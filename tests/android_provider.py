"""Exercise the official Android Credential Manager provider from real Firefox WebAuthn.

No Lockbox extension is installed in this temporary browser profile.
"""
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

# Bitwarden SDK authenticator identifier (the independent verifier checks this
# exact value rather than accepting arbitrary provider registration metadata).
# https://sdk-api-docs.bitwarden.com/src/bitwarden_fido/lib.rs.html
AAGUID='d548826e79b4db40a3d811116f7e8349'


def ceremony(ui,driver_path,server,ca):
    # An interrupted prior WebDriver session can leave AOSP's singleTop selector task alive.
    # Reset that UI only on the already-verified disposable emulator before starting a new request.
    ui.run('shell','am','force-stop','com.android.credentialmanager')
    website=server.replace('//localhost:','//vault.test:')
    with tempfile.TemporaryDirectory(prefix='lockbox-android-provider-') as tmp:
        root=Path(tmp);profile=root/'profile';profile.mkdir()
        for command in (['certutil','-N','--empty-password','-d','sql:'+str(profile)],
                        ['certutil','-A','-n','Lockbox fixture','-t','C,,','-d','sql:'+str(profile),'-i',str(ca)]):
            subprocess.run(command,check=True,capture_output=True)
        archive=io.BytesIO()
        with zipfile.ZipFile(archive,'w') as bundle:
            for file in profile.iterdir():bundle.write(file,file.name)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        with (root/'driver.log').open('w+') as log:
            process=subprocess.Popen([str(driver_path),'--port',str(port),'--allow-system-access','--android-storage','sdcard','--log','error'],
                stdout=log,stderr=log,env={**os.environ,'HOME':str(root)})
            sid=None

            def request(method,path,data=None,timeout=60):
                req=urllib.request.Request(f'http://127.0.0.1:{port}'+path,method=method,
                    data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json'})
                try:
                    with urllib.request.urlopen(req,timeout=timeout) as response:return json.load(response)['value']
                except urllib.error.HTTPError as error:
                    value=json.load(error).get('value',{})
                    raise RuntimeError('WebDriver '+value.get('error','request failed')+': '+value.get('message','')) from None

            def command(method,path,data=None):return request(method,'/session/'+sid+path,data)
            def script(source,*args):return command('POST','/execute/sync',{'script':source,'args':args})
            def begin(kind,options):
                script("""
                    const kind=arguments[0],options=arguments[1];
                    const b=s=>Uint8Array.from(atob(s.replace(/-/g,'+').replace(/_/g,'/')),c=>c.charCodeAt(0));
                    options.challenge=b(options.challenge);if(options.user)options.user.id=b(options.user.id);
                    for(const k of ['allowCredentials','excludeCredentials'])if(options[k])options[k].forEach(c=>c.id=b(c.id));
                    window.passkeyResult=null;window.passkeyError=null;window.passkeyStarted=null;
                    let button=document.querySelector('#start-passkey');
                    if(!button){button=document.createElement('button');button.id='start-passkey';button.type='button';button.textContent='Native provider passkey';document.body.append(button);}
                    button.style.cssText='position:fixed;left:16px;top:32px;width:260px;height:48px;z-index:2147483647';
                    button.onclick=()=>{window.passkeyStarted=kind;navigator.credentials[kind]({publicKey:options}).then(c=>window.passkeyResult=c.toJSON()).catch(e=>window.passkeyError={name:e.name,message:e.message});};
                """,kind,options)
                # Provider activities finish before Firefox's window has fully
                # resumed. Use the visible native page control and confirm its
                # actual event handler ran, rather than trusting a WebDriver tap.
                for _ in range(50):
                    if script('return document.hasFocus()'):break
                    time.sleep(.1)
                else:raise AssertionError('Firefox did not regain focus before the passkey request.')
                ui.click('Native provider passkey')
                for _ in range(20):
                    if script('return window.passkeyStarted')==kind:return
                    time.sleep(.1)
                raise AssertionError('Native Firefox button did not start the WebAuthn request.')

            def result():
                for _ in range(150):
                    data=script('return {result:window.passkeyResult,error:window.passkeyError}')
                    assert data['error'] is None,data['error']
                    if data['result']:return data['result']
                    time.sleep(.1)
                raise AssertionError('Native provider did not return a WebAuthn response.')

            def verify_master():
                ui.wait('Master password confirmation')
                node=None
                for _ in range(20):
                    nodes=ui.nodes()
                    node=next((n for n in nodes if n.get('class')=='android.widget.EditText'
                        and n.get('package')=='com.x8bit.bitwarden'
                        and n.get('resource-id','').rsplit('/',1)[-1]=='AlertInputField'),None)
                    if node is not None:break
                    time.sleep(.1)
                assert node is not None, 'Native master field missing: '+repr([
                    (n.get('class'),n.get('resource-id'),n.get('package')) for n in nodes
                    if n.get('class')=='android.widget.EditText'])
                ui.text(node,os.environ['TEST_PASSWORD'])
                ui.click('Submit')

            try:
                for _ in range(100):
                    try:request('GET','/status');break
                    except OSError:time.sleep(.1)
                session=request('POST','/session',{'capabilities':{'alwaysMatch':{'browserName':'firefox','moz:firefoxOptions':{
                    'androidPackage':'org.mozilla.fenix','androidDeviceSerial':'emulator-5580',
                    'profile':base64.b64encode(archive.getvalue()).decode(),
                    'prefs':{'network.dns.localDomains':'vault.test','browser.shell.checkDefaultBrowser':False,'datareporting.policy.dataSubmissionEnabled':False}}}}})
                sid=session['sessionId']
                ui.firefox_setup('org.mozilla.fenix')
                command('POST','/url',{'url':website+'/fixture/login'})
                assert 'certerror' not in command('GET','/url')
                assert script('return !!document.querySelector("#user")')
                for _ in range(20):
                    # The role chooser can appear after navigation completes on a fresh profile.
                    ui.firefox_setup('org.mozilla.fenix')
                    if script('return document.readyState==="complete" && innerHeight>100 && document.hasFocus()'):break
                    time.sleep(.1)
                else:
                    state=script('return {focus:document.hasFocus(),height:innerHeight,visibility:document.visibilityState}')
                    raise AssertionError('Native Firefox fixture is not focused and visible: '+repr(state))
                challenge=base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip('=')
                handle=base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip('=')
                options={'challenge':challenge,'rp':{'id':'vault.test','name':'Lockbox native provider fixture'},
                    'user':{'id':handle,'name':'passkey-user','displayName':'Native provider test'},
                    'pubKeyCredParams':[{'type':'public-key','alg':-7}],
                    'authenticatorSelection':{'residentKey':'required','userVerification':'required'},
                    'extensions':{'credProps':True},'timeout':120000}
                begin('create',options)
                try:ui.click('Continue')
                except AssertionError as error:
                    state=script('return {error:window.passkeyError,secure:isSecureContext,focus:document.hasFocus(),visibility:document.visibilityState,height:innerHeight}')
                    raise AssertionError(str(error)+'; browser state: '+json.dumps(state)) from None
                ui.click('Save passkey as new login')
                ui.click('Okay')
                ui.click('Save')
                verify_master()
                registration=result()
                # Android Firefox omits credProps; the ID-less assertion below
                # independently proves that this is a discoverable credential.
                creation={'origin':website,'rpId':'vault.test','challenge':challenge,'userHandle':handle,
                    'registration':registration,'aaguid':AAGUID,'credProps':False}
                registration_artifact=Path(__file__).resolve().parents[1]/'.tools/android-test/native-registration-public.json'
                registration_artifact.write_text(json.dumps(creation,indent=2)+'\n');registration_artifact.chmod(0o600)
                registration_check=subprocess.run(['node',str(Path(__file__).with_name('verify_passkeys.mjs')),'--registration-only'],
                    input=json.dumps(creation),text=True,capture_output=True,timeout=15)
                assert registration_check.returncode==0,registration_check.stderr
                print('PASS independent verification of Android system passkey registration',flush=True)
                assertion_challenge=base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip('=')
                begin('get',{'challenge':assertion_challenge,'rpId':'vault.test','userVerification':'required',
                    'timeout':120000})
                try:ui.click('passkey-user')
                except AssertionError as error:
                    state=script('return {started:window.passkeyStarted,error:window.passkeyError,result:!!window.passkeyResult,focus:document.hasFocus()}')
                    raise AssertionError(str(error)+'; assertion state: '+json.dumps(state)) from None
                chooser=next((n for n in ui.nodes() if n.get('package')=='com.android.credentialmanager' and n.get('text','').casefold()=='continue'),None)
                if chooser is not None:ui.tap(chooser)
                verify_master()
                assertion=result()
                report={'origin':website,'rpId':'vault.test','challenge':challenge,'userHandle':handle,
                    'assertionChallenge':assertion_challenge,'registration':registration,'assertion':assertion,
                    'aaguid':AAGUID,'credProps':False}
                artifact=Path(__file__).resolve().parents[1]/'.tools/android-test/native-provider-public.json'
                artifact.write_text(json.dumps(report,indent=2)+'\n');artifact.chmod(0o600)
                verify=subprocess.run(['node',str(Path(__file__).with_name('verify_passkeys.mjs'))],
                    input=json.dumps(report),text=True,capture_output=True,timeout=15)
                assert verify.returncode==0,verify.stderr
                return report
            finally:
                if sid:
                    try:request('DELETE','/session/'+sid,timeout=5)
                    except Exception:pass
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait()
