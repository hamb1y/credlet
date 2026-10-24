"""Drive the actual frozen Tk application over its private, authenticated X display."""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import time


def exercise(executable,fixture_command,fixture_pid,root_dir):
    import tkinter as tk
    root=Path(root_dir)
    environment={**os.environ,'CREDLET_CONFIG_DIR':str(root/'packaged-settings'),'PATH':'/nonexistent'}
    for name in ('TCL_LIBRARY','TK_LIBRARY','LD_LIBRARY_PATH','PYTHONPATH','PYTHONHOME','GI_TYPELIB_PATH'):environment.pop(name,None)
    executable=Path(executable).resolve()
    runtime=subprocess.run([str(executable),'--check-runtime'],env=environment,capture_output=True,text=True,check=True,timeout=15)
    assert json.loads(runtime.stdout)['bundled']
    controller=tk.Tk();controller.withdraw();own=controller.tk.call('tk','appname')
    with (root/'packaged.log').open('w+') as log:
        process=subprocess.Popen([str(executable)],env=environment,stdout=log,stderr=log,start_new_session=True)
        interpreter=None
        def wait(predicate,message,seconds=20):
            deadline=time.monotonic()+seconds
            while time.monotonic()<deadline:
                controller.update()
                if process.poll() is not None:raise AssertionError('Packaged application stopped.')
                value=predicate()
                if value:return value
                time.sleep(.03)
            raise AssertionError(message)
        def call(*words):return controller.tk.call('send',interpreter,words)
        def asynchronous(*words):return controller.tk.call('send','-async',interpreter,words)
        def split(value):return controller.tk.splitlist(value)
        def widgets(parent='.'):
            result=[]
            for child in split(call('winfo','children',parent)):
                result.append(child);result.extend(widgets(child))
            return result
        def find(kind,text=None):
            for widget in widgets():
                if call('winfo','class',widget)==kind and (text is None or call(widget,'cget','-text')==text):return widget
            raise AssertionError('Missing packaged UI control: '+str(text or kind))
        try:
            interpreter=wait(lambda:next((i for i in split(controller.tk.call('winfo','interps')) if i!=own),None),'No packaged Tk interpreter appeared.')
            entries=[w for w in widgets() if call('winfo','class',w)=='TEntry']
            # Widget order follows the sign-in form: server, email, master password, login code.
            for widget,value in zip(entries[:3],[os.environ['TEST_SERVER'],os.environ['TEST_EMAIL'],os.environ['TEST_PASSWORD']]):
                call(widget,'delete',0,'end');call(widget,'insert',0,value)
            labels=[w for w in widgets() if call('winfo','class',w)=='TLabel']
            notice_var=next(call(w,'cget','-textvariable') for w in labels if call(w,'cget','-textvariable') and
                str(call('set',call(w,'cget','-textvariable'))).startswith('Connect to your own vault'))
            notice=lambda:str(call('set',notice_var))
            call(find('TButton','Unlock vault'),'invoke')
            tree=find('Treeview')
            wait(lambda:bool(split(call(tree,'children',''))),'Packaged UI did not unlock: '+notice())
            item=next(i for i in split(call(tree,'children','')) if split(call(tree,'item',i,'-values'))[0]=='Integration fixture')
            def capture(field):
                call(find('TButton','Capture app field…'),'invoke')
                assert fixture_command('focus-'+field)=='focused'
                wait(lambda:notice().startswith('Select a linked login'),'Packaged capture failed: '+notice())
                call(tree,'selection','set',item)
            capture('user')
            call(find('TButton','Fill selected field'),'invoke')
            assert 'Link this login' in notice(),notice()
            asynchronous(find('TButton','Link login to app'),'invoke')
            wait(lambda:call('winfo','exists','.__tk__messagebox.yes'),'Link confirmation did not open.')
            asynchronous('.__tk__messagebox.yes','invoke')
            wait(lambda:split(call(tree,'item',item,'-values'))[-1]=='Yes','Packaged app link did not save.')
            for field in ('username','password','code'):
                if field!='username':capture('password' if field=='password' else 'code')
                call(find('TCombobox'),'set',field)
                call(find('TButton','Fill selected field'),'invoke')
                wait(lambda:notice().startswith('Field filled'),'Packaged native fill failed: '+notice())
            values=fixture_command('inspect').split('\t')
            assert values[0]=='test-user' and values[1]==os.environ['TEST_ITEM_PASSWORD']
            def otp(counter):
                digest=hmac.new(base64.b32decode('GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'),struct.pack('>Q',counter),hashlib.sha1).digest();offset=digest[-1]&15
                return f'{(struct.unpack(">I",digest[offset:offset+4])[0]&0x7fffffff)%1000000:06}'
            counter=int(time.time())//30;assert values[2] in (otp(counter),otp(counter-1))
            settings=json.loads((root/'packaged-settings/settings.json').read_text());assert set(settings)=={'server','email','deviceId'}
            call(find('TButton','Lock'),'invoke')
            wait(lambda:not split(call(tree,'children','')),'Packaged application did not clear the vault on lock.')
            close=split(call('wm','protocol','.','WM_DELETE_WINDOW'))
            asynchronous(*close)
            deadline=time.monotonic()+8
            while process.poll() is None and time.monotonic()<deadline:
                controller.update();time.sleep(.03)
            process.wait(timeout=1)
            assert process.returncode==0
            print('PASS actual frozen desktop application: bundled runtime, HTTPS unlock, explicit app link, native username/password/TOTP fill, private settings and lock')
        finally:
            if process.poll() is None:os.killpg(process.pid,signal.SIGTERM);process.wait(timeout=5)
            controller.destroy()
