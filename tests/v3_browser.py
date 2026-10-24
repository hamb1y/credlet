#!/usr/bin/env python3
"""Exercise the actual unified Svelte extension against the disposable C server."""
import argparse
import base64
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import zipfile


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',choices=('chrome','firefox','tauri'),required=True)
    parser.add_argument('--driver',type=Path,required=True)
    parser.add_argument('--chrome',type=Path)
    parser.add_argument('--application',type=Path)
    parser.add_argument('--native-driver',type=Path)
    parser.add_argument('--server',type=Path,default=Path('server/build-v3/credlet-server'))
    parser.add_argument('--screenshot',type=Path)
    args=parser.parse_args()
    extension=Path('extension/dist')/args.engine
    with tempfile.TemporaryDirectory(prefix='credlet v3 browser ') as temporary:
        root=Path(temporary); state=root/'state'; profile=root/'profile'; profile.mkdir()
        pairing=json.loads(subprocess.check_output([str(args.server.resolve()),'init','--state',str(state),'--owner','owner@example.com'],text=True))
        api_port,driver_port=free_port(),free_port()
        address=f'http://127.0.0.1:{api_port}'
        with (root/'server.log').open('w+') as server_log, (root/'driver.log').open('w+') as driver_log:
            server=subprocess.Popen([str(args.server.resolve()),'serve','--state',str(state),'--port',str(api_port)],stdout=server_log,stderr=server_log)
            driver_args=[str(args.driver.resolve()),'--port',str(driver_port),'--allow-system-access','--log','error'] if args.engine=='firefox' else [str(args.driver.resolve()),f'--port={driver_port}']
            if args.engine=='tauri':
                driver_args=[str(args.driver.resolve()),'--port',str(driver_port),'--native-port',str(free_port())]
                if args.native_driver:driver_args.extend(['--native-driver',str(args.native_driver.resolve())])
            driver=subprocess.Popen(driver_args,stdout=driver_log,stderr=driver_log,env={**os.environ,'XDG_CONFIG_HOME':str(root/'config'),'XDG_CACHE_HOME':str(root/'cache'),'XDG_DATA_HOME':str(root/'data')})
            sid=None
            def request(method,path,data=None):
                req=urllib.request.Request(f'http://127.0.0.1:{driver_port}'+path,method=method,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json'})
                try:
                    with urllib.request.urlopen(req,timeout=60) as response: result=json.load(response)['value']
                except urllib.error.HTTPError as error:
                    raise RuntimeError(json.load(error)) from None
                return result
            def command(method,path,data=None):return request(method,'/session/'+sid+path,data)
            def script(code,*values):return command('POST','/execute/sync',{'script':code,'args':values})
            def wait(code,message):
                for _ in range(150):
                    if script(code):return
                    time.sleep(.1)
                raise AssertionError(message+': '+str(script('return document.body.innerText')))
            def button(text):
                script('const b=[...document.querySelectorAll("button")].find(b=>b.textContent.trim()===arguments[0]);if(!b||b.disabled)throw Error("Button unavailable: "+arguments[0]);b.click();',text)
            def fill(fields):
                script('for(const [name,value] of Object.entries(arguments[0])){const l=[...document.querySelectorAll("label")].find(l=>l.textContent.trim().startsWith(name));const input=l?.querySelector("input,textarea");if(!input)throw Error("Missing field "+name);input.value=value;input.dispatchEvent(new Event("input",{bubbles:true}));}',fields)
            try:
                for _ in range(100):
                    try:request('GET','/status');break
                    except OSError:time.sleep(.1)
                if args.engine=='firefox':
                    options={'browserName':'firefox','moz:firefoxOptions':{'args':['-headless','-profile',str(profile)],'prefs':{'browser.shell.checkDefaultBrowser':False}}}
                elif args.engine=='chrome':
                    assert args.chrome,'--chrome is required for Chrome'
                    options={'browserName':'chrome','goog:chromeOptions':{'binary':str(args.chrome.resolve()),'enableExtensionTargets':True,'args':['--headless=new','--no-first-run','--no-default-browser-check','--user-data-dir='+str(profile),'--load-extension='+str(extension.resolve()),'--disable-extensions-except='+str(extension.resolve())]}}
                else:
                    assert args.application,'--application is required for Tauri'
                    options={'tauri:options':{'application':str(args.application.resolve())}}
                sid=request('POST','/session',{'capabilities':{'alwaysMatch':options}})['sessionId']
                if args.engine=='firefox':
                    xpi=io.BytesIO()
                    with zipfile.ZipFile(xpi,'w') as archive:
                        for file in extension.rglob('*'):
                            if file.is_file():archive.write(file,file.relative_to(extension))
                    command('POST','/moz/addon/install',{'addon':base64.b64encode(xpi.getvalue()).decode(),'temporary':True})
                if args.engine!='tauri':command('POST','/window/rect',{'width':420,'height':900})
                found=False
                for _ in range(100):
                    for handle in command('GET','/window/handles'):
                        command('POST','/window',{'handle':handle})
                        if command('GET','/url').startswith(('chrome-extension:','moz-extension:','tauri:','http://tauri.localhost','https://tauri.localhost')):found=True;break
                    if found:break
                    time.sleep(.1)
                assert found,'Extension did not open its UI'
                wait('return [...document.querySelectorAll("button")].some(b=>b.textContent.includes("First time"))','Svelte sign-in did not render')
                button('First time? Set up your vault')
                fill({'Server HTTP address':address,'Server public key':pairing['serverKey'],'Owner email':'owner@example.com','Master password':'disposable v3 master phrase 8482','One-time enrollment token':pairing['enrollmentToken']})
                script('document.querySelector("form").requestSubmit()')
                wait('return document.querySelector("h1")?.textContent.startsWith("Logins")','Encrypted enrollment failed')
                button('+ New login')
                fill({'Name':'Svelte browser fixture','Username':'browser-owner','Password':'private browser password 7482','Website':'https://example.com/login','Authenticator secret':'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ','Encrypted notes':'Only inside the encrypted vault.'})
                script('document.querySelector("form").requestSubmit()')
                wait('return document.querySelector(".logins strong")?.textContent==="Svelte browser fixture"','Save failed')
                script('document.querySelector("input[type=search]").value="no such item";document.querySelector("input[type=search]").dispatchEvent(new Event("input",{bubbles:true}))')
                wait('return document.body.innerText.includes("No matching logins")','Search did not filter')
                button('Clear search')
                script('document.querySelector(".logins button").click()')
                wait('return document.querySelector("h1")?.textContent==="Svelte browser fixture" && !!document.querySelector(".otp")','Detail/TOTP did not open')
                assert script('return document.body.innerText.includes("Only inside the encrypted vault.")')
                button('Show')
                assert script('return document.querySelector(".password").textContent==="private browser password 7482"')
                button('Copy')
                wait('return document.body.innerText.includes("Copied to clipboard.")','Copy failed')
                button('Edit')
                fill({'Name':'Updated Svelte fixture','Encrypted notes':'Updated encrypted notes.'})
                script('document.querySelector("form").requestSubmit()')
                wait('return document.querySelector(".logins strong")?.textContent==="Updated Svelte fixture"','Edit failed')
                if args.screenshot:
                    args.screenshot.parent.mkdir(parents=True,exist_ok=True)
                    args.screenshot.write_bytes(base64.b64decode(command('GET','/screenshot')))
                button('Lock')
                wait('return !!document.querySelector("input[autocomplete=current-password]")','Lock did not restore sign-in')
                assert not script('return document.body.innerText.includes("Updated Svelte fixture")')
                assert script('return document.querySelector("input[autocomplete=current-password]").value===""')
                button('Already have a vault? Sign in') if script('return [...document.querySelectorAll("button")].some(b=>b.textContent.includes("Already have"))') else None
                fill({'Master password':'disposable v3 master phrase 8482'})
                script('document.querySelector("form").requestSubmit()')
                wait('return document.querySelector(".logins strong")?.textContent==="Updated Svelte fixture"','Fresh unlock did not sync saved login')
                print('PASS '+args.engine+' unified Svelte UI: encrypted HTTP enrollment, create/edit, search, notes, reveal, TOTP, lock and fresh unlock')
            finally:
                if sid:
                    try:command('DELETE','')
                    except Exception:pass
                driver.terminate();server.terminate();driver.wait(timeout=10);server.wait(timeout=10)
                server_log.seek(0);assert 'AddressSanitizer' not in server_log.read()


if __name__=='__main__':main()
