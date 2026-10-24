#!/usr/bin/env python3
"""Start/status/stop the isolated Linux Android acceptance emulator (never a physical device)."""
import argparse
import json
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'.tools/android-test'
SDK=ROOT/'.tools/android-sdk'
SESSION=STATE/'session.json'
SCRIPT=Path(__file__).resolve()


def live(pid,marker):
    try:
        command=(Path('/proc')/str(pid)/'cmdline').read_bytes()
        return marker.encode() in command
    except OSError:return False


def read():
    try:return json.loads(SESSION.read_text())
    except (OSError,ValueError):return {}


def environment():
    return {**os.environ,'HOME':str(STATE/'home'),'ANDROID_AVD_HOME':str(STATE/'avds'),
        'ANDROID_USER_HOME':str(STATE/'user'),'ANDROID_EMULATOR_HOME':str(STATE/'user'),
        'ANDROID_HOME':str(SDK),'ANDROID_SDK_ROOT':str(SDK),'ANDROID_ADB_SERVER_PORT':'5038',
        'ADB_SERVER_SOCKET':'tcp:127.0.0.1:5038'}


def available(port):
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        try:probe.bind(('127.0.0.1',port))
        except OSError:raise RuntimeError(f'Test port {port} is occupied; no existing service was stopped.') from None


def status():
    state=read();running=live(state.get('supervisorPid',0),str(SCRIPT)) and live(state.get('pid',0),'qemu-system-')
    result={'running':running,'serial':state.get('serial'),'sdk':str(SDK),'adbPort':5038,'image':state.get('image','aosp')}
    if running:
        try:
            output=subprocess.run([str(SDK/'platform-tools/adb'),'-P','5038','-s','emulator-5580','shell','getprop','sys.boot_completed'],
                capture_output=True,text=True,timeout=3,env=environment())
            result['booted']=output.returncode==0 and output.stdout.strip()=='1'
        except subprocess.TimeoutExpired:result['booted']=False
    return result


def serve(image='aosp'):
    avd='lockbox-google-apis' if image=='google-apis' else 'lockbox'
    tag='google_apis' if image=='google-apis' else 'default'
    ram='3072' if image=='google-apis' else '2048'
    image_root=SDK/'system-images/android-35'/tag/'x86_64'
    if not (image_root/'system.img').is_file():raise RuntimeError('Fetch the selected Android image before starting it.')
    for port in (5037,5038,5580,5581):available(port)
    for folder in ('home','user','avds/'+avd+'.avd'):(STATE/folder).mkdir(parents=True,exist_ok=True)
    data=STATE/('avds/'+avd+'.avd')
    (STATE/('avds/'+avd+'.ini')).write_text('avd.ini.encoding=UTF-8\npath='+str(data)+'\ntarget=android-35\n')
    config={'AvdId':avd,'avd.ini.displayname':'Lockbox acceptance','hw.cpu.arch':'x86_64','abi.type':'x86_64',
        'hw.ramSize':ram,'hw.lcd.width':'720','hw.lcd.height':'1280','hw.lcd.density':'320','hw.keyboard':'yes',
        'hw.gpu.enabled':'yes','hw.gpu.mode':'swiftshader_indirect','disk.dataPartition.size':'4G',
        'image.sysdir.1':str(image_root),'tag.id':tag,'PlayStore.enabled':'false','fastboot.forceColdBoot':'yes'}
    (data/'config.ini').write_text(''.join(k+'='+v+'\n' for k,v in config.items()))
    stopping=threading.Event()
    for number in (signal.SIGTERM,signal.SIGINT):signal.signal(number,lambda *_:stopping.set())
    children=[];logs=[];listener=None
    try:
        def spawn(command,logname):
            log=(STATE/logname).open('w');logs.append(log)
            process=subprocess.Popen(command,env=environment(),stdout=log,stderr=log)
            children.append(process);return process
        adb=spawn([str(SDK/'platform-tools/adb'),'-L','tcp:5038','nodaemon','server'],'adb.log')
        for _ in range(50):
            if adb.poll() is not None:raise RuntimeError('Test ADB server stopped; inspect .tools/android-test/adb.log.')
            try:
                with socket.create_connection(('127.0.0.1',5038),timeout=.1):break
            except OSError:time.sleep(.1)
        else:raise RuntimeError('Test ADB server did not become ready.')
        # mozdevice uses fixed port 5037. Relay only to this private server, never a user's server.
        listener=socket.socket();listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);listener.bind(('127.0.0.1',5037));listener.listen();listener.settimeout(.5)
        def relay(client):
            upstream=None
            try:
                upstream=socket.create_connection(('127.0.0.1',5038),timeout=3)
                while not stopping.is_set():
                    readable,_,_=select.select([client,upstream],[],[],1)
                    for source in readable:
                        chunk=source.recv(65536)
                        if not chunk:return
                        (upstream if source is client else client).sendall(chunk)
            except OSError:pass
            finally:
                client.close()
                if upstream:upstream.close()
        emulator=spawn([str(SDK/'emulator/emulator'),'-avd',avd,'-port','5580','-no-window','-gpu','swiftshader_indirect',
            '-no-audio','-no-boot-anim','-no-snapshot','-camera-back','none','-camera-front','none','-memory',ram,'-cores','2','-no-metrics'],'emulator.log')
        state={'supervisorPid':os.getpid(),'pid':emulator.pid,'adbPid':adb.pid,'adbPort':5038,'serial':'emulator-5580',
            'avdHome':str(STATE/'avds'),'sdk':str(SDK),'home':str(STATE/'home'),'userHome':str(STATE/'user'),'image':image}
        temporary=SESSION.with_suffix('.tmp');temporary.write_text(json.dumps(state,indent=2)+'\n');temporary.replace(SESSION)
        while not stopping.is_set():
            if any(p.poll() is not None for p in children):raise RuntimeError('An Android test process stopped; inspect its log.')
            try:client,_=listener.accept()
            except socket.timeout:continue
            threading.Thread(target=relay,args=(client,),daemon=True).start()
    finally:
        stopping.set()
        if listener:listener.close()
        for process in reversed(children):
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait()
        for log in logs:log.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['start','status','stop','_serve'])
    parser.add_argument('--image',choices=['aosp','google-apis'],default='aosp');args=parser.parse_args()
    if sys.platform!='linux':parser.error('This fixture currently supports Linux hosts only.')
    if args.action=='_serve':serve(args.image);return
    state=read();supervisor=state.get('supervisorPid',0)
    if args.action=='start':
        if status()['running']:
            if state.get('image','aosp')!=args.image:parser.error('Stop the running test emulator before selecting another image.')
            print(json.dumps(status()));return
        if live(state.get('pid',0),'qemu-system-'):raise RuntimeError('An unmanaged test emulator is still running. Stop it before starting this controller.')
        STATE.mkdir(parents=True,exist_ok=True)
        with (STATE/'supervisor.log').open('w') as log:
            process=subprocess.Popen([sys.executable,str(SCRIPT),'_serve','--image',args.image],stdout=log,stderr=log,start_new_session=True)
        for _ in range(100):
            if process.poll() is not None:raise RuntimeError('Android fixture startup failed; inspect .tools/android-test/supervisor.log.')
            if read().get('supervisorPid')==process.pid:print(json.dumps(status()));return
            time.sleep(.1)
        raise RuntimeError('Android fixture startup timed out.')
    elif args.action=='stop':
        if live(supervisor,str(SCRIPT)):
            os.kill(supervisor,signal.SIGTERM)
            for _ in range(150):
                if not live(supervisor,str(SCRIPT)):break
                time.sleep(.1)
            else:raise RuntimeError('Android fixture has not finished stopping; inspect its processes before retrying.')
        print(json.dumps(status()))
    else:print(json.dumps(status()))


if __name__=='__main__':main()
