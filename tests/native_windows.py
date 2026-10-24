#!/usr/bin/env python3
"""Real Windows native-field acceptance on the disposable interactive desktop."""
import argparse
import base64
import contextlib
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import struct
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop.native import Windows, NativeError


def wait(predicate, message, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value: return value
        time.sleep(.05)
    raise AssertionError(message)


class Fixture:
    def __init__(self, executable, root):
        self.root = Path(root); self.serial = 0
        self.root.mkdir()
        (self.root / '.disposable').write_text('lockbox-native-windows-fixture\n')
        self.process = subprocess.Popen([str(executable), str(self.root)])
        wait(lambda: (self.root / 'ready.json').exists(), 'Win32 fixture did not start.')
        self.ready = json.loads((self.root / 'ready.json').read_text())
        assert self.ready['pid'] == self.process.pid

    def command(self, command):
        self.serial += 1
        path = self.root / 'request.json'
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'id': self.serial, 'command': command}))
        temporary.replace(path)
        def response():
            path = self.root / 'response.json'
            if not path.exists(): return None
            value = json.loads(path.read_text())
            if value.get('id') != self.serial and value.get('ok'): return None
            assert value['ok'], value.get('error')
            return value
        return wait(response, 'Win32 fixture command timed out.')['value']

    def close(self):
        if self.process.poll() is None:
            self.process.terminate(); self.process.wait(timeout=5)


def rejected(action, message):
    try: action()
    except NativeError: return
    raise AssertionError(message)


@contextlib.contextmanager
def interactive_display():
    """Keep this disposable desktop awake only while acceptance is running."""
    import ctypes as C
    from ctypes import wintypes as W
    kernel = C.WinDLL('kernel32', use_last_error=True)
    kernel.SetThreadExecutionState.argtypes = [W.DWORD]
    kernel.SetThreadExecutionState.restype = W.DWORD
    assert kernel.SetThreadExecutionState(0x80000003), 'Could not keep the test display awake'
    try: yield
    finally: kernel.SetThreadExecutionState(0x80000000)


def desktop_ui(fixture, root, runtime, layout_path):
    """Exercise actual Tk widgets and real target controls in the same desktop."""
    import tkinter as tk
    from desktop.app import App
    os.environ['LOCKBOX_CONFIG_DIR'] = str(root / 'settings')
    window = tk.Tk(); app = App(window, runtime_directory=runtime)
    def spin(predicate, message, seconds=30):
        def tick():
            window.update()
            return predicate()
        try: return wait(tick, message, seconds)
        except AssertionError as error: raise AssertionError(message + ': ' + app.notice.get()) from error
    def button(text):
        return next(b for b in app.buttons if b.cget('text') == text)
    layouts = {}
    def layout(name):
        window.update_idletasks()
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        widgets = {'server': app.server, 'email': app.email, 'master': app.master,
            'loginCode': app.code, 'unlock': button('Unlock vault'), 'lock': button('Lock'),
            'capture': button('Capture app field…'), 'tree': app.items,
            'fill': button('Fill selected field'), 'link': button('Link login to app')}
        for key, kind in [('query', 'TEntry'), ('field', 'TCombobox')]:
            widgets[key] = next(w for w in descendants(app.vault) if w.winfo_class() == kind)
        layouts[name] = {key: [w.winfo_rootx() - window.winfo_rootx(),
            w.winfo_rooty() - window.winfo_rooty(), w.winfo_width(), w.winfo_height()]
            for key, w in widgets.items() if w.winfo_viewable()}
        layouts[name]['clientSize'] = [window.winfo_width(), window.winfo_height()]
        if app.items.winfo_viewable() and app.items.get_children():
            layouts[name]['row'] = list(app.items.bbox(app.items.get_children()[0]))
        layout_path.write_text(json.dumps(layouts, indent=2) + '\n')
    try:
        for entry, value in [(app.server, os.environ['TEST_SERVER']),
                (app.email, os.environ['TEST_EMAIL']), (app.master, os.environ['TEST_PASSWORD'])]:
            entry.delete(0, 'end'); entry.insert(0, value)
        spin(lambda: bool(app.server.winfo_viewable()), 'Windows sign-in form did not become visible')
        layout('signin')
        button('Unlock vault').invoke()
        spin(lambda: not app.busy and app.state['unlocked'], 'Windows UI did not unlock')
        layout('vault')
        item = next(i for i in app.state['items'] if i['name'] == 'Integration fixture')
        def capture(field):
            app.target = None
            button('Capture app field…').invoke()
            window.after(150, lambda: fixture.command('focus-' + field))
            spin(lambda: app.target is not None, 'Windows UI capture failed')
            assert app.target.pid == fixture.process.pid
            app.items.selection_set(item['id'])
        capture('user')
        layout('captured')
        button('Fill selected field').invoke()
        assert 'Link this login' in app.notice.get(), app.notice.get()
        # Windows uses the native message box rather than Tk's X11 dialog.
        # Return accepts its focused Yes button only after its actual window exists.
        import ctypes as C
        from ctypes import wintypes as W
        user32 = C.WinDLL('user32', use_last_error=True)
        user32.FindWindowW.argtypes = [W.LPCWSTR, W.LPCWSTR]
        user32.FindWindowW.restype = W.HWND
        user32.GetDlgItem.argtypes = [W.HWND, C.c_int]; user32.GetDlgItem.restype = W.HWND
        user32.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
        def confirm():
            dialog = wait(lambda: user32.FindWindowW('#32770', 'Link login to application'),
                'Windows link confirmation did not appear')
            yes = user32.GetDlgItem(dialog, 6)  # IDYES
            assert yes
            user32.PostMessageW(yes, 0xF5, 0, 0)  # BM_CLICK on this dialog's button.
        confirmer = threading.Thread(target=confirm, daemon=True); confirmer.start()
        button('Link login to app').invoke()
        confirmer.join(timeout=1); assert not confirmer.is_alive()
        spin(lambda: not app.busy, 'Windows app link did not save')
        assert app.linked(next(i for i in app.state['items'] if i['id'] == item['id']))
        for field in ('username', 'password', 'code'):
            if field != 'username': capture('password' if field == 'password' else 'code')
            app.field.set(field); button('Fill selected field').invoke()
            spin(lambda: not app.busy, 'Windows filling did not finish')
            assert app.notice.get().startswith('Field filled'), app.notice.get()
        values = fixture.command('inspect')
        assert values['user'] == 'test-user' and values['password'] == os.environ['TEST_ITEM_PASSWORD']
        def otp(counter):
            digest = hmac.new(base64.b32decode('GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'),
                struct.pack('>Q', counter), hashlib.sha1).digest(); offset = digest[-1] & 15
            return f'{(struct.unpack(">I", digest[offset:offset+4])[0] & 0x7fffffff) % 1000000:06}'
        counter = int(time.time()) // 30
        assert values['code'] in (otp(counter), otp(counter - 1))
        assert set(json.loads((root / 'settings/settings.json').read_text())) == {'server', 'email', 'deviceId'}
        button('Lock').invoke()
        spin(lambda: not app.busy and not app.state['unlocked'], 'Windows UI did not lock')
        assert not app.items.get_children() and app.target is None
    finally: app.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--desktop-ui', action='store_true')
    parser.add_argument('--packaged-app', type=Path)
    parser.add_argument('--layout', type=Path)
    parser.add_argument('--runtime-directory', type=Path)
    parser.add_argument('--environment', type=Path, help='Private environment supplied by the owned-VM integration harness.')
    args = parser.parse_args()
    if args.desktop_ui and args.packaged_app: parser.error('Choose source UI or packaged application')
    if args.packaged_app and not args.layout: parser.error('--packaged-app requires --layout')
    if sys.platform != 'win32' or os.environ.get('COMPUTERNAME') != 'LOCKBOX-TEST':
        raise RuntimeError('Run only on the disposable LOCKBOX-TEST Windows VM.')
    if args.environment:
        values = json.loads(args.environment.read_text(encoding='utf-8'))
        assert set(values) == {'TEST_SERVER', 'TEST_EMAIL', 'TEST_PASSWORD', 'TEST_ITEM_PASSWORD', 'NODE_EXTRA_CA_CERTS'}
        assert all(isinstance(value, str) for value in values.values())
        os.environ.update(values)
    passed = []
    with interactive_display(), tempfile.TemporaryDirectory(prefix='lockbox-native-') as tmp:
        fixture = Fixture(args.fixture.resolve(), Path(tmp) / 'fixture')
        try:
            adapter = Windows()
            def target(field):
                assert fixture.command('focus-' + field) == 'focused'
                def capture():
                    try:
                        value = adapter.capture()
                        return value if value.pid == fixture.process.pid and value.password == (field == 'password') else None
                    except NativeError: return None
                return wait(capture, 'Could not capture the real Win32 ' + field + ' field.')
            user = target('user')
            assert user.identity == os.path.normcase(str(args.fixture.resolve()))
            user.fill('alice-native', 'username')
            password = target('password'); password.fill('disposable-native-secret', 'password')
            code = target('code'); code.fill('123456', 'code')
            assert fixture.command('inspect') == {'user': 'alice-native', 'password': 'disposable-native-secret', 'code': '123456'}
            passed.append('actual Win32 EDIT username/password/code filling through UI Automation and executable identity')
            if args.packaged_app:
                from packaged_windows import exercise
                exercise(args.packaged_app, fixture, Path(tmp), args.layout)
                passed.append('actual frozen Windows application: bundled runtime, HTTPS unlock, explicit app link, native username/password/TOTP fill, private settings and lock')
            elif args.desktop_ui:
                desktop_ui(fixture, Path(tmp), args.runtime_directory, args.report.with_name('layout.json'))
                passed.append('actual Windows Tk UI HTTPS unlock, explicit app linking, native password/TOTP fill, private settings and lock')
            rejected(lambda: user.fill('must-not-fill', 'password'), 'Password entered a non-password field.')
            rejected(lambda: password.fill('must-not-fill', 'username'), 'Username entered a password field.')
            passed.append('password and non-password field role rejection')
            expected_password = fixture.command('inspect')['password']
            for command, undo in [('hide', 'show'), ('disable', 'enable'), ('readonly', 'writable')]:
                assert fixture.command(command) == command
                time.sleep(.2)
                try:
                    rejected(lambda: password.fill('must-not-fill', 'password'), command + ' field accepted filling.')
                except AssertionError:
                    import ctypes as C
                    from ctypes import wintypes as W
                    visible = C.WinDLL('user32').IsWindowVisible
                    visible.argtypes = [W.HWND]; visible.restype = W.BOOL
                    node = password.reference
                    print(json.dumps({'fieldState': command, 'offscreen': bool(node.CurrentIsOffscreen),
                        'enabled': bool(node.CurrentIsEnabled), 'windowVisible': bool(visible(node.CurrentNativeWindowHandle)),
                        'handle': node.CurrentNativeWindowHandle}), flush=True)
                    raise
                assert fixture.command(undo) == undo
                assert fixture.command('inspect')['password'] == expected_password
                passed.append(command + ' field rejection without altering its value')
            fixture.close()
            rejected(lambda: user.fill('must-not-fill', 'username'), 'Closed app accepted filling.')
            passed.append('closed application rejection')
        finally: fixture.close()
    report = {'ok': True, 'platform': sys.platform, 'python': sys.version.split()[0], 'passed': passed}
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    for entry in passed: print('PASS ' + entry)


if __name__ == '__main__': main()
