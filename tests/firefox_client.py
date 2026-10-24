#!/usr/bin/env python3
"""Install a built Firefox/Chrome extension; exercise its UI against disposable fixtures."""
import argparse
import base64
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import zipfile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    engines=p.add_mutually_exclusive_group(required=True)
    engines.add_argument('--geckodriver', type=Path)
    engines.add_argument('--chromedriver', type=Path)
    p.add_argument('--chrome',type=Path)
    p.add_argument('--screenshot', type=Path)
    p.add_argument('--android-package')
    p.add_argument('--android-serial',default='emulator-5580')
    p.add_argument('--adb',type=Path)
    p.add_argument('--adb-port',type=int,default=5037)
    args = p.parse_args()
    if args.chromedriver and not args.chrome:p.error('--chromedriver requires --chrome')
    if args.android_package and (not args.geckodriver or not args.adb):p.error('Android requires --geckodriver and --adb')
    firefox=bool(args.geckodriver)
    server = os.environ['TEST_SERVER']
    marker = os.environ['TEST_ITEM_PASSWORD']
    extension = Path(__file__).resolve().parents[1] / ('extension/dist/firefox' if firefox else 'extension/dist/chrome')
    with tempfile.TemporaryDirectory(prefix='lockbox-browser-') as tmp:
        root = Path(tmp); profile = root / 'profile'; profile.mkdir()
        for command in (['certutil','-N','--empty-password','-d','sql:'+str(profile)],
                        ['certutil','-A','-n','Lockbox fixture','-t','C,,','-d','sql:'+str(profile),'-i',os.environ['TEST_CERT']]):
            subprocess.run(command, check=True, capture_output=True)
        if not firefox:
            for db in [root/'.pki/nssdb',root/'share/pki/nssdb']:
                db.mkdir(parents=True)
                subprocess.run(['certutil','-N','--empty-password','-d','sql:'+str(db)],check=True,capture_output=True)
                subprocess.run(['certutil','-A','-n','Lockbox fixture','-t','C,,','-d','sql:'+str(db),'-i',os.environ['TEST_CERT']],check=True,capture_output=True)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); port = sock.getsockname()[1]
        log = (root / 'driver.log').open('w+')
        driver_args=[str(args.geckodriver.resolve()),'--port',str(port),'--allow-system-access','--log','error'] if firefox else [str(args.chromedriver.resolve()),'--port='+str(port)]
        if args.android_package:driver_args.extend(['--android-storage','sdcard'])
        test_env={**os.environ,'HOME':str(root),'XDG_CONFIG_HOME':str(root/'config'),'XDG_DATA_HOME':str(root/'share'),'XDG_CACHE_HOME':str(root/'cache')}
        driver = subprocess.Popen(driver_args, stdout=log, stderr=log,env=test_env)
        base = f'http://127.0.0.1:{port}'
        sid = None

        def request(method, path, data=None):
            r = urllib.request.Request(base + path, method=method,
                data=None if data is None else json.dumps(data).encode(), headers={'Content-Type':'application/json'})
            try:
                with urllib.request.urlopen(r,timeout=60) as response: result = json.load(response)['value']
            except urllib.error.HTTPError as error:
                value = json.load(error).get('value',{})
                raise RuntimeError('WebDriver: '+value.get('error','request failed') + ': ' + value.get('message','')) from None
            if isinstance(result,dict) and result.get('error'): raise RuntimeError(result['error'])
            return result

        def command(method, path, data=None): return request(method, '/session/'+sid+path, data)
        def script(code, *values): return command('POST','/execute/sync',{'script':code,'args':values})
        def wait(code, message):
            for _ in range(150):
                if script(code): return
                time.sleep(.1)
            raise AssertionError(message + ': ' + str(script('return document.querySelector("#notice")?.textContent')))
        def click(selector):
            element = command('POST','/element',{'using':'css selector','value':selector})
            command('POST','/element/'+element['element-6066-11e4-a52e-4f735466cecf']+'/click',{})
        def choose(name):
            script('const b=[...document.querySelectorAll("#items button")].find(b=>b.querySelector("strong").textContent===arguments[0]); if(!b)throw Error("Missing fixture"); b.click();',name)
            wait('return !document.querySelector("#detail").hidden','Detail did not open')
        try:
            for _ in range(100):
                try: request('GET','/status'); break
                except OSError: time.sleep(.1)
            options={'browserName':'firefox','moz:firefoxOptions':{'args':['-headless','-profile',str(profile)],
                'prefs':{'browser.shell.checkDefaultBrowser':False,'datareporting.policy.dataSubmissionEnabled':False}}} if firefox else {
                'browserName':'chrome','goog:chromeOptions':{'binary':str(args.chrome.resolve()),'enableExtensionTargets':True,
                    'args':['--headless=new','--user-data-dir='+str(profile),'--no-first-run','--no-default-browser-check',
                        '--load-extension='+str(extension),'--disable-extensions-except='+str(extension)]}}
            if args.android_package:
                profile_zip=io.BytesIO()
                with zipfile.ZipFile(profile_zip,'w') as bundle:
                    for file in profile.iterdir():bundle.write(file,file.name)
                firefox_options=options['moz:firefoxOptions'];firefox_options.pop('args')
                firefox_options.update(androidPackage=args.android_package,androidDeviceSerial=args.android_serial,
                    profile=base64.b64encode(profile_zip.getvalue()).decode())
                tls_port=urlsplit(server).port or 443
                subprocess.run([str(args.adb.resolve()),'-P',str(args.adb_port),'-s',args.android_serial,'reverse','tcp:'+str(tls_port),'tcp:'+str(tls_port)],check=True,capture_output=True)
            session = request('POST','/session',{'capabilities':{'alwaysMatch':options}})
            sid = session['sessionId']
            if firefox and not args.android_package: assert Path(session['capabilities']['moz:profile']).resolve() == profile.resolve(), session['capabilities']['moz:profile']
            if args.android_package:assert session['capabilities']['platformName']=='android'
            else:command('POST','/window/rect',{'width':390,'height':844})
            if args.android_package:
                from android_ui import AndroidUi
                android_ui=AndroidUi(args.adb.resolve(),args.android_serial,args.adb_port)
                android_ui.firefox_setup(args.android_package)
            if firefox:
                command('POST','/url',{'url':server+'/alive'})
                assert 'certerror' not in command('GET','/url'), 'Temporary Firefox profile did not trust the fixture certificate'
                xpi = io.BytesIO()
                with zipfile.ZipFile(xpi,'w') as z:
                    for file in extension.iterdir(): z.write(file,file.name)
                assert command('POST','/moz/addon/install',{'addon':base64.b64encode(xpi.getvalue()).decode(),'temporary':True}) == 'lockbox@selfhost.local'
                if args.android_package:android_ui.firefox_setup(args.android_package)
            url = None
            for _ in range(100):
                for handle in command('GET','/window/handles'):
                    command('POST','/window',{'handle':handle})
                    candidate = command('GET','/url')
                    if candidate.startswith(('moz-extension:','chrome-extension:')): url = candidate; break
                if url: break
                time.sleep(.1)
            if not url: raise AssertionError('Installed extension did not open its UI')
            extension_handle = command('GET','/window')
            # Extension API is used only to create a fixture tab. All credential operations use UI controls.
            target = command('POST','/execute/async',{'script':'const done=arguments[arguments.length-1];(globalThis.browser||chrome).tabs.create({url:arguments[0],active:false}).then(t=>done(t.id));','args':[server+'/fixture/login']})
            command('POST','/url',{'url':url.split('?')[0]+'?target='+str(target)})
            wait('return !!document.querySelector("#signin")','UI did not load')
            script('for(const [id,value] of Object.entries(arguments[0])) document.getElementById(id).value=value; document.getElementById("signin").requestSubmit();',
                {'server':server,'email':os.environ['TEST_EMAIL'],'master':os.environ['TEST_PASSWORD']})
            wait('return !document.querySelector("#vault").hidden','Extension sign-in failed')
            choose('Integration fixture')
            click('#fill')
            wait('return document.querySelector("#notice").textContent.includes("does not match")','Origin mismatch was not rejected')
            click('#back'); click('#add')
            script('for(const [id,value] of Object.entries(arguments[0])) document.getElementById(id).value=value; document.getElementById("editor").requestSubmit();',
                {'name':'Browser UI fixture','uri':server,'username':'browser-user','password':marker,'totp':'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'})
            wait('return !document.querySelector("#vault").hidden && document.querySelector("#notice").textContent.includes("saved")','UI save failed')
            choose('Browser UI fixture')
            wait('return /^\\d{6}$/.test(document.querySelector("#otp").textContent)','TOTP not displayed')
            assert script("return document.documentElement.scrollWidth <= document.documentElement.clientWidth"), "Narrow UI overflows horizontally"
            if args.screenshot:
                args.screenshot.parent.mkdir(parents=True,exist_ok=True)
                args.screenshot.write_bytes(base64.b64decode(command('GET','/screenshot')))
            click('#fill')
            wait('return document.querySelector("#notice").textContent.includes("Login filled")','UI filling failed')
            fixture_handle = None
            for handle in command('GET','/window/handles'):
                command('POST','/window',{'handle':handle})
                if command('GET','/url').startswith(server+'/fixture/login'): fixture_handle = handle; break
            assert fixture_handle
            assert script('return document.querySelector("#user").value===arguments[0] && document.querySelector("#pass").value===arguments[1]', 'browser-user',marker)
            assert not script('return !!window.submitted'), 'Filling must not submit the form'
            command('POST','/window',{'handle':extension_handle})
            click('#fill-code');wait('return document.querySelector("#notice").textContent.includes("code filled")','TOTP filling failed')
            command('POST','/window',{'handle':fixture_handle})
            assert script('return /^\\d{6}$/.test(document.querySelector("#otp-field").value)'), 'Code field was not filled'
            command('POST','/window',{'handle':extension_handle})
            click('#edit')
            wait('return !document.querySelector("#editor").hidden','Edit form did not open')
            script('document.querySelector("#username").value="edited-browser-user";document.querySelector("#editor").requestSubmit();')
            wait('return !document.querySelector("#vault").hidden','Edit did not save')
            choose('Browser UI fixture')
            assert script('return document.querySelector("#detail-username").value') == 'edited-browser-user'
            # Trash a separate fixture through the UI; keep the original for independent-client checks.
            click('#back');click('#add')
            script('for(const [id,value] of Object.entries(arguments[0]))document.getElementById(id).value=value;document.getElementById("editor").requestSubmit();',
                {'name':'Trash UI fixture','uri':server,'username':'trash-user','password':marker})
            wait('return !document.querySelector("#vault").hidden','Trash fixture did not save')
            choose('Trash UI fixture');click('#delete')
            assert script('return !document.querySelector("#trash-confirm").hidden')
            click('#trash-cancel');wait('return !document.querySelector("#detail").hidden','Trash cancellation failed')
            click('#delete');click('#trash-submit')
            wait('return !document.querySelector("#vault").hidden','Trash did not finish')
            assert not script('return document.querySelector("#items").textContent.includes("Trash UI fixture")')
            choose('Browser UI fixture')
            command('POST','/window',{'handle':fixture_handle})
            script('document.querySelector("form").action="https://foreign.example/";document.querySelector("#user").value="";document.querySelector("#pass").value="";')
            command('POST','/window',{'handle':extension_handle})
            click('#fill')
            wait('return document.querySelector("#notice").textContent.includes("No visible login fields")','Cross-origin form submission was not rejected')
            command('POST','/window',{'handle':fixture_handle})
            assert script('return document.querySelector("#pass").value===""'), 'Cross-origin form received a secret'
            # Invoke the website's public Credentials API. Lockbox must ask in its own tab.
            command('POST','/window',{'handle':fixture_handle})
            baseline_handles=set()
            def begin_passkey(kind, options):
                nonlocal baseline_handles
                if not firefox or args.android_package:
                    command('POST','/window',{'handle':extension_handle})
                    command('POST','/execute/async',{'script':'const done=arguments[arguments.length-1];(globalThis.browser||chrome).tabs.update(arguments[0],{active:true}).then(()=>done(true));','args':[target]})
                    command('POST','/window',{'handle':fixture_handle})
                script("""
                  window.passkeyResult=null;window.passkeyError=null;
                  const options=arguments[1],kind=arguments[0];
                  const b=s=>Uint8Array.from(atob(s.replace(/-/g,'+').replace(/_/g,'/')),c=>c.charCodeAt(0));
                  options.challenge=b(options.challenge);if(options.user)options.user.id=b(options.user.id);
                  for(const key of ['allowCredentials','excludeCredentials'])if(options[key])options[key].forEach(c=>c.id=b(c.id));
                  let button=document.querySelector('#start-passkey');
                  if(!button){button=document.createElement('button');button.type='button';button.id='start-passkey';button.textContent='Passkey';document.body.append(button);}
                  button.onclick=()=>navigator.credentials[kind]({publicKey:options,signal:(window.passkeyAbort=new AbortController()).signal}).then(c=>{
                    window.passkeyResult=c.toJSON();window.passkeyShape={credential:c instanceof PublicKeyCredential,id:c.rawId instanceof ArrayBuffer,data:c.response.clientDataJSON instanceof ArrayBuffer,tag:Object.prototype.toString.call(c.rawId),responseTag:Object.prototype.toString.call(c.response.clientDataJSON)};
                  }).catch(e=>window.passkeyError={name:e.name,message:e.message});
                """,kind,options)
                baseline_handles=set(command('GET','/window/handles'))
                click('#start-passkey')
            def approval_tab():
                for _ in range(100):
                    for h in command('GET','/window/handles'):
                        if h in baseline_handles: continue
                        command('POST','/window',{'handle':h})
                        if '?passkey=' in command('GET','/url'):
                            wait('return !document.querySelector("#approval").hidden','Passkey approval did not load')
                            return h
                    time.sleep(.1)
                command('POST','/window',{'handle':fixture_handle})
                raise AssertionError('No passkey approval tab: '+str(script('return window.passkeyError')))
            def approve(password):
                script('document.querySelector("#approval-password").value=arguments[0];document.querySelector("#approval").requestSubmit();',password)
            def result():
                command('POST','/window',{'handle':fixture_handle})
                wait('return !!(window.passkeyResult || window.passkeyError)','Website did not receive passkey response')
                error=script('return window.passkeyError');assert error is None,error
                shape=script('return window.passkeyShape');assert shape['credential'] and shape['tag']=='[object ArrayBuffer]' and shape['responseTag']=='[object ArrayBuffer]',shape
                return script('return window.passkeyResult')
            challenge=base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip('=')
            handle=base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip('=')
            options={'challenge':challenge,'rp':{'id':'localhost','name':'Lockbox WebAuthn fixture'},
                'user':{'id':handle,'name':'passkey-user','displayName':'Passkey test'},'pubKeyCredParams':[{'type':'public-key','alg':-7}],
                'authenticatorSelection':{'residentKey':'required','userVerification':'required'},'extensions':{'credProps':True},'timeout':120000}
            begin_passkey('create',options); approval_tab()
            assert script('return document.querySelector("#approval-origin").textContent') == server
            if args.screenshot:args.screenshot.with_stem(args.screenshot.stem+'-passkey').write_bytes(base64.b64decode(command('GET','/screenshot')))
            approve('incorrect fixture password')
            wait('return document.querySelector("#notice").textContent.includes("verification failed")','Wrong master password was not rejected')
            approve(os.environ['TEST_PASSWORD'])
            registration=result()
            assertion_challenge=base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip('=')
            get_options={'challenge':assertion_challenge,'rpId':'localhost','userVerification':'required',
                'allowCredentials':[{'id':registration['id'],'type':'public-key'}],'timeout':120000}
            begin_passkey('get',get_options);approval_tab()
            assert script('return document.querySelector("#approval-choice").selectedOptions[0].textContent') == 'passkey-user'
            approve(os.environ['TEST_PASSWORD']);assertion=result()
            ceremony={'origin':server,'rpId':'localhost','challenge':challenge,'userHandle':handle,'assertionChallenge':assertion_challenge,
                'registration':registration,'assertion':assertion}
            verified=subprocess.run(['node',str(Path(__file__).with_name('verify_passkeys.mjs'))],input=json.dumps(ceremony),text=True,capture_output=True,timeout=15)
            assert verified.returncode == 0,verified.stderr
            # A page cannot ask for another RP's key, and cancellation returns no signed response.
            begin_passkey('get',{**get_options,'rpId':'foreign.example'})
            wait('return !!window.passkeyError','Invalid RP was not rejected')
            assert script('return window.passkeyError.name') == 'SecurityError'
            begin_passkey('get',get_options);approval_tab();click('#approval-cancel')
            command('POST','/window',{'handle':fixture_handle})
            wait('return !!window.passkeyError','Cancelled request did not reject')
            assert script('return window.passkeyError.name') == 'NotAllowedError'
            begin_passkey('get',get_options);approval_tab()
            command('POST','/window',{'handle':fixture_handle});script('window.passkeyAbort.abort();')
            wait('return !!window.passkeyError','AbortSignal did not reject the request')
            assert script('return window.passkeyError.name') == 'AbortError'
            if not firefox:
                # Exercise the real native API fallback using ChromeDriver's CTAP2 test authenticator.
                authenticator=command('POST','/webauthn/authenticator',{'protocol':'ctap2','transport':'internal',
                    'hasResidentKey':True,'hasUserVerification':True,'isUserVerified':True,'automaticPresenceSimulation':True})
                try:
                    begin_passkey('create',options);approval_tab();click('#approval-device')
                    device_registration=result()
                    begin_passkey('get',{**get_options,'allowCredentials':[{'id':device_registration['id'],'type':'public-key'}]})
                    approval_tab();click('#approval-device');device_assertion=result()
                    native_ceremony={**ceremony,'registration':device_registration,'assertion':device_assertion,'backedUp':False,'aaguid':'01020304050607080102030405060708',
                        'registrationCounter':int.from_bytes(base64.urlsafe_b64decode(device_registration['response']['authenticatorData']+'==')[33:37],'big'),
                        'assertionCounter':int.from_bytes(base64.urlsafe_b64decode(device_assertion['response']['authenticatorData']+'==')[33:37],'big')}
                    verified=subprocess.run(['node',str(Path(__file__).with_name('verify_passkeys.mjs'))],input=json.dumps(native_ceremony),text=True,capture_output=True,timeout=15)
                    assert verified.returncode==0,verified.stderr
                finally:command('DELETE','/webauthn/authenticator/'+authenticator)

            command('POST','/window',{'handle':extension_handle})
            stored = command('POST','/execute/async',{'script':'const done=arguments[arguments.length-1];(globalThis.browser||chrome).storage.local.get(null).then(x=>done(Object.keys(x)));','args':[]})
            assert set(stored) == {'deviceId','server','email'}, 'Unexpected persisted extension data'
            click('#lock')
            wait('return !document.querySelector("#signin").hidden','Lock control failed')
            assert script('return document.querySelector("#detail-password").value==="" && document.querySelector("#password").value===""')
            print(json.dumps({'passed':True,'browser':session['capabilities']['browserVersion'],'passkeys':ceremony}))
        except Exception:
            if sid and args.screenshot:
                try:
                    if args.android_package:
                        capture=subprocess.run([str(args.adb.resolve()),'-P',str(args.adb_port),'-s',args.android_serial,'exec-out','screencap','-p'],capture_output=True,check=True)
                        args.screenshot.with_suffix('.failure.png').write_bytes(capture.stdout)
                    else:args.screenshot.with_suffix('.failure.png').write_bytes(base64.b64decode(command('GET','/screenshot')))
                except Exception:pass
                try:print('UI geometry: '+json.dumps(script('const b=document.querySelector("#fill");return {height:innerHeight,visual:visualViewport?.height,scroll:scrollY,client:document.documentElement.clientHeight,total:document.documentElement.scrollHeight,rect:b?.getBoundingClientRect().toJSON()};')),file=sys.stderr)
                except Exception:pass
            raise
        finally:
            if sid:
                try: command('DELETE','')
                except Exception: pass
            if args.android_package:
                subprocess.run([str(args.adb.resolve()),'-P',str(args.adb_port),'-s',args.android_serial,'reverse','--remove','tcp:'+str(urlsplit(server).port or 443)],capture_output=True)
            driver.terminate()
            try: driver.wait(timeout=10)
            except subprocess.TimeoutExpired: driver.kill(); driver.wait()
            log.close()

if __name__ == '__main__': main()
