#!/usr/bin/env python3
"""Real native GTK field filling inside a disposable X display and accessibility bus."""
import ctypes
import os
from pathlib import Path
import select
import secrets
import shlex
import socket
import subprocess
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from desktop.native import Linux,NativeError


def main():
    if not os.environ.get('LOCKBOX_NATIVE_TEST_BUS'):
        env={**os.environ,'LOCKBOX_NATIVE_TEST_BUS':'1','NO_AT_BRIDGE':'0','GTK_MODULES':'gail:atk-bridge','GNOME_ACCESSIBILITY':'1','GDK_BACKEND':'x11','WAYLAND_DISPLAY':''}
        result=subprocess.run(['dbus-run-session','--',sys.executable,__file__,*sys.argv[1:]],env=env)
        raise SystemExit(result.returncode)
    root_dir=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='lockbox-native-') as tmp:
        root=Path(tmp)
        flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','gtk+-3.0','x11'],text=True))
        subprocess.run(['gcc',str(root_dir/'tests/native_fixture.c'),'-o',str(root/'fixture'),*flags],check=True,capture_output=True)
        with (root/'x.log').open('w+') as log:
            display=next(n for n in (secrets.randbelow(5000)+1000 for _ in range(100)) if not Path('/tmp/.X11-unix/X'+str(n)).exists() and not Path('/tmp/.X'+str(n)+'-lock').exists())
            os.environ['DISPLAY']=':'+str(display);os.environ['XAUTHORITY']=str(root/'xauthority')
            subprocess.run(['xauth','-f',os.environ['XAUTHORITY'],'add',os.environ['DISPLAY'],'MIT-MAGIC-COOKIE-1',secrets.token_hex(16)],check=True,capture_output=True)
            xvfb=subprocess.Popen(['Xvfb',os.environ['DISPLAY'],'-auth',os.environ['XAUTHORITY'],'-screen','0','1024x768x24','-nolisten','tcp'],stdout=subprocess.PIPE,stderr=log,text=True)
            fixture=None;accessibility=None
            try:
                address='unix:path='+str(root/'atspi.sock')
                config=(Path('/usr/share/defaults/at-spi2/accessibility.conf').read_text().replace('unix:dir=/tmp',address))
                (root/'accessibility.conf').write_text(config);os.environ['AT_SPI_BUS_ADDRESS']=address
                accessibility=subprocess.Popen(['dbus-daemon','--nofork','--config-file='+str(root/'accessibility.conf'),'--print-address=1'],stdout=subprocess.PIPE,stderr=log,text=True)
                os.environ['AT_SPI_BUS_ADDRESS']=accessibility.stdout.readline().strip()
                for _ in range(100):
                    if Path('/tmp/.X11-unix/X'+str(display)).exists():break
                    if xvfb.poll() is not None:raise AssertionError('Private X server stopped.')
                    time.sleep(.05)
                fixture=subprocess.Popen([str(root/'fixture')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,text=True,bufsize=1)
                def line():
                    if not select.select([fixture.stdout],[],[],10)[0]:raise AssertionError('Native fixture timed out')
                    return fixture.stdout.readline().rstrip('\n')
                assert line()=='ready'
                def command(value):fixture.stdin.write(value+'\n');fixture.stdin.flush();return line()
                adapter=Linux()
                # Drain AT-SPI registration/focus events using its GLib main context.
                from gi.repository import GLib
                def target(field):
                    response=command('focus-'+field);assert response=='focused',repr(response)
                    for _ in range(50):
                        while GLib.MainContext.default().pending():GLib.MainContext.default().iteration(False)
                        try:
                            captured=adapter.capture()
                            if captured.password==(field=='password'):return captured
                        except NativeError:pass
                        time.sleep(.1)
                    raise AssertionError('Could not capture native '+field+' field')
                user=target('user');assert user.pid==fixture.pid;assert user.identity==str(root/'fixture')
                user.fill('alice-native','username')
                password=target('password');password.fill('disposable-native-secret','password')
                code=target('code');code.fill('123456','code')
                assert command('inspect')=='alice-native\tdisposable-native-secret\t123456'
                if '--packaged-app' in sys.argv:
                    from packaged_ui import exercise
                    exercise(sys.argv[sys.argv.index('--packaged-app')+1],command,fixture.pid,root)
                elif '--desktop-ui' in sys.argv:
                    import json
                    import base64,hashlib,hmac,struct
                    import tkinter as tk
                    from desktop.app import App
                    os.environ['LOCKBOX_CONFIG_DIR']=str(root/'settings')
                    runtime=Path(sys.argv[sys.argv.index('--desktop-runtime')+1]) if '--desktop-runtime' in sys.argv else None
                    ui_root=tk.Tk();app=App(ui_root,runtime_directory=runtime)
                    def spin(predicate,message,seconds=20):
                        deadline=time.monotonic()+seconds
                        while time.monotonic()<deadline:
                            ui_root.update()
                            if predicate():return
                            time.sleep(.02)
                        raise AssertionError(message+': '+app.notice.get())
                    try:
                        for entry,value in [(app.server,os.environ['TEST_SERVER']),(app.email,os.environ['TEST_EMAIL']),(app.master,os.environ['TEST_PASSWORD'])]:
                            entry.delete(0,'end');entry.insert(0,value)
                        next(b for b in app.buttons if b.cget('text')=='Unlock vault').invoke()
                        spin(lambda:not app.busy and app.state['unlocked'],'Desktop UI did not unlock')
                        item=next(i for i in app.state['items'] if i['name']=='Integration fixture')
                        def capture_field(field):
                            app.target=None
                            next(b for b in app.buttons if b.cget('text')=='Capture app field…').invoke()
                            ui_root.after(100,lambda:command('focus-'+field))
                            spin(lambda:app.target is not None,'Desktop capture failed')
                            assert app.target.pid==fixture.pid
                            app.items.selection_set(item['id'])
                        capture_field('user')
                        next(b for b in app.buttons if b.cget('text')=='Fill selected field').invoke()
                        assert 'Link this login' in app.notice.get(),app.notice.get()
                        def confirm_link():
                            try:ui_root.tk.call('.__tk__messagebox.yes','invoke')
                            except tk.TclError:ui_root.after(50,confirm_link)
                        ui_root.after(100,confirm_link)
                        next(b for b in app.buttons if b.cget('text')=='Link login to app').invoke()
                        spin(lambda:not app.busy,'Desktop linking failed')
                        assert app.linked(next(i for i in app.state['items'] if i['id']==item['id']))
                        for field in ['username','password','code']:
                            if field!='username':capture_field('password' if field=='password' else 'code')
                            app.field.set(field)
                            next(b for b in app.buttons if b.cget('text')=='Fill selected field').invoke()
                            spin(lambda:not app.busy,'Desktop filling failed')
                            assert app.notice.get().startswith('Field filled'),app.notice.get()
                        values=command('inspect').split('\t')
                        assert values[0]=='test-user' and values[1]==os.environ['TEST_ITEM_PASSWORD']
                        def otp(counter):
                            digest=hmac.new(base64.b32decode('GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'),struct.pack('>Q',counter),hashlib.sha1).digest();offset=digest[-1]&15
                            return f'{(struct.unpack(">I",digest[offset:offset+4])[0]&0x7fffffff)%1000000:06}'
                        counter=int(time.time())//30;assert values[2] in [otp(counter),otp(counter-1)]
                        settings=json.loads((root/'settings/settings.json').read_text())
                        assert set(settings)=={'server','email','deviceId'}
                        next(b for b in app.buttons if b.cget('text')=='Lock').invoke();spin(lambda:not app.busy and not app.state['unlocked'],'Desktop lock failed')
                        assert not app.items.get_children() and app.target is None
                        print('PASS actual desktop Tk UI: HTTPS unlock, explicit app linking, native username/password/TOTP fill, role checks, private settings and lock')
                    finally:app.close()

                before=command('inspect')
                try:user.fill('must-not-fill','password');raise AssertionError('Password entered a non-password field')
                except NativeError:pass
                try:password.fill('must-not-fill','username');raise AssertionError('Username entered a password field')
                except NativeError:pass
                assert command('hide')=='hidden'
                while GLib.MainContext.default().pending():GLib.MainContext.default().iteration(False)
                time.sleep(.1)
                try:password.fill('must-not-fill','password');raise AssertionError('Hidden password field accepted filling')
                except NativeError:pass
                assert command('show')=='shown'
                for change,expected in [('disable','disabled'),('enable','enabled'),('readonly','readonly')]:
                    assert command(change)==expected
                    while GLib.MainContext.default().pending():GLib.MainContext.default().iteration(False)
                    time.sleep(.1)
                    if change=='enable':continue
                    try:password.fill('must-not-fill','password');raise AssertionError(expected+' password field accepted filling')
                    except NativeError:pass
                assert command('inspect')==before,'Rejected native filling changed field contents'
                fixture.terminate();fixture.wait(timeout=5)
                try:user.fill('must-not-fill','username');raise AssertionError('Closed app accepted filling')
                except NativeError:pass
                print('PASS real native GTK username/password/code filling, role checks, hidden/disabled/read-only-field and closed-app rejection')
            except Exception:
                log.flush();log.seek(0);print(log.read(),file=sys.stderr);raise
            finally:
                if fixture and fixture.poll() is None:fixture.terminate();fixture.wait(timeout=5)
                xvfb.terminate();xvfb.wait(timeout=5)
                if accessibility:accessibility.terminate();accessibility.wait(timeout=5)

if __name__=='__main__':main()
