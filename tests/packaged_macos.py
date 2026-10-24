"""Attended frozen Mac GUI acceptance, with input restricted to its owned PID.

Public widget rectangles come from a source UI run on the same Tk/architecture.
No product RPC, Tcl debugging endpoint, clipboard or fixture fill command is
used. Cocoa app-link confirmation and normal macOS permissions are attended.
This driver must still be exercised on an actual Mac before claiming support.
"""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import platform
import plistlib
import struct
import subprocess
import sys
import time


def wait(predicate, message, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result: return result
        time.sleep(.05)
    raise AssertionError(message)


def windows(quartz, pid, onscreen=False):
    result = quartz.CGWindowListCopyWindowInfo(quartz.kCGWindowListOptionAll, quartz.kCGNullWindowID)
    return [w for w in result if int(w.get(quartz.kCGWindowOwnerPID, -1)) == pid
        and int(w.get(quartz.kCGWindowLayer, -1)) == 0
        and (not onscreen or bool(w.get(quartz.kCGWindowIsOnscreen)))]


def bounds(quartz, window):
    value = window[quartz.kCGWindowBounds]
    return [float(value[k]) for k in ('X', 'Y', 'Width', 'Height')]


class Desktop:
    def __init__(self, process, executable):
        if sys.platform != 'darwin': raise RuntimeError('Frozen Mac GUI input requires macOS')
        import ApplicationServices as AX
        import Quartz as Q
        from AppKit import NSRunningApplication, NSApplicationActivateIgnoringOtherApps
        self.A = AX; self.Q = Q; self.process = process
        self.executable = str(Path(executable).resolve(strict=True))
        self.running = NSRunningApplication.runningApplicationWithProcessIdentifier_(process.pid)
        self.activation = NSApplicationActivateIgnoringOtherApps
        self.application = AX.AXUIElementCreateApplication(process.pid)
        self.system = AX.AXUIElementCreateSystemWide()
        self.verify_process()
        visible = wait(lambda: windows(Q, process.pid, True), 'Frozen Mac window did not appear')
        assert len(visible) == 1, 'Expected one owned normal window before sign-in'
        self.window_id = int(visible[0][Q.kCGWindowNumber])

    def verify_process(self):
        assert self.process.poll() is None, 'Frozen Credlet process stopped'
        assert self.running and not self.running.isTerminated(), 'Owned Mac application is unavailable'
        url = self.running.executableURL()
        assert url and str(Path(str(url.path())).resolve(strict=True)) == self.executable, 'Owned executable identity changed'

    def window(self):
        self.verify_process()
        return next((w for w in windows(self.Q, self.process.pid, True)
            if int(w[self.Q.kCGWindowNumber]) == self.window_id), None)

    def attribute(self, node, name):
        error, value = self.A.AXUIElementCopyAttributeValue(node, name, None)
        return None if error else value

    def nodes(self, roots):
        # Missing AX exposure must fail acceptance, rather than reducing GUI
        # verification to a delay followed by clicks at guessed coordinates.
        self.verify_process()
        queue = list(roots); visited = set()
        for _ in range(1500):
            if not queue: break
            node = queue.pop(0)
            marker = hash(node)
            if marker in visited: continue
            visited.add(marker)
            error, pid = self.A.AXUIElementGetPid(node, None)
            assert not error and pid == self.process.pid, 'AX tree escaped the owned process'
            yield node
            queue.extend(self.attribute(node, 'AXChildren') or [])
            queue.extend(self.attribute(node, 'AXSheets') or [])
        else: raise AssertionError('Owned AX hierarchy exceeded the traversal limit')

    def text(self, root=None):
        roots = (self.attribute(self.application, 'AXWindows') or []) if root is None else [root]
        result = []
        for node in self.nodes(roots):
            for key in ('AXTitle', 'AXDescription', 'AXValue'):
                value = self.attribute(node, key)
                if isinstance(value, str): result.append(value)
        return '\n'.join(result)

    def dialog_text(self):
        roots = self.attribute(self.application, 'AXWindows') or []
        return '\n'.join(self.text(node) for node in self.nodes(roots)
            if self.attribute(node, 'AXRole') == 'AXSheet' or
            self.attribute(node, 'AXSubrole') in ('AXDialog', 'AXSystemDialog'))

    def activate(self):
        self.verify_process()
        assert self.running.activateWithOptions_(self.activation), 'Could not activate owned Credlet'
        wait(lambda: self.running.isActive(), 'Owned Credlet did not become active')

    def input_ready(self):
        self.verify_process()
        assert self.running.isActive(), 'Refusing input while another application is active'

    def click(self, rectangle, layout):
        self.activate()
        window = self.window(); assert window, 'Frozen window is hidden'
        frame = bounds(self.Q, window)
        assert frame[2:] == layout['frameSize'], 'Frozen window size differs from the measured source layout'
        x, y, width, height = rectangle
        cx, cy = layout['contentOffset']
        point = (frame[0] + cx + x + width / 2, frame[1] + cy + y + height / 2)
        assert width > 0 and height > 0
        assert frame[0] <= point[0] < frame[0] + frame[2] and frame[1] <= point[1] < frame[1] + frame[3]
        error, node = self.A.AXUIElementCopyElementAtPosition(self.system, *point, None)
        assert not error, 'Cannot identify the application at the click location'
        error, pid = self.A.AXUIElementGetPid(node, None)
        assert not error and pid == self.process.pid, 'Refusing a click covered by another process'
        for kind in (self.Q.kCGEventLeftMouseDown, self.Q.kCGEventLeftMouseUp):
            self.input_ready()
            event = self.Q.CGEventCreateMouseEvent(None, kind, point, self.Q.kCGMouseButtonLeft)
            assert event is not None
            self.Q.CGEventSetIntegerValueField(event, self.Q.kCGMouseEventClickState, 1)
            self.Q.CGEventPostToPid(self.process.pid, event)
        time.sleep(.1)

    def key(self, virtual, flags=0, character=None):
        for down in (True, False):
            self.input_ready()
            event = self.Q.CGEventCreateKeyboardEvent(None, virtual, down)
            assert event is not None
            self.Q.CGEventSetFlags(event, flags)
            if character is not None:
                self.Q.CGEventKeyboardSetUnicodeString(event, len(character.encode('utf-16-le')) // 2, character)
            self.Q.CGEventPostToPid(self.process.pid, event)
        time.sleep(.02)

    def type(self, rectangle, value, layout):
        self.click(rectangle, layout)
        self.key(0, self.Q.kCGEventFlagMaskCommand)  # Command-A
        for character in value: self.key(0, character=character)


def exercise(bundle, fixture, root, layout_path):
    if sys.platform != 'darwin': raise RuntimeError('Packaged Mac acceptance requires an actual Mac')
    root = Path(root); bundle = Path(bundle).resolve(strict=True)
    with (bundle / 'Contents/Info.plist').open('rb') as source: metadata = plistlib.load(source)
    assert bundle.suffix == '.app' and metadata.get('CFBundleIdentifier') == 'local.credlet.desktop'
    assert metadata.get('CFBundleExecutable') == 'Credlet'
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(bundle)], check=True)
    executable = bundle / 'Contents/MacOS/Credlet'
    geometry = Path(layout_path).read_bytes()
    layouts = json.loads(geometry)
    assert layouts['platform'] == 'darwin' and layouts['architecture'] == platform.machine()
    assert layouts['fixtureExecutable'] == str(Path(fixture.process.args[0]).resolve())
    assert Path(layouts['sourceReport']).name == layouts['sourceReport']
    source_report = json.loads(Path(layout_path).with_name(layouts['sourceReport']).read_text())
    assert source_report['ok'] and source_report['desktopUi'] and source_report['packaged'] is None
    assert source_report['layoutSha256'] == hashlib.sha256(geometry).hexdigest(), 'Geometry does not match a successful source acceptance report'
    signin, vault, captured = (layouts[key] for key in ('signin', 'vault', 'captured'))
    environment = {**os.environ, 'PATH': '/usr/bin:/bin', 'CREDLET_CONFIG_DIR': str(root / 'frozen-settings')}
    for name in ('PYTHONPATH', 'PYTHONHOME', 'TCL_LIBRARY', 'TK_LIBRARY', 'DYLD_LIBRARY_PATH', 'DYLD_FRAMEWORK_PATH'):
        environment.pop(name, None)
    runtime_report = root / 'frozen-runtime.json'
    subprocess.run([str(executable), '--check-runtime', '--report', str(runtime_report)],
        env=environment, check=True, timeout=30)
    diagnostic = json.loads(runtime_report.read_text())
    assert diagnostic['ok'] and diagnostic['bundled'] and diagnostic['platform'] == 'darwin'
    # The legacy runtime diagnostic's "tk" field contains Tcl's patch level.
    assert diagnostic['tk'] == layouts['tcl'] and diagnostic['python'] == layouts['python'], \
        'Source/frozen interpreters differ; regenerate layout with the build interpreter'
    process = subprocess.Popen([str(executable)], env=environment)
    try:
        desktop = Desktop(process, executable)
        wait(lambda: 'Server HTTPS address' in desktop.text(), 'Frozen Mac sign-in form is not exposed through AX')
        for key, variable in [('server', 'TEST_SERVER'), ('email', 'TEST_EMAIL'), ('master', 'TEST_PASSWORD')]:
            desktop.type(signin[key], os.environ[variable], signin)
        desktop.click(signin['unlock'], signin)
        wait(lambda: 'Capture app field' in desktop.text(), 'Frozen Mac UI did not unlock over HTTPS', 45)
        def capture(field):
            desktop.click(vault['capture'], vault)
            wait(lambda: desktop.window() is None, 'Frozen Mac capture did not withdraw its window')
            assert fixture.command('focus-' + field) == 'focused'
            wait(desktop.window, 'Frozen Mac capture did not restore its window', 10)
            wait(lambda: layouts['fixtureExecutable'] in desktop.text(), 'Frozen capture did not display the exact fixture path')
        capture('user')
        desktop.type(captured['query'], 'Integration fixture', captured)
        def select():
            tree = captured['tree']; row = captured['row']
            desktop.click([tree[0] + row[0], tree[1] + row[1], row[2], row[3]], captured)
        select()
        before = fixture.command('inspect')
        desktop.click(captured['fill'], captured)
        wait(lambda: 'Link this login to the captured application first.' in desktop.text(), 'Frozen UI did not refuse an unlinked fill')
        assert fixture.command('inspect') == before
        desktop.click(captured['link'], captured)
        question = 'Allow “Integration fixture” to fill fields in this application?'
        wait(lambda: question in desktop.dialog_text(),
            'Frozen native app-link confirmation text was not exposed')
        assert layouts['fixtureExecutable'] in desktop.dialog_text(), 'Confirmation does not expose the exact fixture path'
        print('ACTION Verify the fixture path in the frozen Mac app-link dialog and choose Yes: '
            + layouts['fixtureExecutable'], flush=True)
        def filled(field, expected):
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if desktop.dialog_text():
                    time.sleep(.1); continue
                desktop.click(captured['fill'], captured)
                time.sleep(.2)
                if expected(fixture.command('inspect')[field]): return
            raise AssertionError('Frozen Mac ' + field + ' filling failed')
        filled('user', lambda value: value == 'test-user')
        capture('password'); select()
        filled('password', lambda value: value == os.environ['TEST_ITEM_PASSWORD'])
        capture('code'); select()
        desktop.click(captured['field'], captured)
        for key in (126, 126, 126, 125, 125, 36): desktop.key(key)  # top, down twice, Return
        def valid_code(value):
            def otp(counter):
                digest = hmac.new(base64.b32decode('GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'),
                    struct.pack('>Q', counter), hashlib.sha1).digest(); offset = digest[-1] & 15
                return f'{(struct.unpack(">I", digest[offset:offset+4])[0] & 0x7fffffff) % 1000000:06}'
            counter = int(time.time()) // 30
            return value in (otp(counter), otp(counter - 1))
        filled('code', valid_code)
        settings = root / 'frozen-settings/settings.json'
        assert set(json.loads(settings.read_text())) == {'server', 'email', 'deviceId'}
        assert settings.stat().st_mode & 0o077 == 0
        desktop.click(captured['lock'], captured)
        wait(lambda: 'Server HTTPS address' in desktop.text() and 'Capture app field' not in desktop.text(),
            'Frozen Mac vault did not hide on lock')
        # Record the actual bridge child, then require it to disappear as well
        # as the GUI. A successful GUI exit alone could leave a vault orphan.
        children = subprocess.check_output(['/bin/ps', '-axo', 'pid=,ppid=,comm='], text=True)
        bridges = []
        for line in children.splitlines():
            columns = line.split(None, 2)
            if len(columns) == 3 and int(columns[1]) == process.pid and Path(columns[2]).name == 'node':
                bridges.append(int(columns[0]))
        assert len(bridges) == 1, 'Expected exactly one owned vault bridge subprocess'
        def bridge_stopped():
            try: os.kill(bridges[0], 0)
            except ProcessLookupError: return True
            return False
        # Command-Q invokes the actual application close handler. Its key-down
        # can close the process immediately, so do not require a subsequent
        # key-up to be delivered to an application that has already exited.
        desktop.activate(); desktop.input_ready()
        quit_event = desktop.Q.CGEventCreateKeyboardEvent(None, 12, True)
        assert quit_event is not None
        desktop.Q.CGEventSetFlags(quit_event, desktop.Q.kCGEventFlagMaskCommand)
        desktop.Q.CGEventPostToPid(process.pid, quit_event)
        process.wait(timeout=10); assert process.returncode == 0
        wait(bridge_stopped, 'Mac Quit left its vault bridge subprocess alive', 5)
    finally:
        if process.poll() is None: process.terminate(); process.wait(timeout=5)
    return {'executableSha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
        'runtime': diagnostic, 'layout': str(Path(layout_path).resolve()), 'bundled': True}
