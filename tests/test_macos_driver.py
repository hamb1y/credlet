"""Frozen-driver refusal logic only; these are not real macOS input tests."""
from types import SimpleNamespace
import unittest

from packaged_macos import Desktop


class MacInputBoundaryTests(unittest.TestCase):
    @staticmethod
    def driver():
        state = {'active': True, 'hitPid': 123, 'hitError': 0}
        posted = []
        driver = Desktop.__new__(Desktop)
        driver.process = SimpleNamespace(pid=123)
        driver.running = SimpleNamespace(isActive=lambda: state['active'])
        driver.verify_process = lambda: None
        driver.activate = lambda: None
        driver.window = lambda: {'bounds': {'X': 20, 'Y': 30, 'Width': 720, 'Height': 680}}
        driver.system = object()
        driver.A = SimpleNamespace(
            AXUIElementCopyElementAtPosition=lambda *args: (state['hitError'], object()),
            AXUIElementGetPid=lambda *args: (0, state['hitPid']))
        driver.Q = SimpleNamespace(kCGWindowBounds='bounds', kCGEventLeftMouseDown=1,
            kCGEventLeftMouseUp=2, kCGMouseButtonLeft=0, kCGMouseEventClickState=1,
            CGEventCreateMouseEvent=lambda *args: object(),
            CGEventSetIntegerValueField=lambda *args: None,
            CGEventCreateKeyboardEvent=lambda *args: object(),
            CGEventSetFlags=lambda *args: None,
            CGEventPostToPid=lambda pid, event: posted.append(pid))
        layout = {'frameSize': [720, 680], 'contentOffset': [0, 30]}
        return driver, state, posted, layout

    def test_click_is_refused_when_another_process_covers_the_coordinates(self):
        driver, state, posted, layout = self.driver()
        state['hitPid'] = 456
        with self.assertRaises(AssertionError): driver.click([20, 20, 100, 30], layout)
        self.assertEqual(posted, [])

    def test_unavailable_hit_identity_is_refused(self):
        driver, state, posted, layout = self.driver()
        state['hitError'] = -25204
        with self.assertRaises(AssertionError): driver.click([20, 20, 100, 30], layout)
        self.assertEqual(posted, [])

    def test_changed_geometry_is_refused_before_posting(self):
        driver, _, posted, layout = self.driver()
        layout['frameSize'] = [800, 680]
        with self.assertRaises(AssertionError): driver.click([20, 20, 100, 30], layout)
        self.assertEqual(posted, [])

    def test_keyboard_input_requires_the_owned_application_to_be_active(self):
        driver, state, posted, _ = self.driver()
        state['active'] = False
        with self.assertRaises(AssertionError): driver.key(0)
        self.assertEqual(posted, [])

    def test_activation_is_checked_again_between_keyboard_events(self):
        driver, state, posted, _ = self.driver()
        def post(pid, event):
            posted.append(pid)
            state['active'] = False
        driver.Q.CGEventPostToPid = post
        with self.assertRaises(AssertionError): driver.key(0)
        self.assertEqual(posted, [123])


if __name__ == '__main__': unittest.main()
