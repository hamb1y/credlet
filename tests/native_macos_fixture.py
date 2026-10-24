#!/usr/bin/env python3
"""Owned Cocoa text fields for real macOS Accessibility acceptance.

Build as CredletFixture.app with bundle ID local.credlet.fixture. Private IPC
only focuses, inspects and changes the availability of these fixture controls;
it provides no command for writing a vault value.
"""
import json
import os
from pathlib import Path
import sys


def main():
    if sys.platform != 'darwin': raise RuntimeError('This fixture requires macOS')
    from AppKit import (NSApplication, NSApplicationActivationPolicyRegular,
        NSBackingStoreBuffered, NSSecureTextField, NSTextField, NSWindow,
        NSWindowStyleMaskClosable, NSWindowStyleMaskTitled)
    from Foundation import NSBundle, NSObject, NSTimer
    if NSBundle.mainBundle().bundleIdentifier() != 'local.credlet.fixture':
        raise RuntimeError('Run the packaged disposable fixture, not a shared interpreter')
    root = Path(sys.argv[1]).resolve(strict=True)
    if root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077:
        raise RuntimeError('Fixture directory must be private and owned by this user')
    if (root / '.disposable').read_text().strip() != 'credlet-native-macos-fixture':
        raise RuntimeError('Missing fixture marker')
    os.umask(0o077)
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        ((80, 120), (460, 290)), NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
        NSBackingStoreBuffered, False)
    window.setTitle_('Credlet native macOS fixture')
    window.setReleasedWhenClosed_(False)
    controls = {}
    for index, (name, title) in enumerate([('user', 'Fixture username'),
            ('password', 'Fixture password'), ('code', 'Fixture six-digit code')]):
        y = 230 - index * 75
        label = NSTextField.alloc().initWithFrame_(((20, y + 24), (420, 20)))
        label.setStringValue_(title); label.setEditable_(False); label.setSelectable_(False)
        label.setBezeled_(False); label.setDrawsBackground_(False)
        window.contentView().addSubview_(label)
        kind = NSSecureTextField if name == 'password' else NSTextField
        field = kind.alloc().initWithFrame_(((20, y - 4), (420, 26)))
        field.setEditable_(True); field.setSelectable_(True)
        field.setBezeled_(True); field.setDrawsBackground_(True)
        field.setAccessibilityLabel_(title)
        window.contentView().addSubview_(field); controls[name] = field

    def write(name, value):
        temporary = root / (name + '.tmp')
        temporary.write_text(json.dumps(value), encoding='utf-8')
        temporary.replace(root / name)

    def command(name):
        if name.startswith('focus-'):
            field = controls[name.removeprefix('focus-')]
            app.activateIgnoringOtherApps_(True); window.makeKeyAndOrderFront_(None)
            if not window.makeFirstResponder_(field): raise RuntimeError('Fixture field could not take focus')
            return 'focused'
        if name == 'inspect':
            values = {}
            for key, field in controls.items():
                editor = field.currentEditor()
                values[key] = str(editor.string() if editor else field.stringValue())
            return values
        if name in ('hide', 'show'): controls['password'].setHidden_(name == 'hide')
        elif name in ('disable', 'enable'): controls['password'].setEnabled_(name == 'enable')
        elif name in ('readonly', 'writable'): controls['password'].setEditable_(name == 'writable')
        elif name == 'quit': return 'closed'
        else: raise ValueError('Unknown fixture command')
        return name

    class Delegate(NSObject):
        def applicationDidFinishLaunching_(self, notification):
            command('focus-user')
            write('ready.json', {'pid': os.getpid(), 'bundleId': str(NSBundle.mainBundle().bundleIdentifier())})

        def poll_(self, timer):
            path = root / 'request.json'
            if not path.exists(): return
            request = json.loads(path.read_text(encoding='utf-8')); path.unlink()
            try: value = command(request['command'])
            except Exception as error:
                write('response.json', {'id': request['id'], 'ok': False, 'error': str(error)})
                return
            write('response.json', {'id': request['id'], 'ok': True, 'value': value})
            if request['command'] == 'quit': app.terminate_(None)

        def applicationShouldTerminateAfterLastWindowClosed_(self, application):
            return True

    # Cocoa delegates are weakly retained, so keep Python references until run exits.
    delegate = Delegate.alloc().init(); app.setDelegate_(delegate)
    timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        .05, delegate, 'poll:', None, True)
    app.run()
    timer.invalidate()


if __name__ == '__main__': main()
