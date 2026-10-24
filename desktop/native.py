"""Capture and fill a specific native accessibility element. Never type into global focus."""
from dataclasses import dataclass
import os
import re
from pathlib import Path
import sys
from urllib.parse import quote


class NativeError(RuntimeError):
    pass


def app_uri(platform, identity):
    return 'credlet-app://' + platform + '/' + quote(identity, safe='')


def canonical_app_uri(uri):
    """Keep previously linked applications usable after the display-name change."""
    return 'credlet-app://' + uri[len('lockbox-app://'):] if uri.startswith('lockbox-app://') else uri


@dataclass
class Target:
    uri: str
    identity: str
    name: str
    password: bool
    backend: object
    reference: object
    pid: int

    def fill(self, value, field):
        if field == 'password' and not self.password:
            raise NativeError('Capture a password field before filling a password.')
        if field != 'password' and self.password:
            raise NativeError('Capture a username or code field for this value.')
        self.backend.fill(self, value)


def reject_browser(identity):
    # Browser pages require extension origin checks; process identity alone cannot authorize a website.
    name = Path(identity).name.lower()
    if any(part in name for part in ('firefox', 'chrome', 'chromium', 'msedge', 'brave', 'vivaldi', 'safari', 'opera', 'librewolf', 'zen-browser')):
        raise NativeError('Use the browser extension to fill websites.')
    if re.fullmatch(r'(?:pythonw?[0-9.]*|node(?:js)?|javaw?|ruby[0-9.]*|perl|bash|zsh|fish|sh|pwsh|powershell|dotnet|electron)(?:\.exe)?',name):
        raise NativeError('Use a packaged application with its own executable identity; shared interpreters cannot be linked.')


class Linux:
    def __init__(self):
        try:
            import gi
            gi.require_version('Atspi', '2.0')
            from gi.repository import Atspi,GLib
            self.api = Atspi; self.context=GLib.MainContext.default()
            Atspi.init()
            Atspi.set_timeout(1500,3000)
        except (ImportError, ValueError) as error:
            raise NativeError('Install PyGObject and AT-SPI 2 support for native application filling.') from error

    @staticmethod
    def identity(pid):
        path = Path('/proc') / str(pid)
        if path.stat().st_uid != os.getuid():
            raise NativeError('The application must run as your desktop user.')
        return str((path / 'exe').resolve(strict=True))

    def capture(self):
        A = self.api
        for _ in range(1000):
            if not self.context.pending():break
            self.context.iteration(False)
        desktop = A.get_desktop(0)
        remaining = [10000]

        def focused(node, depth=0):
            if not node or depth > 40 or remaining[0] <= 0:
                return None
            remaining[0] -= 1
            try:
                state = node.get_state_set()
                if state.contains(A.StateType.DEFUNCT): return None
                if state.contains(A.StateType.FOCUSED): return node
                for i in range(node.get_child_count()):
                    found = focused(node.get_child_at_index(i), depth+1)
                    if found: return found
            except Exception:
                return None
            return None

        for i in range(desktop.get_child_count()):
            application = desktop.get_child_at_index(i)
            if application.get_process_id() == os.getpid(): continue
            node = focused(application)
            if node:
                pid = node.get_process_id()
                identity = self.identity(pid); reject_browser(identity)
                self.editable(node)
                return Target(app_uri('linux', identity), identity, application.get_name() or Path(identity).name,
                    node.get_role() == A.Role.PASSWORD_TEXT, self, node, pid)
        raise NativeError('Focus an editable field in an application with accessibility support, then capture again.')

    def editable(self, node):
        A = self.api
        # clear_cache is available on older LTS AT-SPI releases too. Refresh
        # before checking visibility/editability so stale state cannot authorize filling.
        node.clear_cache()
        state = node.get_state_set()
        if state.contains(A.StateType.DEFUNCT) or not all(state.contains(s) for s in (A.StateType.EDITABLE, A.StateType.ENABLED, A.StateType.SHOWING)):
            raise NativeError('The captured field is no longer visible and editable. Capture it again.')
        interface = node.get_editable_text_iface()
        if interface is None: raise NativeError('This application does not expose an editable accessibility field.')
        return interface

    def fill(self, target, value):
        try:
            if target.reference.get_process_id() != target.pid or self.identity(target.pid) != target.identity:
                raise NativeError('The application changed. Capture its field again.')
            if (target.reference.get_role() == self.api.Role.PASSWORD_TEXT) != target.password:
                raise NativeError('The field changed. Capture it again.')
            if not self.editable(target.reference).set_text_contents(value):
                raise NativeError('The application rejected filling this field.')
        except NativeError: raise
        except Exception as error: raise NativeError('The captured application field is unavailable. Capture it again.') from error


class Windows:
    def __init__(self):
        try:
            import comtypes.client
            self.types = comtypes.client.GetModule('UIAutomationCore.dll')
            self.automation = comtypes.client.CreateObject(self.types.CUIAutomation,interface=self.types.IUIAutomation)
        except (ImportError, OSError) as error:
            raise NativeError('Install comtypes for Windows accessibility filling.') from error

    @staticmethod
    def identity(pid):
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle: raise NativeError('The application process is unavailable.')
        try:
            text = ctypes.create_unicode_buffer(32768); size = wintypes.DWORD(len(text))
            if not kernel.QueryFullProcessImageNameW(handle, 0, text, ctypes.byref(size)):
                raise NativeError('The application identity could not be verified.')
            return os.path.normcase(text.value)
        finally: kernel.CloseHandle(handle)

    def editable(self, node):
        if not node.CurrentIsEnabled or node.CurrentIsOffscreen:
            raise NativeError('The captured field is no longer visible and enabled. Capture it again.')
        # Some Win32 accessibility providers retain stale UIA visibility flags.
        # When a native window exists, also ask Windows about that exact window.
        handle = node.CurrentNativeWindowHandle
        if handle:
            import ctypes
            from ctypes import wintypes
            user = ctypes.WinDLL('user32', use_last_error=True)
            user.IsWindowVisible.argtypes = [wintypes.HWND]
            user.IsWindowVisible.restype = wintypes.BOOL
            user.IsWindowEnabled.argtypes = [wintypes.HWND]
            user.IsWindowEnabled.restype = wintypes.BOOL
            if not user.IsWindowVisible(handle) or not user.IsWindowEnabled(handle):
                raise NativeError('The captured field is no longer visible and enabled. Capture it again.')
        try:
            pattern = node.GetCurrentPattern(10002).QueryInterface(self.types.IUIAutomationValuePattern)
            if pattern.CurrentIsReadOnly: raise NativeError('The captured field is read-only.')
            return pattern
        except NativeError: raise
        except Exception as error: raise NativeError('This application does not support filling this field through UI Automation.') from error

    def capture(self):
        node = self.automation.GetFocusedElement()
        pid = node.CurrentProcessId
        if pid == os.getpid(): raise NativeError('Focus a field in the application you want to fill.')
        identity = self.identity(pid); reject_browser(identity); self.editable(node)
        return Target(app_uri('windows',identity),identity,Path(identity).name,bool(node.CurrentIsPassword),self,node,pid)

    def fill(self, target, value):
        try:
            node = target.reference
            if node.CurrentProcessId != target.pid or self.identity(target.pid) != target.identity or bool(node.CurrentIsPassword) != target.password:
                raise NativeError('The application or field changed. Capture it again.')
            self.editable(node).SetValue(value)
        except NativeError: raise
        except Exception as error: raise NativeError('The captured field is unavailable or rejected filling. Capture it again.') from error


class Mac:
    def __init__(self):
        try:
            import ApplicationServices as AX
            from AppKit import NSRunningApplication
            self.api = AX; self.running = NSRunningApplication
        except ImportError as error:
            raise NativeError('Install PyObjC ApplicationServices and Cocoa support for macOS filling.') from error

    def value(self, node, attribute):
        error, value = self.api.AXUIElementCopyAttributeValue(node, attribute, None)
        if error: raise NativeError('The application does not expose the requested accessibility field.')
        return value

    def identity(self, pid):
        app = self.running.runningApplicationWithProcessIdentifier_(pid)
        if not app: raise NativeError('The application process is unavailable.')
        url = app.executableURL()
        if not url: raise NativeError('The application executable could not be verified.')
        try:
            path = Path(str(url.path()))
            if not path.is_absolute(): raise ValueError('Relative executable path')
            identity = str(path.resolve(strict=True))
        except (OSError, ValueError) as error:
            raise NativeError('The application executable could not be verified.') from error
        # A bundle identifier is a declaration, not a unique executable identity.
        # Checking the actual executable also rejects Python.app and other
        # shared interpreters even when they have a non-generic bundle ID.
        reject_browser(identity)
        return identity

    def editable(self, node):
        A = self.api
        if not self.value(node, A.kAXEnabledAttribute):
            raise NativeError('The captured field is disabled. Capture an enabled field again.')
        error, editable = A.AXUIElementIsAttributeSettable(node, A.kAXValueAttribute, None)
        if error or not editable: raise NativeError('This application does not allow filling this field through Accessibility.')
        role = self.value(node, A.kAXRoleAttribute)
        if role not in (A.kAXTextFieldRole, A.kAXTextAreaRole):
            raise NativeError('Capture a text or password field in the application.')

    def capture(self):
        A = self.api
        if not A.AXIsProcessTrustedWithOptions({A.kAXTrustedCheckOptionPrompt: True}):
            raise NativeError('Enable Credlet in System Settings → Privacy & Security → Accessibility, then capture again.')
        node = self.value(A.AXUIElementCreateSystemWide(), A.kAXFocusedUIElementAttribute)
        error, pid = A.AXUIElementGetPid(node, None)
        if error or pid == os.getpid(): raise NativeError('Focus a field in the application you want to fill.')
        identity = self.identity(pid); reject_browser(identity); self.editable(node)
        try: password = self.value(node, A.kAXSubroleAttribute) == A.kAXSecureTextFieldSubrole
        except NativeError: password = False
        return Target(app_uri('macos',identity),identity,Path(identity).name,password,self,node,pid)

    def fill(self, target, value):
        A = self.api
        error, pid = A.AXUIElementGetPid(target.reference, None)
        if error or pid != target.pid or self.identity(pid) != target.identity:
            raise NativeError('The application changed. Capture its field again.')
        self.editable(target.reference)
        try: password = self.value(target.reference,A.kAXSubroleAttribute) == A.kAXSecureTextFieldSubrole
        except NativeError: password = False
        if password != target.password: raise NativeError('The field changed. Capture it again.')
        if A.AXUIElementSetAttributeValue(target.reference,A.kAXValueAttribute,value):
            raise NativeError('The application rejected filling the captured field.')


def backend():
    if sys.platform == 'linux': return Linux()
    if sys.platform == 'win32': return Windows()
    if sys.platform == 'darwin': return Mac()
    raise NativeError('Native filling is supported on Linux, Windows and macOS.')
