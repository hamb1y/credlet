#!/usr/bin/env python3
"""Official Android app acceptance on our disposable AOSP emulator, with real TLS and UI."""
import argparse
import base64
import contextlib
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import struct
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

from android_ui import AndroidUi

ROOT=Path(__file__).resolve().parents[1]
PACKAGE='com.x8bit.bitwarden'
FIXTURE='org.credlet.fixture'


class NativeUi(AndroidUi):
    def nodes(self):
        data=self.run('exec-out','env','CLASSPATH=/data/local/tmp/credlet-ui.apk',
            'app_process','/system/bin','org.credlet.fixture.UiDump')
        return [n for n in ET.fromstring(data).iter('node') if n.get('visible')=='true']

    def wait_value(self,package,description,value):
        end=time.monotonic()+20
        while time.monotonic()<end:
            if any(n.get('package')==package and n.get('class')=='android.widget.EditText'
                and n.get('content-desc')==description and n.get('text')==value for n in self.nodes()):return
            time.sleep(.1)
        diagnostic=ROOT/'.tools/android-test/fill-failure.png'
        diagnostic.write_bytes(self.run('exec-out','screencap','-p'));diagnostic.chmod(0o600)
        nodes=self.nodes()
        labels=[(n.get('text') or n.get('content-desc'),n.get('package'),n.get('bounds')) for n in nodes
            if n.get('class')!='android.widget.EditText' and n.get('password')!='true' and (n.get('text') or n.get('content-desc'))]
        raise AssertionError('Native autofill did not update the expected field; visible labels: '+repr(labels))

    def wait(self,label,timeout=20):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            nodes=self.nodes()
            target=next((n for n in nodes if n.get('text','').casefold()==label.casefold() or n.get('content-desc','').casefold()==label.casefold()),None)
            if target is not None:return target
            time.sleep(.2)
        # Never include editable text or password values in a failure report.
        labels=[n.get('text') or n.get('content-desc') for n in nodes if n.get('class') not in ('android.widget.EditText',) and n.get('password')!='true' and (n.get('text') or n.get('content-desc'))]
        raise AssertionError('Missing UI control '+label+'; visible labels: '+repr(labels))

    def click(self,label):
        node=self.wait(label)
        # Embedded keyboard suggestions can expose stale screen bounds during IME layout.
        # Invoke the actual node's accessibility click instead of tapping those coordinates.
        if label=='Integration fixture':
            print('Native fixture selection: '+repr({key:node.get(key) for key in ('package','class','bounds')}),flush=True)
            data=self.run('exec-out','env','CLASSPATH=/data/local/tmp/credlet-ui.apk',
                'app_process','/system/bin','org.credlet.fixture.UiDump','--click',shlex.quote(label))
            if ET.fromstring(data).get('success')=='true':return
            node=self.wait(label)
        self.tap(node)

    def text(self,node,value):
        self.tap(node)
        try:self.run('shell','input','text',shlex.quote(value))
        except subprocess.CalledProcessError:raise RuntimeError('Could not type fixture text.') from None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb',type=Path,required=True)
    parser.add_argument('--serial',default='emulator-5580')
    parser.add_argument('--adb-port',type=int,default=5038)
    parser.add_argument('--geckodriver',type=Path,help='Also exercise Android system passkeys from Firefox, without an extension.')
    args=parser.parse_args()
    ui=NativeUi(args.adb,args.serial,args.adb_port)
    # Destructive test setup is confined to the project's explicitly named disposable emulator.
    if args.serial!='emulator-5580' or ui.run('shell','getprop','ro.kernel.qemu').strip()!=b'1':
        raise RuntimeError('This destructive test only runs on the named disposable emulator.')
    if ui.run('shell','id','-u').strip()!=b'0':
        raise RuntimeError('Run adb root on the disposable AOSP image first.')
    server=os.environ['TEST_SERVER'];port=str(urlsplit(server).port)
    ca=Path(os.environ['TEST_CERT'])
    ca_hash=subprocess.check_output(['openssl','x509','-in',str(ca),'-subject_hash_old','-noout'],text=True).strip()
    assert re.fullmatch('[0-9a-f]{8}',ca_hash)
    for suffix in range(100):
        remote='/data/misc/user/0/cacerts-added/'+ca_hash+'.'+str(suffix)
        exists=subprocess.run(ui.command+['shell','test','-e',remote],capture_output=True,timeout=15)
        if exists.returncode==1:break
        if exists.returncode:raise RuntimeError('Could not inspect the disposable CA store.')
    else:raise RuntimeError('No unused fixture CA slot.')
    try:
        ui.run('shell','mkdir','-p','/data/misc/user/0/cacerts-added')
        ui.run('push',str(ca),remote)
        ui.run('shell','chmod','644',remote)
        ui.run('shell','chown','system:system',remote)
        ui.run('shell','restorecon','-R','/data/misc/user/0/cacerts-added')
        ui.run('shell','am','broadcast','-a','android.security.action.TRUST_STORE_CHANGED')
        ui.run('reverse','tcp:'+port,'tcp:'+port)
        ui.run('install','-r',str(ROOT/'.tools/android-test/fixture/credlet-fixture.apk'))
        ui.run('push',str(ROOT/'.tools/android-test/fixture/credlet-fixture.apk'),'/data/local/tmp/credlet-ui.apk')
        # Failed WebAuthn sessions can leave Android's singleTop selector above later app tasks.
        ui.run('shell','am','force-stop','com.android.credentialmanager')
        ui.run('shell','pm','clear',PACKAGE)
        ui.run('shell','pm','clear',FIXTURE)
        ui.run('shell','am','start','-n',PACKAGE+'/.MainActivity')
        ui.click('Log in');ui.click('Region');ui.click('Self-hosted')
        ui.wait('Server URL')
        ui.text(next(n for n in ui.nodes() if n.get('class')=='android.widget.EditText'),server)
        ui.run('shell','input','keyevent','4')
        ui.click('Save')
        ui.wait('Email address')
        ui.text(next(n for n in ui.nodes() if n.get('class')=='android.widget.EditText'),os.environ['TEST_EMAIL'])
        ui.run('shell','input','keyevent','4');ui.click('Continue')
        ui.wait('Master password')
        ui.text(next(n for n in ui.nodes() if n.get('class')=='android.widget.EditText'),os.environ['TEST_PASSWORD'])
        ui.run('shell','input','keyevent','4');ui.click('Log in with master password')
        ui.wait('My vault',timeout=40)
        ui.click('Login')
        ui.wait('Integration fixture')
        print('PASS Android native self-hosted HTTPS login and encrypted vault sync',flush=True)
        ui.click('Integration fixture')
        before=int(time.time())//30
        codes=[]
        for _ in range(5):
            codes=[re.sub(r'\s','',n.get('text','')) for n in ui.nodes() if re.fullmatch(r'\d{3}\s?\d{3}',n.get('text',''))]
            if codes:break
        def totp(counter):
            digest=hmac.new(base64.b32decode('GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'),struct.pack('>Q',counter),hashlib.sha1).digest()
            offset=digest[-1]&15
            return f'{(struct.unpack(">I",digest[offset:offset+4])[0]&0x7fffffff)%1000000:06}'
        assert set(codes)&{totp(before),totp(int(time.time())//30)}, 'Native app did not display the independently verified six-digit code.'
        print('PASS Android native six-digit TOTP matches independent RFC 6238 calculation',flush=True)
        ui.run('shell','settings','put','secure','autofill_service',PACKAGE+'/com.x8bit.bitwarden.Autofill.AutofillService')
        ui.run('shell','am','start','-n',FIXTURE+'/.MainActivity')
        # Let the actual IME attach before the explicit autofill request. Gboard
        # can otherwise receive the inline response before its suggestion host
        # exists and silently discard it.
        ui.tap(ui.wait('Fixture username'))
        for _ in range(40):
            if any(n.get('package') in ('com.google.android.inputmethod.latin','com.android.inputmethod.latin') for n in ui.nodes()):break
            time.sleep(.1)
        else:raise AssertionError('Native fixture keyboard did not become visible.')
        fill_before=int(time.time())//30
        ui.click('Request autofill')
        ui.click('Integration fixture')
        ui.wait_value(FIXTURE,'Fixture username','test-user')
        # Paste promptly, before inspection round trips can outlast the client's clipboard timeout.
        ui.click('Paste code')
        ui.click('Inspect fields')
        ui.wait('Fixture fields inspected')
        fields=json.loads(ui.run('shell','run-as',FIXTURE,'cat','files/fields.json'))
        assert fields['username']=='test-user'
        assert fields['password']==os.environ['TEST_ITEM_PASSWORD']
        print('PASS Android native app username/password autofill into real EditText fields',flush=True)
        assert fields['code'] in {totp(c) for c in range(fill_before,int(time.time())//30+1)}, 'Native TOTP copy/paste did not produce a code from the autofill interval (length '+str(len(fields['code']))+').'
        print('PASS Android native autofill copies TOTP and explicit paste fills the native code field',flush=True)
        if args.geckodriver:
            component=PACKAGE+'/com.x8bit.bitwarden.Autofill.CredentialProviderService'
            ui.run('shell','settings','put','secure','credential_service',component)
            ui.run('shell','settings','put','secure','credential_service_primary',component)
            from android_provider import ceremony
            report=ceremony(ui,args.geckodriver.resolve(),server,ca)
            print(json.dumps({'passkeys':report}),flush=True)
    finally:
        with contextlib.suppress(Exception):ui.run('shell','am','force-stop','com.android.credentialmanager')
        with contextlib.suppress(Exception):ui.run('shell','am','force-stop',PACKAGE)
        with contextlib.suppress(Exception):ui.run('shell','rm','-f',remote)
        with contextlib.suppress(Exception):ui.run('shell','am','broadcast','-a','android.security.action.TRUST_STORE_CHANGED')
        with contextlib.suppress(Exception):ui.run('reverse','--remove','tcp:'+port)
        with contextlib.suppress(Exception):ui.run('shell','pm','clear',FIXTURE)


if __name__=='__main__':main()
