"""Drive the frozen Windows GUI with input events in the owned test desktop.

The source UI exports public widget rectangles on this exact Tk/DPI runtime.
This driver uses those rectangles, native window visibility, an actual native
confirmation dialog and inspected fixture values. It opens no application RPC
or Tcl debugging endpoint and never types into the fixture's password fields.
"""
import base64
import ctypes as C
from ctypes import wintypes as W
import hashlib
import hmac
import json
import os
from pathlib import Path
import struct
import subprocess
import time


def wait(predicate, message, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value: return value
        time.sleep(.05)
    raise AssertionError(message)


class Desktop:
    def __init__(self, process):
        self.process = process
        self.api = C.WinDLL('user32', use_last_error=True)
        self.callback = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        for name, args, result in [
            ('EnumWindows', [self.callback, W.LPARAM], W.BOOL),
            ('EnumChildWindows', [W.HWND, self.callback, W.LPARAM], W.BOOL),
            ('GetWindowThreadProcessId', [W.HWND, C.POINTER(W.DWORD)], W.DWORD),
            ('GetWindowTextW', [W.HWND, W.LPWSTR, C.c_int], C.c_int),
            ('GetClassNameW', [W.HWND, W.LPWSTR, C.c_int], C.c_int),
            ('IsWindowVisible', [W.HWND], W.BOOL),
            ('IsWindow', [W.HWND], W.BOOL),
            ('GetClientRect', [W.HWND, C.POINTER(W.RECT)], W.BOOL),
            ('GetWindowRect', [W.HWND, C.POINTER(W.RECT)], W.BOOL),
            ('ClientToScreen', [W.HWND, C.POINTER(W.POINT)], W.BOOL),
            ('MoveWindow', [W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, W.BOOL], W.BOOL),
            ('WindowFromPoint', [W.POINT], W.HWND),
            ('GetForegroundWindow', [], W.HWND),
            ('SetCursorPos', [C.c_int, C.c_int], W.BOOL),
            ('GetDlgItem', [W.HWND, C.c_int], W.HWND),
            ('PostMessageW', [W.HWND, W.UINT, W.WPARAM, W.LPARAM], W.BOOL),
            ('mouse_event', [W.DWORD, W.DWORD, W.DWORD, W.DWORD, C.c_size_t], None),
        ]:
            method = getattr(self.api, name); method.argtypes = args; method.restype = result
        self.window = wait(self.find, 'Frozen Credlet window did not appear')
        rect = W.RECT(); self.api.GetWindowRect(self.window, C.byref(rect))
        assert self.api.MoveWindow(self.window, 20, 20, rect.right - rect.left, rect.bottom - rect.top, True)

    def pid(self, handle):
        value = W.DWORD(); self.api.GetWindowThreadProcessId(handle, C.byref(value))
        return value.value

    def text(self, handle, classname=False):
        value = C.create_unicode_buffer(4096)
        method = self.api.GetClassNameW if classname else self.api.GetWindowTextW
        method(handle, value, len(value))
        return value.value

    def windows(self, parent=None):
        found = []
        @self.callback
        def collect(handle, _):
            if self.pid(handle) == self.process.pid: found.append(handle)
            return True
        if parent: self.api.EnumChildWindows(parent, collect, 0)
        else: self.api.EnumWindows(collect, 0)
        return found

    def find(self):
        if self.process.poll() is not None: raise AssertionError('Frozen application stopped before opening.')
        return next((h for h in self.windows() if self.text(h) == 'Credlet' and self.api.IsWindowVisible(h)), None)

    def origin(self):
        point = W.POINT(0, 0); assert self.api.ClientToScreen(self.window, C.byref(point))
        return point

    def has_rectangle(self, rectangle):
        x, y, width, height = rectangle; origin = self.origin()
        for handle in self.windows(self.window):
            if not self.api.IsWindowVisible(handle): continue
            rect = W.RECT(); self.api.GetWindowRect(handle, C.byref(rect))
            actual = [rect.left - origin.x, rect.top - origin.y, rect.right - rect.left, rect.bottom - rect.top]
            if actual == [x, y, width, height]: return True
        return False

    def click(self, rectangle, screen=False):
        x, y, width, height = rectangle
        origin = W.POINT(0, 0) if screen else self.origin()
        point = W.POINT(origin.x + x + width // 2, origin.y + y + height // 2)
        # Input must land on this exact owned application, even if another
        # window happens to cover its expected coordinates.
        handle = self.api.WindowFromPoint(point)
        assert self.pid(handle) == self.process.pid, 'Frozen UI click is covered by another process.'
        assert self.api.SetCursorPos(point.x, point.y)
        self.api.mouse_event(2, 0, 0, 0, 0); self.api.mouse_event(4, 0, 0, 0, 0)
        time.sleep(.08)

    def keys(self, events):
        assert self.pid(self.api.GetForegroundWindow()) == self.process.pid, 'Refusing keyboard input outside frozen Credlet.'
        class Keyboard(C.Structure):
            _fields_ = [('virtual', W.WORD), ('scan', W.WORD), ('flags', W.DWORD), ('time', W.DWORD), ('extra', C.c_size_t)]
        class Mouse(C.Structure):
            _fields_ = [('x', W.LONG), ('y', W.LONG), ('data', W.DWORD), ('flags', W.DWORD), ('time', W.DWORD), ('extra', C.c_size_t)]
        class Data(C.Union):
            _fields_ = [('keyboard', Keyboard), ('mouse', Mouse)]
        class Input(C.Structure):
            _fields_ = [('type', W.DWORD), ('data', Data)]
        records = (Input * len(events))()
        for record, (virtual, scan, flags) in zip(records, events):
            record.type = 1; record.data.keyboard = Keyboard(virtual, scan, flags, 0, 0)
        self.api.SendInput.argtypes = [W.UINT, C.POINTER(Input), C.c_int]
        self.api.SendInput.restype = W.UINT
        assert self.api.SendInput(len(records), records, C.sizeof(Input)) == len(records)
        time.sleep(.1)

    def key(self, value):
        self.keys([(value, 0, 0), (value, 0, 2)])

    def type(self, rectangle, value):
        self.click(rectangle)
        self.keys([(0x11, 0, 0), (0x41, 0, 0), (0x41, 0, 2), (0x11, 0, 2)])
        raw = value.encode('utf-16le'); events = []
        for offset in range(0, len(raw), 2):
            character = int.from_bytes(raw[offset:offset+2], 'little')
            events.extend([(0, character, 4), (0, character, 6)])
        self.keys(events)


def exercise(executable, fixture, root, layout_path):
    root = Path(root); executable = Path(executable).resolve()
    layouts = json.loads(Path(layout_path).read_text(encoding='utf-8-sig'))
    signin, vault, captured = (layouts[key] for key in ('signin', 'vault', 'captured'))
    assert all(key in signin for key in ('server', 'email', 'master', 'unlock'))
    environment = {**os.environ, 'PATH': r'C:\Windows\System32;C:\Windows',
        'CREDLET_CONFIG_DIR': str(root / 'frozen-settings')}
    for name in ('PYTHONPATH', 'PYTHONHOME', 'TCL_LIBRARY', 'TK_LIBRARY'): environment.pop(name, None)
    runtime_report = root / 'frozen-runtime.json'
    runtime = subprocess.run([str(executable), '--check-runtime', '--report', str(runtime_report)],
        env=environment, timeout=20)
    assert runtime.returncode == 0
    diagnostic = json.loads(runtime_report.read_text()); assert diagnostic['ok'] and diagnostic['bundled']
    process = subprocess.Popen([str(executable)], env=environment)
    try:
        desktop = Desktop(process)
        rectangle = W.RECT(); desktop.api.GetClientRect(desktop.window, C.byref(rectangle))
        assert [rectangle.right, rectangle.bottom] == signin['clientSize']
        wait(lambda: desktop.has_rectangle(signin['server']), 'Frozen sign-in layout differs from tested Windows runtime')
        for key, variable in [('server', 'TEST_SERVER'), ('email', 'TEST_EMAIL'), ('master', 'TEST_PASSWORD')]:
            desktop.type(signin[key], os.environ[variable])
        desktop.click(signin['unlock'])
        wait(lambda: desktop.has_rectangle(vault['tree']), 'Frozen Windows UI did not unlock over HTTPS', 45)
        def capture(field):
            desktop.click(vault['capture'])
            wait(lambda: not desktop.api.IsWindowVisible(desktop.window), 'Frozen capture did not hide its window')
            assert fixture.command('focus-' + field) == 'focused'
            wait(lambda: desktop.api.IsWindowVisible(desktop.window), 'Frozen capture did not return', 10)
            wait(lambda: desktop.has_rectangle(captured['tree']), 'Frozen captured-field layout is missing')
        capture('user')
        desktop.type(captured['query'], 'Integration fixture')
        def select():
            tree = captured['tree']; row = captured['row']
            desktop.click([tree[0] + row[0], tree[1] + row[1], row[2], row[3]])
        select()
        before = fixture.command('inspect')
        desktop.click(captured['fill']); time.sleep(.3)
        assert fixture.command('inspect') == before, 'Frozen UI filled an unlinked application'
        desktop.click(captured['link'])
        dialog = wait(lambda: next((h for h in desktop.windows() if desktop.text(h, True) == '#32770' and
            desktop.text(h) == 'Link login to application'), None), 'Frozen app-link confirmation did not open')
        texts = '\n'.join(desktop.text(h) for h in desktop.windows(dialog))
        assert str(Path(fixture.process.args[0]).resolve()).lower() in texts.lower()
        yes = desktop.api.GetDlgItem(dialog, 6); assert yes
        button = W.RECT(); desktop.api.GetWindowRect(yes, C.byref(button))
        desktop.click([button.left, button.top, button.right-button.left, button.bottom-button.top], screen=True)
        wait(lambda: not desktop.api.IsWindow(dialog), 'Frozen app-link confirmation did not close')
        def filled(field, expected):
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                desktop.click(captured['fill']); time.sleep(.2)
                value = fixture.command('inspect')[field]
                if expected(value): return
            raise AssertionError('Frozen native ' + field + ' filling failed')
        filled('user', lambda value: value == 'test-user')
        capture('password'); select()
        filled('password', lambda value: value == os.environ['TEST_ITEM_PASSWORD'])
        capture('code'); select()
        desktop.click(captured['field']); desktop.key(0x24)
        desktop.key(0x28); desktop.key(0x28); desktop.key(0x0D)
        def valid_code(value):
            def otp(counter):
                digest = hmac.new(base64.b32decode('GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'),
                    struct.pack('>Q', counter), hashlib.sha1).digest(); offset = digest[-1] & 15
                return f'{(struct.unpack(">I",digest[offset:offset+4])[0]&0x7fffffff)%1000000:06}'
            counter = int(time.time()) // 30
            return value in (otp(counter), otp(counter-1))
        filled('code', valid_code)
        assert set(json.loads((root / 'frozen-settings/settings.json').read_text())) == {'server', 'email', 'deviceId'}
        desktop.click(captured['lock'])
        wait(lambda: not desktop.has_rectangle(captured['tree']), 'Frozen Windows vault did not hide on lock')
        assert any(desktop.has_rectangle([signin['master'][0], y, *signin['master'][2:]])
            for y in range(signin['master'][1] - 40, signin['master'][1] + 41))
        assert desktop.api.PostMessageW(desktop.window, 0x10, 0, 0)
        process.wait(timeout=10); assert process.returncode == 0
    finally:
        if process.poll() is None: process.terminate(); process.wait(timeout=5)
