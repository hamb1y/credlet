"""Mac field-decision regression tests; not a substitute for actual Cocoa acceptance."""
from types import SimpleNamespace
import unittest

from desktop.native import Mac, NativeError, Target


class MacFieldGuardTests(unittest.TestCase):
    @staticmethod
    def fixture():
        state = {'enabled': True, 'role': 'text', 'subrole': 'secure', 'settable': True}
        writes = []
        def attribute(node, name, unused):
            return (0, state[name]) if name in state else (-25205, None)
        adapter = Mac.__new__(Mac)
        adapter.api = SimpleNamespace(kAXEnabledAttribute='enabled', kAXValueAttribute='value',
            kAXRoleAttribute='role', kAXTextFieldRole='text', kAXTextAreaRole='area',
            kAXSubroleAttribute='subrole', kAXSecureTextFieldSubrole='secure',
            AXUIElementCopyAttributeValue=attribute,
            AXUIElementIsAttributeSettable=lambda *args: (0, state['settable']),
            AXUIElementGetPid=lambda *args: (0, 123),
            AXUIElementSetAttributeValue=lambda node, name, value: writes.append(value) or 0)
        adapter.identity = lambda pid: '/owned/CredletFixture'
        target = Target('fixture-uri', '/owned/CredletFixture', 'Fixture', True, adapter, object(), 123)
        return state, writes, target

    def test_disabled_but_settable_field_is_refused(self):
        state, writes, target = self.fixture()
        state['enabled'] = False
        with self.assertRaises(NativeError): target.fill('must-not-fill', 'password')
        self.assertEqual(writes, [])

    def test_enabled_state_is_checked_again_at_fill_time(self):
        state, writes, target = self.fixture()
        target.backend.editable(target.reference)
        state['enabled'] = False
        with self.assertRaises(NativeError): target.fill('must-not-fill', 'password')
        self.assertEqual(writes, [])

    def test_unavailable_enabled_state_is_refused(self):
        state, writes, target = self.fixture()
        del state['enabled']
        with self.assertRaises(NativeError): target.fill('must-not-fill', 'password')
        self.assertEqual(writes, [])

    def test_enabled_field_still_requires_a_writable_text_role(self):
        for role, settable, allowed in [('text', True, True), ('area', True, True),
                ('button', True, False), ('text', False, False)]:
            with self.subTest(role=role, settable=settable):
                state, writes, target = self.fixture()
                state.update(role=role, settable=settable)
                if allowed:
                    target.fill('disposable-fixture-value', 'password')
                    self.assertEqual(writes, ['disposable-fixture-value'])
                else:
                    with self.assertRaises(NativeError): target.fill('must-not-fill', 'password')
                    self.assertEqual(writes, [])


if __name__ == '__main__': unittest.main()
