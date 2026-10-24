"""Real website acceptance for the shared Svelte extension UI."""
import base64
import json
import os
from pathlib import Path
import subprocess
import time


def exercise_extension(command,script,wait,button,fill,ui_handle,target,origin):
    master='disposable v3 master phrase 8482'
    marker='private browser password 7482'
    website_handle=None
    for handle in command('GET','/window/handles'):
        command('POST','/window',{'handle':handle})
        if command('GET','/url')==origin+'/login':website_handle=handle;break
    assert website_handle,'Website fixture did not open'
    wait('return !!document.querySelector("#user")','Website fixture did not load')
    assert script('return isSecureContext && !!navigator.credentials'),'Website needs a secure context'
    command('POST','/window',{'handle':ui_handle})
    script('document.querySelector(".logins button").click()')
    wait('return !!document.querySelector(".otp")','Detail did not load')
    button('Fill on this website')
    wait('return document.body.innerText.includes("Field filled.")','Website fill failed')
    command('POST','/window',{'handle':website_handle})
    assert script('return document.querySelector("#user").value==="browser-owner" && document.querySelector("#pass").value===arguments[0]',marker)
    assert not script('return !!window.submitted'),'Filling submitted the form'
    code_field=script('const f=document.querySelector("#otp-field");return {type:f.type,autocomplete:f.autocomplete,attribute:f.getAttribute("autocomplete"),rects:f.getClientRects().length,action:f.form.action};')
    command('POST','/window',{'handle':ui_handle})
    button('Fill code')
    wait('return document.body.innerText.includes("Field filled.")','Website code fill failed '+str(code_field))
    command('POST','/window',{'handle':website_handle})
    wait('return /^\\d{6}$/.test(document.querySelector("#otp-field").value)','Code field not filled')
    script('document.querySelector("form").action="https://foreign.example/";document.querySelector("#pass").value="";')
    command('POST','/window',{'handle':ui_handle})
    button('Fill on this website')
    wait('return !!document.querySelector("[role=alert]")','Foreign form submission was not rejected')
    command('POST','/window',{'handle':website_handle})
    assert script('return document.querySelector("#pass").value===""'),'Foreign form received a secret'
    script('document.querySelector("form").action=location.href;const extra=document.createElement("input");extra.id="other-password";extra.type="password";document.querySelector("form").append(extra);document.activeElement.blur();')
    command('POST','/window',{'handle':ui_handle})
    button('Fill on this website')
    wait('return !!document.querySelector("[role=alert]")','Ambiguous password fields were not rejected')
    command('POST','/window',{'handle':website_handle})
    assert script('return document.querySelector("#pass").value==="" && document.querySelector("#other-password").value===""')
    script('document.querySelector("#pass").autocomplete="new-password";document.querySelector("#other-password").autocomplete="current-password";')
    command('POST','/window',{'handle':ui_handle})
    button('Fill on this website')
    wait('return document.body.innerText.includes("Field filled.")','Current-password field not filled')
    command('POST','/window',{'handle':website_handle})
    assert script('return document.querySelector("#pass").value==="" && document.querySelector("#other-password").value===arguments[0]',marker),'New-password field was overwritten'

    baseline=set()
    def begin(kind,options):
        nonlocal baseline
        command('POST','/window',{'handle':ui_handle})
        command('POST','/execute/async',{'script':'const done=arguments[arguments.length-1];(globalThis.browser||chrome).tabs.update(arguments[0],{active:true}).then(()=>done(true));','args':[target]})
        command('POST','/window',{'handle':website_handle})
        script('''
          window.passkeyResult=null;window.passkeyError=null;
          const options=arguments[1],kind=arguments[0];
          const b=s=>Uint8Array.from(atob(s.replace(/-/g,'+').replace(/_/g,'/')),c=>c.charCodeAt(0));
          options.challenge=b(options.challenge);if(options.user)options.user.id=b(options.user.id);
          for(const key of ['allowCredentials','excludeCredentials'])if(options[key])options[key].forEach(c=>c.id=b(c.id));
          let button=document.querySelector('#start-passkey');
          if(!button){button=document.createElement('button');button.type='button';button.id='start-passkey';button.textContent='Passkey';document.body.append(button);}
          button.onclick=()=>navigator.credentials[kind]({publicKey:options,signal:(window.passkeyAbort=new AbortController()).signal}).then(async c=>{
            // Firefox WebDriver runs this callback in a different JS realm.
            // Verify ArrayBuffer brands and actual BufferSource consumption.
            const digest=await crypto.subtle.digest('SHA-256',c.rawId);
            window.passkeyShape={credential:c instanceof PublicKeyCredential,id:Object.prototype.toString.call(c.rawId)==='[object ArrayBuffer]',data:Object.prototype.toString.call(c.response.clientDataJSON)==='[object ArrayBuffer]',digest:digest.byteLength===32};
            window.passkeyResult=c.toJSON();
          }).catch(e=>window.passkeyError={name:e.name,message:e.message});
        ''',kind,options)
        baseline=set(command('GET','/window/handles'))
        element=command('POST','/element',{'using':'css selector','value':'#start-passkey'})
        command('POST','/element/'+element['element-6066-11e4-a52e-4f735466cecf']+'/click',{})
    def approval(locked=False):
        for _ in range(100):
            for handle in command('GET','/window/handles'):
                if handle in baseline:continue
                command('POST','/window',{'handle':handle})
                if '?passkey=' in command('GET','/url'):
                    wait('return document.body.innerText.includes("Cancel passkey request")' if locked else 'return document.body.innerText.includes("PASSKEY REQUEST")','Approval UI failed')
                    return
            time.sleep(.1)
        command('POST','/window',{'handle':website_handle})
        raise AssertionError('No approval tab: '+str(script('return window.passkeyError')))
    def approve(password):
        fill({'Master password':password})
        script('document.querySelector("form").requestSubmit()')
    def result():
        command('POST','/window',{'handle':website_handle})
        wait('return !!(window.passkeyResult || window.passkeyError)','Website did not receive the passkey')
        assert script('return window.passkeyError') is None,script('return window.passkeyError')
        assert all(script('return window.passkeyShape').values()),'Incorrect browser credential object shape'
        return script('return window.passkeyResult')
    challenge=base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip('=')
    user=base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip('=')
    options={'challenge':challenge,'rp':{'id':'localhost','name':'Credlet website fixture'},
        'user':{'id':user,'name':'passkey-user','displayName':'Passkey test'},'pubKeyCredParams':[{'type':'public-key','alg':-7}],
        'authenticatorSelection':{'residentKey':'required','userVerification':'required'},'extensions':{'credProps':True},'timeout':120000}
    begin('create',options);approval()
    assert script('return document.querySelector(".origin").textContent')==origin
    approve('incorrect fixture master')
    wait('return !!document.querySelector("[role=alert]")','Incorrect master was not rejected')
    assert not script('return document.body.innerText.includes("Passkey request completed.")')
    approve(master);registration=result()
    assertion_challenge=base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip('=')
    get_options={'challenge':assertion_challenge,'rpId':'localhost','userVerification':'required',
        'allowCredentials':[{'type':'public-key','id':registration['id']}],'timeout':120000}
    begin('get',get_options);approval()
    assert script('return document.querySelector("select").selectedOptions[0].textContent')=='passkey-user'
    approve(master);assertion=result()
    ceremony={'origin':origin,'rpId':'localhost','challenge':challenge,'userHandle':user,'assertionChallenge':assertion_challenge,
        'registration':registration,'assertion':assertion}
    verified=subprocess.run(['node',str(Path(__file__).with_name('verify_passkeys.mjs'))],input=json.dumps(ceremony),text=True,capture_output=True,timeout=15)
    assert verified.returncode==0,verified.stderr
    begin('get',{**get_options,'rpId':'foreign.example'})
    wait('return !!window.passkeyError','Foreign relying party was not rejected')
    assert script('return window.passkeyError.name')=='SecurityError'
    begin('get',get_options);approval();button('Cancel')
    command('POST','/window',{'handle':website_handle})
    wait('return !!window.passkeyError','Cancel did not reject')
    assert script('return window.passkeyError.name')=='NotAllowedError'
    begin('get',get_options);approval()
    command('POST','/window',{'handle':website_handle});script('window.passkeyAbort.abort()')
    wait('return !!window.passkeyError','AbortSignal did not reject')
    assert script('return window.passkeyError.name')=='AbortError'
    command('POST','/window',{'handle':ui_handle})
    stored=command('POST','/execute/async',{'script':'const done=arguments[arguments.length-1];(globalThis.browser||chrome).storage.local.get(null).then(x=>done(Object.keys(x)));','args':[]})
    assert set(stored)=={'server','serverKey','email'},'Unexpected persistent browser secrets'
    button('Lock')
    wait('return !!document.querySelector("input[autocomplete=current-password]")','Lock failed')
    begin('get',get_options);approval(locked=True);button('Cancel passkey request')
    command('POST','/window',{'handle':website_handle})
    wait('return !!window.passkeyError','Locked request cancel failed')
    assert script('return window.passkeyError.name')=='NotAllowedError'
    print('PASS actual website: password/TOTP fill, foreign/ambiguous/new-password protection, passkey create/sign-in with independent signature verification, RP scoping, consent, cancellation and lock')
