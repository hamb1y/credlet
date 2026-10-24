#!/usr/bin/env python3
"""Owned Win32 EDIT controls for real Windows UI Automation acceptance.

Freeze this as LockboxFixture.exe, then launch from native_windows.py on the
disposable Windows test desktop. Fixture commands never perform vault filling.
"""
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import sys
import time


def main():
    if sys.platform != 'win32':
        raise RuntimeError('This fixture requires Windows.')
    root = Path(sys.argv[1]).resolve()
    if (root / '.disposable').read_text().strip() != 'lockbox-native-windows-fixture':
        raise RuntimeError('Missing fixture marker.')
    user = C.WinDLL('user32', use_last_error=True)
    kernel = C.WinDLL('kernel32', use_last_error=True)
    result_type = C.c_ssize_t
    callback_type = C.WINFUNCTYPE(result_type, W.HWND, W.UINT, W.WPARAM, W.LPARAM)

    class WindowClass(C.Structure):
        _fields_ = [('style', W.UINT), ('procedure', callback_type),
                    ('class_extra', C.c_int), ('window_extra', C.c_int),
                    ('instance', W.HINSTANCE), ('icon', W.HICON),
                    ('cursor', W.HANDLE), ('background', W.HBRUSH),
                    ('menu', W.LPCWSTR), ('name', W.LPCWSTR)]

    user.DefWindowProcW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
    user.DefWindowProcW.restype = result_type
    user.CreateWindowExW.argtypes = [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD,
        C.c_int, C.c_int, C.c_int, C.c_int, W.HWND, W.HMENU, W.HINSTANCE, W.LPVOID]
    user.CreateWindowExW.restype = W.HWND
    user.RegisterClassW.argtypes = [C.POINTER(WindowClass)]
    user.RegisterClassW.restype = W.ATOM
    user.SetFocus.argtypes = [W.HWND]; user.SetFocus.restype = W.HWND
    user.SetForegroundWindow.argtypes = [W.HWND]
    user.ShowWindow.argtypes = [W.HWND, C.c_int]
    user.EnableWindow.argtypes = [W.HWND, W.BOOL]
    user.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
    user.SendMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
    user.SendMessageW.restype = result_type
    user.SetTimer.argtypes = [W.HWND, C.c_size_t, W.UINT, W.LPVOID]
    user.SetTimer.restype = C.c_size_t
    user.DestroyWindow.argtypes = [W.HWND]
    user.GetMessageW.argtypes = [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT]
    user.DispatchMessageW.argtypes = [C.POINTER(W.MSG)]
    kernel.GetModuleHandleW.argtypes = [W.LPCWSTR]
    kernel.GetModuleHandleW.restype = W.HMODULE
    controls = {}

    def write(name, value):
        temporary = root / (name + '.tmp')
        temporary.write_text(json.dumps(value), encoding='utf-8')
        for attempt in range(100):
            try:
                temporary.replace(root / name)
                return
            except PermissionError:
                if attempt == 99: raise
                time.sleep(.01)

    def command(request):
        name = request['command']
        if name.startswith('focus-'):
            field = name.removeprefix('focus-')
            user.ShowWindow(window, 9)
            user.SetForegroundWindow(window)
            user.SetFocus(controls[field])
            return 'focused'
        if name == 'inspect':
            values = {}
            for name, handle in controls.items():
                value = C.create_unicode_buffer(4096)
                user.GetWindowTextW(handle, value, len(value))
                values[name] = value.value
            return values
        if name in ('hide', 'show', 'disable', 'enable', 'readonly', 'writable'):
            handle = controls['password']
            if name in ('hide', 'show'): user.ShowWindow(handle, 0 if name == 'hide' else 5)
            elif name in ('disable', 'enable'): user.EnableWindow(handle, name == 'enable')
            else: user.SendMessageW(handle, 0xCF, name == 'readonly', 0)  # EM_SETREADONLY
            return name
        if name == 'quit':
            user.DestroyWindow(window)
            return 'closed'
        raise ValueError('Unknown fixture command')

    @callback_type
    def procedure(hwnd, message, wparam, lparam):
        if message == 0x113:  # WM_TIMER; all field operations run on the UI thread.
            path = root / 'request.json'
            if path.exists():
                try:
                    request = json.loads(path.read_text(encoding='utf-8')); path.unlink()
                except (PermissionError, FileNotFoundError):
                    # Windows scanners/readers can briefly hold a file without
                    # delete sharing. Retry next tick before executing anything.
                    return 0
                try:
                    value = command(request)
                    write('response.json', {'id': request['id'], 'ok': True, 'value': value})
                except Exception as error:
                    write('response.json', {'ok': False, 'error': str(error)})
            return 0
        if message == 2:
            user.PostQuitMessage(0)
            return 0
        return user.DefWindowProcW(hwnd, message, wparam, lparam)

    instance = kernel.GetModuleHandleW(None)
    cls = WindowClass(0, procedure, 0, 0, instance, None, None, 6, None, 'LockboxNativeFixture')
    if not user.RegisterClassW(C.byref(cls)): raise C.WinError(C.get_last_error())
    window = user.CreateWindowExW(0, cls.name, 'Lockbox native Windows fixture',
        0xCF0000, 760, 80, 460, 290, None, None, instance, None)
    if not window: raise C.WinError(C.get_last_error())
    for index, (name, label) in enumerate([('user', 'Fixture username'),
            ('password', 'Fixture password'), ('code', 'Fixture six-digit code')]):
        y = 20 + index * 65
        user.CreateWindowExW(0, 'STATIC', label, 0x50000000, 18, y, 380, 20, window, None, instance, None)
        # Native EDIT + ES_PASSWORD. These are actual UIA ValuePattern fields.
        controls[name] = user.CreateWindowExW(0x200, 'EDIT', '',
            0x50810080 | (0x20 if name == 'password' else 0),
            18, y + 22, 400, 26, window, index + 10, instance, None)
        if not controls[name]: raise C.WinError(C.get_last_error())
    user.ShowWindow(window, 5)
    user.SetForegroundWindow(window); user.SetFocus(controls['user'])
    user.SetTimer(window, 1, 40, None)
    write('ready.json', {'pid': os.getpid(), 'window': window, 'controls': controls})
    message = W.MSG()
    while user.GetMessageW(C.byref(message), None, 0, 0) > 0:
        user.TranslateMessage(C.byref(message)); user.DispatchMessageW(C.byref(message))


if __name__ == '__main__':
    main()
