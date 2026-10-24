#!/usr/bin/env python3
"""Real encrypted round trip against a disposable Vaultwarden process and two CLI profiles.
Requires node, openssl, a Vaultwarden binary + web vault, and the official bw CLI.
Never uses a real account or changes global Bitwarden configuration.
"""
import argparse
import base64
import contextlib
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lockbox


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--vaultwarden', type=Path, required=True)
    p.add_argument('--web-vault', type=Path, required=True)
    p.add_argument('--bw', type=Path, required=True)
    p.add_argument('--library-path', type=Path)
    p.add_argument('--geckodriver', type=Path)
    p.add_argument('--android-package')
    p.add_argument('--android-native',action='store_true',help='Run the official Android application against native fixture fields.')
    p.add_argument('--android-native-driver',type=Path,help='Use geckodriver for Android system passkey provider acceptance.')
    p.add_argument('--android-serial',default='emulator-5580')
    p.add_argument('--adb',type=Path)
    p.add_argument('--adb-port',type=int,default=5037)
    p.add_argument('--browser-screenshot', type=Path)
    p.add_argument('--browser-only', action='store_true')
    p.add_argument('--chromedriver',type=Path)
    p.add_argument('--chrome',type=Path)
    p.add_argument('--caddy',type=Path)
    p.add_argument('--desktop-linux',action='store_true')
    p.add_argument('--desktop-linux-container',action='store_true',help='Run the frozen Linux GUI inside the owned Ubuntu LTS build container.')
    p.add_argument('--desktop-windows',type=Path,help='Private session.json for the owned Windows VM interactive acceptance.')
    p.add_argument('--windows-packaged',action='store_true',help='Drive the built Windows executable rather than the source UI.')
    p.add_argument('--desktop-macos',type=Path,help='Private, explicitly marked root for attended Mac UI acceptance on this Mac.')
    p.add_argument('--macos-fixture',type=Path,help='Packaged LockboxFixture.app for --desktop-macos.')
    p.add_argument('--macos-packaged-app',type=Path,help='Test the frozen Lockbox.app using a successful source layout from --desktop-macos.')
    p.add_argument('--desktop-runtime',type=Path,help='Test the packaged Node bridge/runtime with the native UI.')
    p.add_argument('--packaged-app',type=Path,help='Drive the actual frozen desktop application against native fields.')
    p.add_argument('--kdf', choices=['pbkdf2','argon2'], default='pbkdf2')
    args = p.parse_args()
    if args.desktop_macos or args.macos_fixture or args.macos_packaged_app:
        if not (args.desktop_macos and args.macos_fixture):p.error('--desktop-macos and --macos-fixture are required together')
        if sys.platform != 'darwin':p.error('--desktop-macos requires an actual macOS graphical desktop')
    if args.windows_packaged and not args.desktop_windows:p.error('--windows-packaged requires --desktop-windows')
    if args.desktop_linux_container and args.desktop_linux:p.error('Choose host or container Linux acceptance')
    if args.browser_only and not (args.geckodriver or args.chromedriver): p.error('--browser-only requires --geckodriver or --chromedriver')
    if args.geckodriver and args.chromedriver:p.error('Run one browser per integration invocation')
    if args.chromedriver and not args.chrome:p.error('--chromedriver requires --chrome')
    if args.android_package and (not args.geckodriver or not args.adb):p.error('Android requires --geckodriver and --adb')
    if args.android_native and not args.adb:p.error('--android-native requires --adb')
    if args.android_native_driver and not args.android_native:p.error('--android-native-driver requires --android-native')
    if (args.desktop_runtime or args.packaged_app) and not args.desktop_linux:p.error('Desktop artifact checks require --desktop-linux')
    if args.desktop_runtime and args.packaged_app:p.error('Choose --desktop-runtime or --packaged-app')
    browser_name='Firefox' if args.geckodriver else 'Chrome'
    binary, bw = str(args.vaultwarden.resolve()), str(args.bw.absolute())
    browser_command = [sys.executable, str(Path(__file__).with_name('firefox_client.py'))]
    if args.geckodriver: browser_command.extend(['--geckodriver',str(args.geckodriver.resolve())])
    if args.android_package:browser_command.extend(['--android-package',args.android_package,'--android-serial',args.android_serial,'--adb',str(args.adb.resolve()),'--adb-port',str(args.adb_port)])
    if args.chromedriver: browser_command.extend(['--chromedriver',str(args.chromedriver.resolve()),'--chrome',str(args.chrome.resolve())])
    if args.browser_screenshot: browser_command.extend(['--screenshot',str(args.browser_screenshot.resolve())])
    with tempfile.TemporaryDirectory(prefix='lockbox-integration-') as tmp:
        root = Path(tmp)
        lockbox.init(root / 'state', 'vault.example.com', 'owner@example.com')
        port, tls_port = free_port(), free_port()
        server_url = f'https://localhost:{tls_port}'
        cert, key = root / 'cert.pem', root / 'key.pem'
        ca_cert, ca_key = root / 'ca.pem', root / 'ca-key.pem'
        extensions = root / 'server.ext'
        extensions.write_text('subjectAltName=DNS:localhost,DNS:vault.test\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n')
        commands = [
            ['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(ca_key),'-out',str(ca_cert),'-days','1','-subj','/CN=Lockbox test CA','-addext','basicConstraints=critical,CA:TRUE','-addext','keyUsage=critical,keyCertSign,cRLSign','-addext','subjectKeyIdentifier=hash'],
            ['openssl','req','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(root / 'server.csr'),'-subj','/CN=localhost'],
            ['openssl','x509','-req','-in',str(root / 'server.csr'),'-CA',str(ca_cert),'-CAkey',str(ca_key),'-CAcreateserial','-out',str(cert),'-days','1','-extfile',str(extensions)]
        ]
        for command in commands: subprocess.run(command, check=True, capture_output=True)

        class Proxy(BaseHTTPRequestHandler):
            def do(self):
                if self.path.startswith('/fixture/login'):
                    body = b'<html><body><form onsubmit="window.submitted=true;return false"><input id="user" name="username" autocomplete="username"><input id="pass" name="password" type="password"><input id="otp-field" name="otp" autocomplete="one-time-code"><button>Sign in</button></form></body></html>'
                    self.send_response(200); self.send_header('Content-Type','text/html'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
                n = int(self.headers.get('Content-Length', '0'))
                request = urllib.request.Request(f'http://127.0.0.1:{port}' + self.path,
                    data=self.rfile.read(n) if n else None, method=self.command,
                    headers={k:v for k,v in self.headers.items() if k.lower() not in ('host', 'connection', 'content-length')})
                try: response = urllib.request.urlopen(request, timeout=15)
                except urllib.error.HTTPError as error: response = error
                with response:
                    body = response.read()
                    self.send_response(response.status)
                    for k,v in response.headers.items():
                        if k.lower() not in ('connection', 'transfer-encoding', 'content-length'):
                            self.send_header(k, v)
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers(); self.wfile.write(body)
            do_GET = do_POST = do_PUT = do_DELETE = do_OPTIONS = do
            def log_message(self, *args): pass

        proxy_port=free_port() if args.caddy else tls_port
        proxy = ThreadingHTTPServer(('127.0.0.1', proxy_port), Proxy)
        if not args.caddy:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(cert, key)
            proxy.socket = ctx.wrap_socket(proxy.socket, server_side=True)
        threading.Thread(target=proxy.serve_forever, daemon=True).start()
        password = secrets.token_urlsafe(32)
        base_env = {**os.environ, 'NODE_EXTRA_CA_CERTS': str(ca_cert), 'TEST_EMAIL': 'owner@example.com',
                    'TEST_PASSWORD': password, 'TEST_SERVER': server_url, 'TEST_KDF':args.kdf}
        env = {**base_env, 'DATA_FOLDER': str(root / 'state/data'), 'DOMAIN': server_url,
               'WEB_VAULT_FOLDER': str(args.web_vault.resolve()), 'ROCKET_PORT': str(port),
               'ROCKET_ADDRESS': '127.0.0.1', 'SIGNUPS_ALLOWED': 'true', 'INVITATIONS_ALLOWED': 'false',
               'ORG_CREATION_USERS': 'none', 'SENDS_ALLOWED': 'false', 'LOG_LEVEL': 'error'}
        if args.library_path: env['LD_LIBRARY_PATH'] = str(args.library_path.resolve())
        process = None
        caddy_process = None
        caddy_log = (root/'caddy.log').open('w+')
        log = (root / 'server.log').open('w+')

        def start(signups):
            nonlocal process
            env['SIGNUPS_ALLOWED'] = str(signups).lower()
            process = subprocess.Popen([binary], env=env, stdout=log, stderr=log, cwd=root)
            for _ in range(150):
                if process.poll() is not None:
                    log.seek(0); raise RuntimeError('Server stopped: ' + log.read())
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}/alive', timeout=.2): return
                except (OSError, urllib.error.URLError): time.sleep(.1)
            raise RuntimeError('Server startup timed out')

        def stop():
            if process and process.poll() is None:
                process.terminate()
                try: process.wait(timeout=15)
                except subprocess.TimeoutExpired: process.kill(); process.wait()

        def cli(profile, *command, session=None, stdin=None):
            cli_env = {**base_env, 'BITWARDENCLI_APPDATA_DIR': str(root / profile)}
            if session: cli_env['BW_SESSION'] = session
            result = subprocess.run([bw, *command], env=cli_env, input=stdin, text=True, capture_output=True, timeout=90)
            if result.returncode:
                # Do not print stdout, which may contain decrypted test data/session keys.
                raise RuntimeError('CLI command failed: ' + command[0] + ': ' + result.stderr)
            return result.stdout.strip()

        try:
            if args.caddy:
                # Preserve production headers, admin denial and proxy configuration; fixture TLS/listen address differ.
                sites=server_url+(', https://vault.test:'+str(tls_port) if args.android_native_driver else '')
                config=(root/'state/Caddyfile').read_text().replace('vault.example.com {',sites+' {\n    tls '+str(cert)+' '+str(key))
                config=config.replace('reverse_proxy vault:8080','reverse_proxy /fixture/* 127.0.0.1:'+str(proxy_port)+'\n    reverse_proxy 127.0.0.1:'+str(port))
                caddyfile=root/'Caddyfile';caddyfile.write_text('{\n    admin off\n    auto_https disable_redirects\n}\n'+config)
                caddy_process=subprocess.Popen([str(args.caddy.resolve()),'run','--config',str(caddyfile),'--adapter','caddyfile'],
                    env={**os.environ,'XDG_DATA_HOME':str(root/'caddy-data'),'XDG_CONFIG_HOME':str(root/'caddy-config')},stdout=caddy_log,stderr=caddy_log)
            start(True)
            if args.caddy:
                for _ in range(100):
                    if caddy_process.poll() is not None:
                        caddy_log.seek(0);raise RuntimeError('Caddy stopped: '+caddy_log.read())
                    try:
                        with urllib.request.urlopen(server_url+'/alive',context=ssl.create_default_context(cafile=str(ca_cert)),timeout=.2):break
                    except (OSError,urllib.error.URLError):time.sleep(.1)
                else:raise RuntimeError('Caddy HTTPS startup timed out.')
            result = subprocess.run(['node', str(Path(__file__).with_name('register_fixture.cjs'))],
                                    env=base_env, capture_output=True, text=True, timeout=30)
            if result.returncode: raise RuntimeError('Fixture registration failed: ' + result.stderr)
            lockbox.check_owner(root / 'state')
            stop(); start(False)
            request = urllib.request.Request(server_url + '/identity/accounts/register/send-verification-email',
                data=json.dumps({'email':'intruder@example.com'}).encode(), headers={'Content-Type':'application/json'})
            try:
                urllib.request.urlopen(request, context=ssl.create_default_context(cafile=str(ca_cert)))
                raise AssertionError('Production accepted a new registration')
            except urllib.error.HTTPError as error:
                assert error.code == 400, error.code
            print('PASS owner enrollment and registration rejection', flush=True)
            if args.caddy:
                context=ssl.create_default_context(cafile=str(ca_cert))
                with urllib.request.urlopen(server_url+'/alive',context=context,timeout=10) as response:
                    assert response.headers.get('Strict-Transport-Security')=='max-age=31536000'
                try:urllib.request.urlopen(server_url+'/admin',context=context,timeout=10);raise AssertionError('Caddy exposed admin route')
                except urllib.error.HTTPError as error:assert error.code==404
                print('PASS actual Caddy trusted HTTPS, health proxy, HSTS and admin denial',flush=True)
            if args.browser_only:
                marker = 'fixture-' + secrets.token_urlsafe(20)
                test_env = {**base_env, 'TEST_ITEM_PASSWORD':marker, 'TEST_CERT':str(ca_cert)}
                seed = subprocess.run(['node',str(Path(__file__).with_name('browser_seed.mjs'))],env=test_env,capture_output=True,text=True,timeout=30)
                if seed.returncode: raise RuntimeError('Browser fixture failed: '+seed.stderr)
                browser = subprocess.run(browser_command,env=test_env,capture_output=True,text=True,timeout=150)
                if browser.returncode: raise RuntimeError(browser_name+' acceptance failed: '+browser.stderr)
                report=json.loads(browser.stdout)
                print('PASS '+browser_name+' '+report['browser']+' UI: passwords, TOTP, fill, passkey creation/assertion, consent, RP rejection and lock',flush=True)
                return
            sessions = []
            for profile in ('client-a', 'client-b'):
                cli(profile, 'config', 'server', server_url)
                sessions.append(cli(profile, 'login', 'owner@example.com', '--passwordenv', 'TEST_PASSWORD', '--raw'))
            marker = 'secret-' + secrets.token_urlsafe(20)
            seed = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'
            item = {'type':1, 'name':'Integration fixture', 'login': {'username':'test-user', 'password':marker,
                'totp':seed, 'uris':[{'uri':'https://example.com', 'match':0}]}, 'notes':'disposable fixture'}
            if args.android_native:item['login']['uris'].append({'uri':'androidapp://org.lockbox.fixture','match':0})
            encoded = base64.b64encode(json.dumps(item).encode()).decode()
            created = json.loads(cli('client-a', 'create', 'item', session=sessions[0], stdin=encoded))
            ident = created['id']
            cli('client-b', 'sync', session=sessions[1])
            fetched = json.loads(cli('client-b', 'get', 'item', ident, session=sessions[1]))
            assert fetched['login']['password'] == marker
            assert fetched['login']['totp'] == seed
            def totp(counter):
                digest = hmac.new(base64.b32decode(seed), struct.pack('>Q', counter), hashlib.sha1).digest()
                offset = digest[-1] & 15
                return f'{(struct.unpack(">I", digest[offset:offset+4])[0] & 0x7fffffff) % 1000000:06}'
            before = int(time.time()) // 30
            code = cli('client-b', 'get', 'totp', ident, session=sessions[1])
            assert code in {totp(before), totp(int(time.time()) // 30)}
            print('PASS encrypted password sync and RFC 6238 six-digit TOTP across two CLI profiles', flush=True)
            extension = subprocess.run(['node', str(Path(__file__).with_name('extension_client.mjs'))],
                env={**base_env, 'TEST_ITEM_PASSWORD':marker}, capture_output=True, text=True, timeout=90)
            if extension.returncode: raise RuntimeError('Extension interoperability failed: ' + extension.stderr)
            extension_id = json.loads(extension.stdout)['id']
            cli('client-b', 'sync', session=sessions[1])
            assert cli('client-b', 'get', 'password', extension_id, session=sessions[1]) == marker
            print('PASS Lockbox extension decrypts official-client cipher and official client decrypts extension cipher', flush=True)
            browser_id = None
            passkey_id = None
            passkey_fixtures = []
            if args.geckodriver or args.chromedriver:
                browser = subprocess.run(browser_command,
                    env={**base_env, 'TEST_ITEM_PASSWORD':marker, 'TEST_CERT':str(ca_cert)}, capture_output=True, text=True, timeout=150)
                if browser.returncode: raise RuntimeError(browser_name+' acceptance failed: ' + browser.stderr)
                report = json.loads(browser.stdout)
                cli('client-b', 'sync', session=sessions[1])
                browser_item = next(i for i in json.loads(cli('client-b', 'list', 'items', session=sessions[1])) if i['name']=='Browser UI fixture')
                assert browser_item['login']['password'] == marker
                assert browser_item['login']['username'] == 'edited-browser-user'
                browser_id = browser_item['id']
                passkey = subprocess.run(['node',str(Path(__file__).with_name('passkey_client.mjs'))],
                    env=base_env,input=json.dumps(report['passkeys']),text=True,capture_output=True,timeout=30)
                if passkey.returncode: raise RuntimeError('Passkey sync failed: '+passkey.stderr)
                passkey_id = json.loads(passkey.stdout)['id']
                cli_passkey = json.loads(cli('client-b','get','item',passkey_id,session=sessions[1]))['login']['fido2Credentials'][0]
                assert cli_passkey['rpId'] == 'localhost'
                assert cli_passkey['credentialId'] == 'b64.'+report['passkeys']['registration']['id']
                assert cli_passkey['userName'] == 'passkey-user'
                assert len(cli_passkey['keyValue']) > 100
                passkey_fixtures.append((passkey_id,report['passkeys'],cli_passkey))
                print('PASS browser WebAuthn registration/assertion, fresh-client passkey sync/signing and official CLI decryption',flush=True)
                print('PASS actual '+browser_name+' ' + report['browser'] + ' extension UI: sign in, save, TOTP, fill, origin rejection, lock, CLI interop', flush=True)
            if args.desktop_linux or args.desktop_linux_container:
                if args.desktop_linux_container:
                    from linux_container import exercise
                    exercise({**base_env,'TEST_ITEM_PASSWORD':marker},ca_cert)
                else:
                    desktop_command=[sys.executable,str(Path(__file__).with_name('native_linux.py')),'--desktop-ui']
                    if args.desktop_runtime:desktop_command.extend(['--desktop-runtime',str(args.desktop_runtime.resolve())])
                    if args.packaged_app:desktop_command.extend(['--packaged-app',str(args.packaged_app.resolve())])
                    desktop=subprocess.run(desktop_command,
                        env={**base_env,'TEST_ITEM_PASSWORD':marker},text=True,capture_output=True,timeout=90)
                    if desktop.returncode:raise RuntimeError('Native desktop UI test failed: '+desktop.stderr)
                    print(desktop.stdout.strip(),flush=True)
                cli('client-b','sync',session=sessions[1])
                linked=json.loads(cli('client-b','get','item',ident,session=sessions[1]))
                app_uris=[u['uri'] for u in linked['login']['uris'] if u['uri'].startswith('lockbox-app://linux/')]
                assert len(app_uris)==1
                assert linked['login']['password']==marker and linked['login']['totp']==seed
                assert linked['login']['uris'][0]['uri']=='https://example.com' and linked['notes']=='disposable fixture'
                print('PASS official CLI decrypts desktop app link and preserved login fields',flush=True)
            if args.desktop_windows:
                from windows_remote import exercise
                exercise(args.desktop_windows, {**base_env, 'TEST_ITEM_PASSWORD': marker}, ca_cert, packaged=args.windows_packaged)
                cli('client-b', 'sync', session=sessions[1])
                linked = json.loads(cli('client-b', 'get', 'item', ident, session=sessions[1]))
                app_uris = [u['uri'] for u in linked['login']['uris'] if u['uri'].startswith('lockbox-app://windows/')]
                assert len(app_uris) == 1
                assert linked['login']['password'] == marker and linked['login']['totp'] == seed
                assert linked['login']['uris'][0]['uri'] == 'https://example.com' and linked['notes'] == 'disposable fixture'
                print('PASS official CLI decrypts Windows app link and preserved login fields', flush=True)
            if args.desktop_macos:
                report = args.desktop_macos.resolve() / ('packaged-ui-report.json' if args.macos_packaged_app else 'source-ui-report.json')
                command = [sys.executable, str(Path(__file__).with_name('native_macos.py')),
                    '--fixture', str(args.macos_fixture.resolve()),
                    '--disposable-root', str(args.desktop_macos.resolve()),
                    '--report', str(report)]
                if args.macos_packaged_app:
                    command.extend(['--packaged-app', str(args.macos_packaged_app.resolve()),
                        '--layout', str(args.desktop_macos.resolve() / 'layout.json')])
                else: command.append('--desktop-ui')
                # Keep the attended dialog instructions visible. A private
                # process group lets a timeout stop this harness and its owned
                # Cocoa fixture/bridge together, without touching other apps.
                desktop = subprocess.Popen(command, env={**base_env, 'TEST_ITEM_PASSWORD': marker},
                    start_new_session=True)
                try:
                    try: result = desktop.wait(timeout=180)
                    except subprocess.TimeoutExpired:
                        with contextlib.suppress(ProcessLookupError):os.killpg(desktop.pid, signal.SIGTERM)
                        try:desktop.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            with contextlib.suppress(ProcessLookupError):os.killpg(desktop.pid, signal.SIGKILL)
                            desktop.wait(timeout=5)
                        raise RuntimeError('Mac UI acceptance timed out; its owned process group was stopped') from None
                    if result:raise RuntimeError('Mac UI acceptance failed; inspect its visible error')
                finally:
                    if desktop.poll() is None:
                        with contextlib.suppress(ProcessLookupError):os.killpg(desktop.pid, signal.SIGTERM)
                        desktop.wait(timeout=5)
                result = json.loads(report.read_text())
                assert result['ok'] and result['desktopUi'] and result['platform'] == 'darwin'
                if args.macos_packaged_app:assert result['packaged']['bundled']
                else:assert result['packaged'] is None
                from desktop.native import app_uri
                expected_macos_uri = app_uri('macos', str((args.macos_fixture / 'Contents/MacOS/LockboxFixture').resolve()))
                cli('client-b', 'sync', session=sessions[1])
                linked = json.loads(cli('client-b', 'get', 'item', ident, session=sessions[1]))
                app_uris = [u['uri'] for u in linked['login']['uris'] if u['uri'].startswith('lockbox-app://macos/')]
                assert app_uris == [expected_macos_uri]
                assert linked['login']['password'] == marker and linked['login']['totp'] == seed
                assert linked['login']['uris'][0]['uri'] == 'https://example.com' and linked['notes'] == 'disposable fixture'
                print('PASS official CLI decrypts exact Mac app link and preserved login fields', flush=True)
            if args.android_native:
                native_command=[sys.executable,str(Path(__file__).with_name('android_native.py')),
                    '--adb',str(args.adb.resolve()),'--serial',args.android_serial,'--adb-port',str(args.adb_port)]
                if args.android_native_driver:native_command.extend(['--geckodriver',str(args.android_native_driver.resolve())])
                native=subprocess.run(native_command,
                    env={**base_env,'TEST_ITEM_PASSWORD':marker,'TEST_CERT':str(ca_cert)},text=True,capture_output=True,timeout=240)
                if native.returncode:
                    log.flush();log.seek(0)
                    artifact=Path(__file__).resolve().parents[1]/'.tools/android-test/server-failure.log'
                    artifact.write_text(log.read());artifact.chmod(0o600)
                    raise RuntimeError('Native Android acceptance failed: '+native.stdout+'\n'+native.stderr)
                for line in native.stdout.splitlines():
                    if line.startswith('PASS '):print(line,flush=True)
                    elif line.startswith('{'):
                        native_report=json.loads(line)['passkeys']
                        synced=subprocess.run(['node',str(Path(__file__).with_name('passkey_client.mjs'))],
                            env=base_env,input=json.dumps(native_report),text=True,capture_output=True,timeout=30)
                        if synced.returncode:raise RuntimeError('Native Android passkey sync failed: '+synced.stderr)
                        native_id=json.loads(synced.stdout)['id']
                        cli('client-b','sync',session=sessions[1])
                        native_key=json.loads(cli('client-b','get','item',native_id,session=sessions[1]))['login']['fido2Credentials'][0]
                        assert native_key['rpId']==native_report['rpId'] and native_key['userName']=='passkey-user'
                        passkey_fixtures.append((native_id,native_report,native_key))
                        print('PASS Android system passkey creation/assertion, independent signatures, fresh-client signing and official CLI decryption',flush=True)
            if args.caddy:
                notification=subprocess.run(['node',str(Path(__file__).with_name('notifications.mjs'))],
                    env={**base_env,'TEST_ITEM_PASSWORD':marker},text=True,capture_output=True,timeout=60)
                if notification.returncode:raise RuntimeError('Caddy WebSocket test failed: '+notification.stderr)
                print(notification.stdout.strip(),flush=True)
            stop()
            for path in (root / 'state/data').rglob('*'):
                if path.is_file():
                    content=path.read_bytes()
                    assert marker.encode() not in content, 'Plaintext password leaked into server storage'
                    for _,_,credential in passkey_fixtures:
                        secret=credential['keyValue']
                        assert secret.encode() not in content, 'Plaintext passkey leaked into server storage'
                        assert base64.urlsafe_b64decode(secret+'==') not in content, 'Private key bytes leaked into server storage'
            archive = lockbox.backup(root / 'state')
            recovery = root / 'recovered'; recovery.mkdir()
            lockbox.restore(recovery, archive)
            env['DATA_FOLDER'] = str(recovery / 'data')
            start(False)
            cli('client-b', 'sync', session=sessions[1])
            assert cli('client-b', 'get', 'password', ident, session=sessions[1]) == marker
            if args.desktop_macos:
                recovered_login = json.loads(cli('client-b', 'get', 'item', ident, session=sessions[1]))
                assert expected_macos_uri in [u['uri'] for u in recovered_login['login']['uris']]
                assert recovered_login['login']['totp'] == seed and recovered_login['notes'] == 'disposable fixture'
                print('PASS existing client decrypts the exact Mac app link after full backup recovery', flush=True)
            for recovered_id,ceremony,credential in passkey_fixtures:
                recovered_passkey = subprocess.run(['node',str(Path(__file__).with_name('passkey_client.mjs'))],
                    env=base_env,input=json.dumps(ceremony),text=True,capture_output=True,timeout=30)
                if recovered_passkey.returncode:raise RuntimeError('Recovered passkey failed: '+recovered_passkey.stderr)
                assert json.loads(recovered_passkey.stdout)['id'] == recovered_id
                print('PASS recovered passkey signs successfully from a newly unlocked client',flush=True)
            cli('client-a', 'sync', session=sessions[0])
            for delete_id in {ident,extension_id,browser_id,*[entry[0] for entry in passkey_fixtures]}-{None}:
                cli('client-a', 'delete', 'item', delete_id, session=sessions[0])
            cli('client-b', 'sync', session=sessions[1])
            assert not json.loads(cli('client-b', 'list', 'items', session=sessions[1]))
            print('PASS full backup recovery, existing client access, and deletion sync', flush=True)
        finally:
            stop(); log.close(); proxy.shutdown(); proxy.server_close()
            if caddy_process:
                caddy_process.terminate()
                try:caddy_process.wait(timeout=10)
                except subprocess.TimeoutExpired:caddy_process.kill();caddy_process.wait()
            caddy_log.close()

if __name__ == '__main__': main()
