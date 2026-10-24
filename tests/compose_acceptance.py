#!/usr/bin/env python3
"""Accept the actual stack in the project's disposable Linux VM, including recovery.

Requires the isolated VM setup in docs/container-testing.md and an enrolled fixture.
Never points at the user's vault or a system Docker daemon.
"""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import shlex
import ssl
import struct
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
ARTIFACT=ROOT/'.tools/compose-acceptance'
VM=ROOT/'.tools/linux-vm'
STATE='/srv/credlet-test/state'
MANAGER='/srv/credlet-test/credlet.py'


def main():
    ssh=['ssh','-p','22993','-i',str(VM/'id_ed25519'),'-o','IdentitiesOnly=yes',
        '-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+str(VM/'known_hosts'),'root@127.0.0.1']

    def remote(command,input=None,check=True):
        result=subprocess.run(ssh+[command],input=input,capture_output=True,text=True,timeout=180)
        if check and result.returncode:raise RuntimeError('VM command failed: '+result.stderr)
        return result

    if remote('cat /srv/credlet-test/.disposable').stdout.strip()!='credlet-disposable-linux-vm' or remote('cat /sys/class/dmi/id/sys_vendor').stdout.strip()!='QEMU':
        raise RuntimeError('The isolated Linux VM identity check failed.')
    fixture=json.loads((ARTIFACT/'fixture.json').read_text())
    assert fixture['server']=='https://vault.localhost:18443' and fixture['email']=='owner@example.com'
    report=[]
    def passed(message):report.append(message);print('PASS '+message,flush=True)
    login_start=time.monotonic()
    login_count=0
    def login_budget(count=1):
        # Match production's five-token burst and one-token/minute refill.
        # Pace disposable clients rather than weakening the deployed policy.
        nonlocal login_count
        target=login_start+max(0,login_count+count-5)*60+2
        if time.monotonic()<target:
            print('Waiting for the production sign-in rate-limit budget',flush=True)
        while time.monotonic()<target:time.sleep(min(10,target-time.monotonic()))
        login_count+=count
    def manager(state,command):return remote(' '.join(map(shlex.quote,['python3',MANAGER,'--state',state,*command]))).stdout.strip()
    def trust(state):
        certificate=remote('cat '+state+'/caddy-data/caddy/pki/authorities/local/root.crt').stdout
        (ARTIFACT/'root-ca.crt').write_text(certificate);(ARTIFACT/'root-ca.crt').chmod(0o600)
        return ssl.create_default_context(cafile=str(ARTIFACT/'root-ca.crt'))
    context=trust(STATE)
    env={**os.environ,'TEST_SERVER':fixture['server'],'TEST_EMAIL':fixture['email'],
        'TEST_PASSWORD':fixture['password'],'TEST_ITEM_PASSWORD':fixture['itemPassword'],
        'NODE_EXTRA_CA_CERTS':str(ARTIFACT/'root-ca.crt')}
    def node(file,input=None):
        result=subprocess.run(['node',str(ROOT/'tests'/file)],input=None if input is None else json.dumps(input),
            env=env,text=True,capture_output=True,timeout=60)
        if result.returncode:raise RuntimeError('Client acceptance failed: '+result.stderr)
        return result.stdout
    def http(path,body=None):
        request=urllib.request.Request(fixture['server']+path,
            data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
        try:return urllib.request.urlopen(request,context=context,timeout=15)
        except urllib.error.HTTPError as error:return error
    for path in ('/alive','/api/config'):
        with http(path) as response:
            assert response.status==200 and response.headers['Strict-Transport-Security']=='max-age=31536000'
    with http('/admin') as response:assert response.status==404
    with http('/identity/accounts/register/send-verification-email',{'email':'another@example.com'}) as response:
        assert response.status in (400,403)
    containers=json.loads(remote('docker inspect credlet-https-1 credlet-vault-1').stdout)
    vault=next(c for c in containers if c['Name']=='/credlet-vault-1')
    assert not vault['HostConfig']['PortBindings'] and 'SIGNUPS_ALLOWED=false' in vault['Config']['Env']
    assert vault['HostConfig']['CapDrop']==['ALL'] and vault['HostConfig']['SecurityOpt']==['no-new-privileges:true']
    manager_check=remote('env SSL_CERT_FILE='+STATE+'/caddy-data/caddy/pki/authorities/local/root.crt python3 '+MANAGER+' --state '+STATE+' check')
    assert manager_check.returncode==0
    passed('actual Compose HTTPS/HSTS/admin denial, registration rejection, owner check and unpublished restricted backend')

    recovery='/srv/credlet-test/recovered-'+str(time.time_ns())
    try:
        with tempfile.TemporaryDirectory(prefix='credlet-compose-cli-') as temporary:
            def cli(profile,*args,session=None,stdin=None):
                result=subprocess.run([str(ROOT/'.tools/node_modules/.bin/bw'),*args],input=stdin,text=True,
                    capture_output=True,timeout=90,env={**env,'BITWARDENCLI_APPDATA_DIR':str(Path(temporary)/profile),
                        **({'BW_SESSION':session} if session else {})})
                if result.returncode:raise RuntimeError('Official CLI failed: '+result.stderr)
                return result.stdout.strip()
            sessions=[]
            for profile in ('a','b'):
                cli(profile,'config','server',fixture['server'])
                login_budget()
                sessions.append(cli(profile,'login',fixture['email'],'--passwordenv','TEST_PASSWORD','--raw'))
            # Anchor refill deadlines after the CLI has actually sent its first
            # requests. CLI startup/KDF time must not count as server refill time.
            login_start=time.monotonic()
            # Only this guarded, disposable fixture vault may be reset. A prior
            # interrupted acceptance run can leave its three named test records.
            existing=json.loads(cli('a','list','items',session=sessions[0]))
            fixture_names={'Integration fixture','Credlet extension fixture','Container fixture — passkey-user'}
            assert all(item['name'] in fixture_names for item in existing),'Unexpected item in disposable test vault'
            for stale in existing:cli('a','delete','item',stale['id'],session=sessions[0])
            seed='GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'
            item={'type':1,'name':'Integration fixture','login':{'username':'test-user','password':fixture['itemPassword'],
                'totp':seed,'uris':[{'uri':'https://example.com','match':0}]}}
            ident=json.loads(cli('a','create','item',session=sessions[0],stdin=base64.b64encode(json.dumps(item).encode()).decode()))['id']
            cli('b','sync',session=sessions[1]);assert cli('b','get','password',ident,session=sessions[1])==fixture['itemPassword']
            before=int(time.time())//30
            code=cli('b','get','totp',ident,session=sessions[1])
            def totp(counter):
                digest=hmac.new(base64.b32decode(seed),struct.pack('>Q',counter),hashlib.sha1).digest();offset=digest[-1]&15
                return f'{(struct.unpack(">I",digest[offset:offset+4])[0]&0x7fffffff)%1000000:06}'
            assert code in {totp(before),totp(int(time.time())//30)}
            login_budget();extension_id=json.loads(node('extension_client.mjs'))['id']
            cli('b','sync',session=sessions[1]);assert cli('b','get','password',extension_id,session=sessions[1])==fixture['itemPassword']
            passed('Argon2id, two official CLI profiles, encrypted password/TOTP sync and extension interoperability through the containers')
            login_budget(2);passkey=json.loads(node('deployed_passkey.mjs'))
            cli('b','sync',session=sessions[1])
            credential=json.loads(cli('b','get','item',passkey['id'],session=sessions[1]))['login']['fido2Credentials'][0]
            assert credential['rpId']=='example.com' and credential['userName']=='passkey-user'
            passed('headless passkey creation, independent registration/assertion verification, fresh-client signing and official CLI FIDO2 decryption through the containers')
            login_budget(2)
            assert 'PASS authenticated WSS' in node('notifications.mjs')
            passed('authenticated WSS cipher notification and second-client sync through the container network and Caddy')
            manager(STATE,['down'])
            scan='import pathlib,sys; marker=sys.stdin.buffer.read(); assert all(marker not in p.read_bytes() for p in pathlib.Path('+repr(STATE+'/data')+').rglob("*") if p.is_file())'
            remote('python3 -c '+shlex.quote(scan),input=fixture['itemPassword'])
            archive=manager(STATE,['backup']).splitlines()[-1]
            assert archive.startswith(STATE+'/backups/credlet-') and archive.endswith('.tar.gz')
            assert remote('stat -c %a '+shlex.quote(archive)).stdout.strip()=='600'
            manager(recovery,['restore',archive]);manager(recovery,['up'])
            context=trust(recovery)
            assert http('/alive').status==200
            cli('b','sync',session=sessions[1]);assert cli('b','get','password',ident,session=sessions[1])==fixture['itemPassword']
            login_budget()
            recovered=json.loads(node('passkey_client.mjs',passkey['ceremony']));assert recovered['id']==passkey['id']
            passed('actual stopped-stack backup/restore, private archive, existing CLI session access and fresh-client recovered passkey signing')
            cli('a','sync',session=sessions[0])
            for item_id in (ident,extension_id,passkey['id']):cli('a','delete','item',item_id,session=sessions[0])
            cli('b','sync',session=sessions[1]);assert not json.loads(cli('b','list','items',session=sessions[1]))
            passed('deletion sync after restoring the complete container deployment')
            manager(recovery,['down'])
            next_archive=manager(recovery,['backup']).splitlines()[-1]
            assert next_archive.startswith(recovery+'/backups/credlet-')
            assert remote('stat -c %a '+shlex.quote(next_archive)).stdout.strip()=='600'
            passed('restored deployment creates its next private backup through the actual CLI')
    finally:
        for state in (recovery,STATE):
            if remote('test -f '+state+'/config.json',check=False).returncode==0:manager(state,['down'])
    output={'passed':report,'server':fixture['server'],'state':STATE,'recovery':recovery,
        'kernel':remote('uname -r').stdout.strip(),'docker':remote('docker --version').stdout.strip(),
        'compose':remote('docker compose version').stdout.strip()}
    (ARTIFACT/'report.json').write_text(json.dumps(output,indent=2)+'\n')


if __name__=='__main__':main()
