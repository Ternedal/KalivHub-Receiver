"""Offline tests for the opt-in Cast diagnostic launcher."""
import contextlib
import io
import sys
import types
import unittest
from unittest.mock import patch

from tools.launch_mic_probe import main


class LauncherTests(unittest.TestCase):
    def invoke(self, args, cast_module=None):
        out, err = io.StringIO(), io.StringIO()
        modules = {"pychromecast": cast_module} if cast_module is not None else {}
        with patch.object(sys, "argv", ["launch_mic_probe.py", *args]), \
             patch.dict(sys.modules, modules), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            return main(), out.getvalue(), err.getvalue()

    def test_invalid_app_id_fails_before_network(self):
        with self.assertRaises(SystemExit) as raised:
            self.invoke(["--host", "192.0.2.10", "--app-id", "bad-id"])
        self.assertEqual(raised.exception.code, 2)

    def test_launch_and_disconnect(self):
        state = []
        class Receiver:
            def launch_app(self, app_id):
                state.append(("launch", app_id))
        class Cast:
            receiver_controller = Receiver()
            def __init__(self, host):
                state.append(("connect", host))
            def wait(self, timeout):
                state.append(("wait", timeout))
            def disconnect(self):
                state.append(("disconnect",))
        code, out, err = self.invoke(
            ["--host", "192.0.2.10", "--app-id", "ABCD1234"],
            types.SimpleNamespace(Chromecast=Cast),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("Launch requested", out)
        self.assertEqual(state, [
            ("connect", "192.0.2.10"), ("wait", 15),
            ("launch", "ABCD1234"), ("disconnect",),
        ])

    def test_disconnect_after_launch_error(self):
        state = []
        class Receiver:
            def launch_app(self, app_id):
                raise RuntimeError("cast unavailable")
        class Cast:
            receiver_controller = Receiver()
            def __init__(self, host):
                pass
            def wait(self, timeout):
                pass
            def disconnect(self):
                state.append("disconnect")
        code, _, err = self.invoke(
            ["--host", "192.0.2.10", "--app-id", "ABCD1234"],
            types.SimpleNamespace(Chromecast=Cast),
        )
        self.assertEqual(code, 1)
        self.assertIn("Cast launch failed", err)
        self.assertEqual(state, ["disconnect"])


if __name__ == "__main__":
    unittest.main()
