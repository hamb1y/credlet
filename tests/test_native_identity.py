"""Identity boundary tests; these do not emulate macOS Accessibility acceptance."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from desktop.native import Mac, NativeError


class MacIdentityTests(unittest.TestCase):
    @staticmethod
    def adapter(path, bundle='local.fixture'):
        app = SimpleNamespace(bundleIdentifier=lambda: bundle,
            executableURL=lambda: SimpleNamespace(path=lambda: str(path)) if path else None)
        adapter = Mac.__new__(Mac)
        adapter.running = SimpleNamespace(runningApplicationWithProcessIdentifier_=lambda pid: app)
        return adapter

    def test_same_declared_bundle_cannot_authorize_a_different_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = (Path(directory) / name for name in ('First.app', 'Second.app'))
            first.touch(); second.touch()
            self.assertNotEqual(self.adapter(first).identity(1), self.adapter(second).identity(2))
            self.assertEqual(self.adapter(first).identity(1), str(first.resolve()))

    def test_bundle_identifier_does_not_hide_a_shared_interpreter_or_browser(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ('Python', 'python3.14', 'node', 'Google Chrome', 'firefox'):
                with self.subTest(executable=name):
                    path = Path(directory) / name; path.touch()
                    with self.assertRaises(NativeError): self.adapter(path).identity(1)

    def test_symlink_to_a_shared_interpreter_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            python = Path(directory) / 'python'; python.touch()
            disguised = Path(directory) / 'Fixture'
            try: disguised.symlink_to(python)
            except (OSError, NotImplementedError): self.skipTest('This host cannot create a test symlink')
            with self.assertRaises(NativeError): self.adapter(disguised).identity(1)

    def test_missing_or_relative_executable_is_rejected(self):
        for path in (None, 'relative-fixture', '/missing-lockbox-fixture/executable'):
            with self.subTest(path=path), self.assertRaises(NativeError): self.adapter(path).identity(1)


if __name__ == '__main__': unittest.main()
