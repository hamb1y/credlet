#!/usr/bin/env python3
"""Actual Cocoa/Accessibility acceptance on an explicitly marked Mac test user.

This requires a logged-in graphical session and macOS-granted Accessibility
permission. It never edits TCC databases or sends input to another application.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import platform
import plistlib
import subprocess
import struct
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop.native import Mac, NativeError


def wait(predicate, message, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value: return value
        time.sleep(.05)
    raise AssertionError(message)


class Fixture:
    def __init__(self, executable, root):
        self.root = root; self.serial = 0; root.mkdir(mode=0o700)
        (root / '.disposable').write_text('lockbox-native-macos-fixture\n')
        self.process = subprocess.Popen([str(executable), str(root)])
        try:
            def ready():
                if self.process.poll() is not None: raise AssertionError('Cocoa fixture stopped before opening')
                return (root / 'ready.json').exists()
            wait(ready, 'Cocoa fixture did not start')
            result = json.loads((root / 'ready.json').read_text())
            assert result == {'pid': self.process.pid, 'bundleId': 'local.lockbox.fixture'}
        except BaseException:
            self.close(); raise

    def command(self, command):
        self.serial += 1
        temporary = self.root / 'request.tmp'
        temporary.write_text(json.dumps({'id': self.serial, 'command': command}))
        temporary.replace(self.root / 'request.json')
        def response():
            path = self.root / 'response.json'
            if not path.exists(): return None
            value = json.loads(path.read_text())
            if value.get('id') != self.serial: return None
            assert value['ok'], value.get('error')
            return value
        return wait(response, 'Cocoa fixture command timed out')['value']

    def close(self):
        if self.process.poll() is None:
            self.process.terminate(); self.process.wait(timeout=5)


def rejected(action, message):
    try: action()
    except NativeError: return
    raise AssertionError(message)


def desktop_ui(fixture, root):
    """Drive source widgets and real AX targets; the native link dialog is attended.

    This exercises App's real buttons and bridge, not a replacement vault client.
    The operator accepts the ordinary native app-link confirmation. No dialog
    response, native field fill or Accessibility result is stubbed.
    """
    import tkinter as tk
    from desktop.app import App
    config = root / 'settings'
    previous = os.environ.get('LOCKBOX_CONFIG_DIR')
    os.environ['LOCKBOX_CONFIG_DIR'] = str(config)
    window = tk.Tk()
    app = None
    try:
        app = App(window)
        def spin(predicate, message, seconds=45):
            def tick():
                window.update()
                return predicate()
            try: return wait(tick, message, seconds)
            except AssertionError as error:
                raise AssertionError(message + ': ' + app.notice.get()) from error
        def button(text):
            return next(b for b in app.buttons if b.cget('text') == text)
        layouts = {'platform': sys.platform, 'architecture': platform.machine(),
            'tcl': window.tk.call('info', 'patchlevel'), 'tk': window.tk.call('package', 'present', 'Tk'),
            'python': sys.version.split()[0],
            'fixtureExecutable': str(Path(fixture.process.args[0]).resolve())}
        def layout(name):
            # Only public widget geometry is exported. Neither entry contents
            # nor vault records/identifiers go into this reusable template.
            import Quartz as Q
            from packaged_macos import windows, bounds
            window.update_idletasks()
            visible = windows(Q, os.getpid(), True)
            assert len(visible) == 1, 'Source layout requires one visible normal window'
            frame = bounds(Q, visible[0])
            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)
            widgets = {'server': app.server, 'email': app.email, 'master': app.master,
                'unlock': button('Unlock vault'), 'lock': button('Lock'),
                'capture': button('Capture app field…'), 'tree': app.items,
                'fill': button('Fill selected field'), 'link': button('Link login to app')}
            for key, kind in [('query', 'TEntry'), ('field', 'TCombobox')]:
                widgets[key] = next(w for w in descendants(app.vault) if w.winfo_class() == kind)
            layouts[name] = {key: [w.winfo_rootx() - window.winfo_rootx(),
                w.winfo_rooty() - window.winfo_rooty(), w.winfo_width(), w.winfo_height()]
                for key, w in widgets.items() if w.winfo_viewable()}
            layouts[name].update(contentOffset=[window.winfo_rootx() - frame[0], window.winfo_rooty() - frame[1]],
                frameSize=frame[2:], clientSize=[window.winfo_width(), window.winfo_height()])
            if app.items.winfo_viewable():
                layouts[name]['row'] = list(app.items.bbox(app.items.get_children()[0]))
        spin(lambda: bool(app.server.winfo_viewable()), 'Mac sign-in form is not visible')
        layout('signin')
        for entry, value in [(app.server, os.environ['TEST_SERVER']),
                (app.email, os.environ['TEST_EMAIL']), (app.master, os.environ['TEST_PASSWORD'])]:
            entry.delete(0, 'end'); entry.insert(0, value)
        button('Unlock vault').invoke()
        spin(lambda: not app.busy and app.state['unlocked'], 'Mac UI did not unlock over HTTPS')
        layout('vault')
        assert app.master.get() == '' and app.code.get() == ''
        item = next(i for i in app.state['items'] if i['name'] == 'Integration fixture')
        def capture(field):
            app.target = None
            button('Capture app field…').invoke()
            window.after(150, lambda: fixture.command('focus-' + field))
            spin(lambda: app.target is not None, 'Mac UI capture failed', 15)
            assert app.target.pid == fixture.process.pid
            assert app.target.identity == str(Path(fixture.process.args[0]).resolve())
            app.items.selection_set(item['id'])
        capture('user')
        layout('captured')
        before = fixture.command('inspect')
        button('Fill selected field').invoke()
        assert 'Link this login' in app.notice.get(), app.notice.get()
        assert not app.busy and fixture.command('inspect') == before
        print('ACTION Check the fixture executable path in the native app-link dialog and choose Yes: '
            + app.target.identity, flush=True)
        button('Link login to app').invoke()
        spin(lambda: not app.busy, 'Mac app link did not finish saving')
        linked = next(i for i in app.state['items'] if i['id'] == item['id'])
        assert app.linked(linked), 'Native app linking was declined or did not save'
        for field in ('username', 'password', 'code'):
            if field != 'username': capture('password' if field == 'password' else 'code')
            app.field.set(field); button('Fill selected field').invoke()
            spin(lambda: not app.busy, 'Mac native ' + field + ' filling did not finish')
            assert app.notice.get().startswith('Field filled'), app.notice.get()
        values = fixture.command('inspect')
        assert values['user'] == 'test-user'
        assert values['password'] == os.environ['TEST_ITEM_PASSWORD']
        def otp(counter):
            digest = hmac.new(base64.b32decode('GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'),
                struct.pack('>Q', counter), hashlib.sha1).digest(); offset = digest[-1] & 15
            return f'{(struct.unpack(">I", digest[offset:offset+4])[0] & 0x7fffffff) % 1000000:06}'
        counter = int(time.time()) // 30
        assert values['code'] in (otp(counter), otp(counter - 1))
        settings = json.loads((config / 'settings.json').read_text())
        assert set(settings) == {'server', 'email', 'deviceId'}
        assert settings['server'] == os.environ['TEST_SERVER'].rstrip('/')
        assert settings['email'] == os.environ['TEST_EMAIL'].strip().lower()
        assert config.stat().st_mode & 0o077 == 0
        assert (config / 'settings.json').stat().st_mode & 0o077 == 0
        button('Lock').invoke()
        spin(lambda: not app.busy and not app.state['unlocked'], 'Mac UI did not lock')
        assert not app.items.get_children() and app.target is None
        assert not app.vault.winfo_viewable() and app.master.winfo_viewable()
        # Exercise the native Quit callback, including real Node subprocess
        # shutdown. The caller publishes geometry only after all checks pass.
        window.tk.call('::tk::mac::Quit')
        assert app.rpc.process.poll() is not None
        app = None
        return layouts
    finally:
        if app: app.close()
        elif window.tk.call('info', 'commands', '.'): window.destroy()
        if previous is None: os.environ.pop('LOCKBOX_CONFIG_DIR', None)
        else: os.environ['LOCKBOX_CONFIG_DIR'] = previous


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True, help='Packaged LockboxFixture.app')
    parser.add_argument('--disposable-root', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--desktop-ui', action='store_true',
        help='Also run the source vault UI against the disposable integration account; attend its native link dialog.')
    parser.add_argument('--packaged-app', type=Path, help='Frozen Lockbox.app; use instead of --desktop-ui.')
    parser.add_argument('--layout', type=Path, help='Successful source UI geometry from this Mac, required for --packaged-app.')
    args = parser.parse_args()
    if sys.platform != 'darwin': parser.error('Run only on an actual macOS graphical desktop')
    if args.desktop_ui and args.packaged_app: parser.error('Choose source UI or packaged application')
    if bool(args.packaged_app) != bool(args.layout): parser.error('--packaged-app and --layout are required together')
    if args.desktop_ui or args.packaged_app:
        if not all(os.environ.get(name) for name in ('TEST_SERVER', 'TEST_EMAIL', 'TEST_PASSWORD', 'TEST_ITEM_PASSWORD')):
            parser.error('Source or packaged UI acceptance requires the disposable integration account environment')
        if not os.environ['TEST_SERVER'].startswith('https://'):
            parser.error('The desktop UI test requires a disposable HTTPS server')
    root = args.disposable_root.resolve(strict=True)
    if root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077:
        parser.error('The disposable root must be private (0700) and owned by the test user')
    if (root / '.disposable').read_text().strip() != 'lockbox-disposable-macos-test':
        parser.error('Missing explicit disposable Mac test marker')
    report_path = args.report.resolve()
    if not report_path.is_relative_to(root): parser.error('Write reports only inside the disposable root')
    report_path.unlink(missing_ok=True)
    layout_path = report_path.with_name('layout.json')
    if args.desktop_ui: layout_path.unlink(missing_ok=True)
    if args.layout and not args.layout.resolve(strict=True).is_relative_to(root):
        parser.error('Read source UI geometry only from the marked Mac test directory')
    bundle = args.fixture.resolve(strict=True)
    if bundle.suffix != '.app': parser.error('--fixture must be a packaged .app')
    with (bundle / 'Contents/Info.plist').open('rb') as source: metadata = plistlib.load(source)
    if metadata.get('CFBundleIdentifier') != 'local.lockbox.fixture' or metadata.get('CFBundleExecutable') != 'LockboxFixture':
        parser.error('Wrong fixture application identity')
    executable = bundle / 'Contents/MacOS/LockboxFixture'
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(bundle)], check=True)
    import ApplicationServices as AX
    if not AX.AXIsProcessTrusted():
        AX.AXIsProcessTrustedWithOptions({AX.kAXTrustedCheckOptionPrompt: True})
        parser.error('Grant this test process Accessibility permission in System Settings, then rerun')
    os.umask(0o077)
    passed = []
    packaged = None
    source_layout = None
    with tempfile.TemporaryDirectory(prefix='native-', dir=root) as temporary:
        fixture = Fixture(executable, Path(temporary) / 'fixture')
        try:
            adapter = Mac()
            def target(field):
                assert fixture.command('focus-' + field) == 'focused'
                def capture():
                    try:
                        value = adapter.capture()
                        return value if value.pid == fixture.process.pid and value.password == (field == 'password') else None
                    except NativeError: return None
                return wait(capture, 'Could not capture the real Cocoa ' + field + ' control')
            user = target('user'); assert user.identity == str(executable.resolve())
            user.fill('alice-native', 'username')
            password = target('password'); password.fill('disposable-native-secret', 'password')
            code = target('code'); code.fill('123456', 'code')
            assert fixture.command('inspect') == {'user': 'alice-native', 'password': 'disposable-native-secret', 'code': '123456'}
            passed.append('actual Cocoa text/secure text username/password/code filling through Accessibility and executable identity')
            rejected(lambda: user.fill('must-not-fill', 'password'), 'Password entered a non-password control')
            rejected(lambda: password.fill('must-not-fill', 'username'), 'Username entered a secure password control')
            passed.append('password and non-password field role rejection')
            for command, undo in [('hide', 'show'), ('disable', 'enable'), ('readonly', 'writable')]:
                assert fixture.command(command) == command
                time.sleep(.2)
                rejected(lambda: password.fill('must-not-fill', 'password'), command + ' control accepted filling')
                assert fixture.command(undo) == undo
                assert fixture.command('inspect')['password'] == 'disposable-native-secret'
                passed.append(command + ' control rejection without altering its value')
            if args.desktop_ui:
                source_layout = desktop_ui(fixture, Path(temporary))
                passed.append('source Tk UI HTTPS unlock, refusal before linking, attended native app-link confirmation, '
                    'real AX username/password/TOTP filling, private settings, lock and Mac Quit bridge shutdown')
            elif args.packaged_app:
                from packaged_macos import exercise
                packaged = exercise(args.packaged_app, fixture, Path(temporary), args.layout)
                passed.append('frozen Mac GUI bundled runtime, HTTPS unlock, unlinked refusal, attended native app link, '
                    'actual AX username/password/TOTP fill, private settings, lock and normal Quit')
            fixture.close()
            rejected(lambda: user.fill('must-not-fill', 'username'), 'Closed application accepted filling')
            passed.append('closed application rejection')
        finally: fixture.close()
    report = {'ok': True, 'platform': sys.platform, 'macOS': platform.mac_ver()[0],
        'architecture': platform.machine(), 'python': sys.version.split()[0],
        'desktopUi': args.desktop_ui or bool(args.packaged_app), 'packaged': packaged, 'passed': passed}
    if source_layout is not None:
        source_layout['sourceReport'] = report_path.name
        geometry = (json.dumps(source_layout, indent=2) + '\n').encode()
        report['layoutSha256'] = hashlib.sha256(geometry).hexdigest()
        layout_path.write_bytes(geometry)
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    for entry in passed: print('PASS ' + entry)


if __name__ == '__main__': main()
