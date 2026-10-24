#!/usr/bin/env python3
"""Native Lockbox vault and accessibility filling companion."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import uuid
from desktop.native import backend, NativeError


def config_directory():
    if os.environ.get('LOCKBOX_CONFIG_DIR'): return Path(os.environ['LOCKBOX_CONFIG_DIR'])
    if sys.platform == 'win32': return Path(os.environ.get('APPDATA',Path.home()))/'Lockbox'
    if sys.platform == 'darwin': return Path.home()/'Library/Application Support/Lockbox'
    return Path(os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config'))/'lockbox'


class Rpc:
    def __init__(self, device_id, runtime_directory=None):
        root=Path(__file__).resolve().parents[1]
        if runtime_directory is not None or getattr(sys,'frozen',False):
            directory=Path(runtime_directory) if runtime_directory is not None else Path(sys._MEIPASS)/'runtime'
            node=directory/('node.exe' if sys.platform=='win32' else 'node')
            bridge=directory/'bridge.mjs'
        else:
            node=shutil.which('node');bridge=root/'desktop/bridge.mjs'
            if not node:raise RuntimeError('Install Node.js 22 or newer and run npm ci in the Lockbox project.')
        self.process=subprocess.Popen([str(node),str(bridge)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,text=True,bufsize=1,env={**os.environ,'LOCKBOX_DEVICE_ID':device_id},
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
        self.serial=0

    def call(self, message):
        self.serial+=1;message={**message,'id':self.serial}
        self.process.stdin.write(json.dumps(message)+'\n');self.process.stdin.flush()
        line=self.process.stdout.readline(20*1024*1024)
        if not line or not line.endswith('\n'):raise RuntimeError('The vault process stopped. Restart Lockbox and unlock again.')
        result=json.loads(line)
        if result.get('id')!=self.serial:raise RuntimeError('Invalid vault process response.')
        if not result.get('ok'):raise RuntimeError(result.get('error','Vault request failed.'))
        return result['value']

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait()


class App:
    def __init__(self, root, runtime_directory=None):
        self.root=root;root.title('Lockbox');root.geometry('720x650');root.minsize(590,520)
        self.directory=config_directory();self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        try:self.settings=json.loads((self.directory/'settings.json').read_text())
        except (OSError,ValueError):self.settings={}
        if not isinstance(self.settings,dict):self.settings={}
        self.settings={k:self.settings[k] for k in ('server','email','deviceId') if isinstance(self.settings.get(k),str)}
        self.settings.setdefault('deviceId',str(uuid.uuid4()))
        self.rpc=Rpc(self.settings['deviceId'],runtime_directory);self.pool=ThreadPoolExecutor(max_workers=1)
        self.state={'unlocked':False,'items':[]};self.target=None;self.adapter=None;self.busy=False
        self.buttons=[]
        top=ttk.Frame(root,padding=(20,16));top.pack(fill='x')
        ttk.Label(top,text='Lockbox',font=('TkDefaultFont',21,'bold')).pack(side='left')
        self.button(top,'Lock',lambda:self.run({'type':'lock'},self.render)).pack(side='right')
        self.notice=tk.StringVar(value='Connect to your own vault to fill native application fields.')
        ttk.Label(root,textvariable=self.notice,wraplength=650,padding=(20,8)).pack(fill='x')
        self.signin=ttk.Frame(root,padding=20)
        self.server=self.entry(self.signin,'Server HTTPS address',self.settings.get('server',''))
        self.email=self.entry(self.signin,'Owner email',self.settings.get('email',''))
        self.master=self.entry(self.signin,'Master password',secret=True)
        self.code=self.entry(self.signin,'Vault login code (if enabled)')
        self.button(self.signin,'Unlock vault',self.unlock).pack(anchor='e',pady=12)
        self.master.bind('<Return>',lambda event:self.unlock())
        self.vault=ttk.Frame(root,padding=(20,8))
        toolbar=ttk.Frame(self.vault);toolbar.pack(fill='x')
        self.button(toolbar,'Capture app field…',self.capture).pack(side='left')
        self.button(toolbar,'Sync',lambda:self.run({'type':'sync'},self.render)).pack(side='right')
        self.target_text=tk.StringVar(value='Capture the username, password or code field you want to fill.')
        ttk.Label(self.vault,textvariable=self.target_text,wraplength=650,padding=(0,12)).pack(fill='x')
        filters=ttk.Frame(self.vault);filters.pack(fill='x',pady=(0,10))
        self.query=tk.StringVar();ttk.Entry(filters,textvariable=self.query).pack(side='left',fill='x',expand=True)
        self.only_linked=tk.BooleanVar(value=False)
        ttk.Checkbutton(filters,text='Only linked',variable=self.only_linked,command=self.refresh).pack(side='left',padx=10)
        self.query.trace_add('write',lambda *args:self.refresh())
        table=ttk.Frame(self.vault);table.pack(fill='both',expand=True)
        self.items=ttk.Treeview(table,columns=('name','username','linked'),show='headings',selectmode='browse',height=10)
        for column,label,width in [('name','Login',240),('username','Username',220),('linked','Linked',70)]:
            self.items.heading(column,text=label);self.items.column(column,width=width,minwidth=60,stretch=column!='linked')
        scroll=ttk.Scrollbar(table,orient='vertical',command=self.items.yview);self.items.configure(yscrollcommand=scroll.set)
        self.items.pack(side='left',fill='both',expand=True);scroll.pack(side='right',fill='y')
        actions=ttk.Frame(self.vault);actions.pack(fill='x',pady=12)
        self.field=tk.StringVar(value='username')
        ttk.Combobox(actions,textvariable=self.field,values=('username','password','code'),state='readonly',width=13).pack(side='left')
        self.button(actions,'Fill selected field',self.fill).pack(side='left',padx=8)
        self.button(actions,'Link login to app',self.link).pack(side='right')
        ttk.Label(self.vault,text='Fills the captured field directly. Review and submit in the application. Manage logins and passkeys in the browser extension or web vault.',
            wraplength=650).pack(fill='x',pady=(0,10))
        root.protocol('WM_DELETE_WINDOW',self.close)
        if sys.platform == 'darwin':
            # The Mac application menu / Command-Q has a distinct Tk callback.
            # Route it through bridge shutdown as well as the window close button.
            root.createcommand('::tk::mac::Quit',self.close)
        root.after(1000,self.tick)
        self.render(self.state)

    def button(self,parent,text,command):
        button=ttk.Button(parent,text=text,command=command);self.buttons.append(button);return button

    @staticmethod
    def entry(parent,label,value='',secret=False):
        ttk.Label(parent,text=label).pack(anchor='w',pady=(8,4))
        entry=ttk.Entry(parent,show='•' if secret else '',width=55);entry.insert(0,value);entry.pack(fill='x');return entry

    def save_settings(self):
        temporary=self.directory/'settings.tmp'
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as f:json.dump(self.settings,f)
        os.replace(temporary,self.directory/'settings.json')

    def run(self,message,done):
        if self.busy:return
        self.busy=True;self.notice.set('Working…')
        for button in self.buttons:button.state(['disabled'])
        future=self.pool.submit(self.rpc.call,message)
        def poll():
            if not future.done():self.root.after(50,poll);return
            self.busy=False
            for button in self.buttons:button.state(['!disabled'])
            try:self.notice.set('');done(future.result())
            except Exception as error:self.notice.set(str(error))
        self.root.after(50,poll)

    def unlock(self):
        password=self.master.get();self.master.delete(0,'end')
        code=self.code.get();self.code.delete(0,'end')
        server=self.server.get().strip();email=self.email.get().strip().lower()
        def done(value):
            self.settings.update(server=server.rstrip('/'),email=email);self.save_settings();self.render(value)
        self.run({'type':'login','server':server,'email':email,'password':password,'code':code},done)

    def render(self,state):
        self.state=state
        self.signin.pack_forget();self.vault.pack_forget()
        if state['unlocked']:self.vault.pack(fill='both',expand=True)
        else:
            self.signin.pack(fill='x');self.target=None;self.target_text.set('Capture the field you want to fill.');self.master.delete(0,'end')
        self.refresh()

    def linked(self,item):
        return self.target and any(u['uri']==self.target.uri and u.get('match')!=5 for u in item['uris'])

    def refresh(self):
        selected=self.items.selection();self.items.delete(*self.items.get_children())
        query=self.query.get().casefold()
        for item in self.state['items']:
            linked=self.linked(item)
            if self.only_linked.get() and not linked:continue
            if query not in (item['name']+' '+item['username']).casefold():continue
            self.items.insert('', 'end',iid=item['id'],values=(item['name'],item['username'],'Yes' if linked else ''))
        if selected and self.items.exists(selected[0]):self.items.selection_set(selected)

    def capture(self):
        if self.busy:return
        self.notice.set('Focus the desired field in your application. Capturing in three seconds…')
        self.root.withdraw()
        def capture_now():
            try:
                self.adapter=self.adapter or backend();self.target=self.adapter.capture()
                self.target_text.set(('Password' if self.target.password else 'Text')+' field in '+self.target.name+'\n'+self.target.identity)
                self.field.set('password' if self.target.password else 'username')
                self.only_linked.set(False);self.notice.set('Select a linked login, or link a login to this application first.');self.refresh()
            except Exception as error:self.target=None;self.target_text.set('Capture a field to continue.');self.notice.set(str(error))
            finally:self.root.deiconify();self.root.lift()
        self.root.after(3000,capture_now)

    def selected(self):
        if not self.target:raise NativeError('Capture an application field first.')
        selection=self.items.selection()
        if not selection:raise NativeError('Select a login first.')
        return next(i for i in self.state['items'] if i['id']==selection[0])

    def message(self,item,kind):
        result={'type':kind,'itemId':item['id'],'appUri':self.target.uri}
        if item['reprompt']:
            password=simpledialog.askstring('Verify master password','Master password for this protected login:',show='•',parent=self.root)
            if password is None:return None
            result['password']=password
        return result

    def fill(self):
        try:
            item=self.selected()
            if not self.linked(item):raise NativeError('Link this login to the captured application first.')
            target=self.target;field=self.field.get();message=self.message(item,'fill')
            if message is None:return
            message['field']=field
            def done(result):
                value=result.pop('value');target.fill(value,field);self.notice.set('Field filled. Review and submit in the application.')
            self.run(message,done)
        except Exception as error:self.notice.set(str(error))

    def link(self):
        try:
            item=self.selected()
            if not messagebox.askyesno('Link login to application',f'Allow “{item["name"]}” to fill fields in this application?\n\n{self.target.identity}',parent=self.root):return
            message=self.message(item,'link')
            if message is not None:self.run(message,self.render)
        except Exception as error:self.notice.set(str(error))

    def tick(self):
        if self.state['unlocked'] and time.time()*1000>=self.state['deadline'] and not self.busy:self.run({'type':'lock'},self.render)
        self.root.after(1000,self.tick)

    def close(self):
        self.rpc.close();self.pool.shutdown(wait=False,cancel_futures=True);self.root.destroy()


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-runtime',action='store_true',help='Check bundled dependencies without unlocking a vault.')
    parser.add_argument('--report',type=Path,help='Write runtime-check results to a JSON file.')
    args=parser.parse_args()
    if args.check_runtime:
        rpc=None
        try:
            if sys.platform=='linux':
                import gi
                gi.require_version('Atspi','2.0')
                from gi.repository import Atspi
                assert Atspi.Role.PASSWORD_TEXT
            elif sys.platform in ('win32','darwin'):backend()
            rpc=Rpc(str(uuid.uuid4()))
            state=rpc.call({'type':'status'})
            if state['unlocked'] or state['items']:raise RuntimeError('Vault process did not start locked.')
            report={'ok':True,'platform':sys.platform,'python':sys.version.split()[0],
                'tk':tk.Tcl().eval('info patchlevel'),'bundled':bool(getattr(sys,'frozen',False)),'vaultLocked':True}
        except Exception as error:report={'ok':False,'error':str(error)}
        finally:
            if rpc:rpc.close()
        if args.report:args.report.write_text(json.dumps(report,indent=2)+'\n')
        if sys.stdout:print(json.dumps(report))
        raise SystemExit(0 if report['ok'] else 1)
    root=tk.Tk()
    try:App(root)
    except Exception as error:messagebox.showerror('Lockbox',str(error),parent=root);root.destroy();return
    root.mainloop()

if __name__=='__main__':main()
