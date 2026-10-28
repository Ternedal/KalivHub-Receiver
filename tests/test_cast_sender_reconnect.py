"""CastSender launch, reconnect, backoff and state resync, without a Nest Hub.

A fake PyChromecast stands in for the Hub: one running app at a time, and a
Kaliv receiver that answers exactly as protocol/kaliv-display-v1.json says
(acks come from test_kaliv_display_contract.contract_ack). No network.
"""
import contextlib
import io
import queue
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

from kalivhub_mirror_server import (  # noqa: E402
    CastSender, CastUnavailable, PendingReply, ReceiverGone, _display_worker_loop,
)
from test_kaliv_display_contract import contract_ack  # noqa: E402

APP = "KALIVAPP"
OTHER = "OTHERAPP"


class FakeHub:
    """The device: which app runs, what the Kaliv receiver shows, what it got."""

    def __init__(self, app_id=None):
        self.app_id = app_id
        self.reachable = True
        self.casts = []
        self.launches = []
        self.received = []
        self.state = "idle"
        self.message = None
        self.lose = lambda message: False  # message never arrives, no ACK
        self.after_receive = lambda message: None

    def launch(self, app_id):
        self.app_id = app_id
        self.launches.append(app_id)
        self.state, self.message = "idle", None  # a fresh receiver starts idle

    def deliver(self, message, controller):
        if self.app_id != controller.supporting_app_id:
            # Real PyChromecast 14 would silently launch the receiver here.
            raise AssertionError("send_message while the Kaliv receiver is not running")
        if self.lose(message):
            return
        self.received.append(message)
        if message["type"] == "SET_STATE":
            self.state = message["state"]
        elif message["type"] == "SHOW_MESSAGE":
            self.message = message["text"]
        elif message["type"] == "CLEAR_MESSAGE":
            self.message = None
        controller.receive_message(None, contract_ack(message))
        self.after_receive(message)

    def types(self):
        return [m["type"] if m["type"] != "SET_STATE" else m["state"] for m in self.received]


class FakeCast:
    def __init__(self, hub):
        self.hub = hub
        self.socket_client = SimpleNamespace(is_connected=True)
        self.disconnected = False

    @property
    def status(self):
        return SimpleNamespace(app_id=self.hub.app_id)

    def wait(self, timeout):
        if not self.hub.reachable:
            raise TimeoutError("RequestTimeout: wait")

    def register_handler(self, controller):
        controller.cast = self

    def start_app(self, app_id):
        self.hub.launch(app_id)

    def disconnect(self):
        self.disconnected = True


class BaseController:
    def __init__(self, namespace, supporting_app_id=None):
        self.namespace = namespace
        self.supporting_app_id = supporting_app_id
        self.cast = None

    def send_message(self, data):
        if self.cast.disconnected:
            raise ConnectionError("NotConnected")
        self.cast.hub.deliver(data, self)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class SenderTest(unittest.TestCase):
    def setUp(self):
        self.hub = FakeHub()
        self.clock = Clock()

        def from_host(_address):
            cast = FakeCast(self.hub)
            self.hub.casts.append(cast)
            return cast

        patcher = patch.dict(sys.modules, {
            "pychromecast": SimpleNamespace(get_chromecast_from_host=from_host),
            "pychromecast.controllers": SimpleNamespace(BaseController=BaseController),
        })
        patcher.start()
        self.addCleanup(patcher.stop)
        sleeper = patch("kalivhub_mirror_server.time.sleep", return_value=None)
        self.sleep = sleeper.start()
        self.addCleanup(sleeper.stop)
        self.sender = CastSender("192.168.1.50", APP, clock=self.clock)
        self.sender.ack_timeout = 0.05
        self.sender.launch_settle_seconds = 0
        self.out = io.StringIO()
        redirect = contextlib.redirect_stdout(self.out)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)

    def status_lines(self):
        return [line for line in self.out.getvalue().splitlines() if line.startswith("Cast status:")]


class TestLaunchRule(SenderTest):
    def test_new_reply_starts_receiver_and_says_what_it_replaced(self):
        self.hub.app_id = OTHER
        self.sender.show_answer("Hej")
        self.assertEqual(self.hub.launches, [APP])
        self.assertEqual(self.hub.types(), ["thinking", "SHOW_MESSAGE", "idle"])
        self.assertEqual(self.hub.message, "Hej")
        self.assertIn("Cast status: starting Kaliv receiver (Hub app was OTHERAPP)", self.status_lines())

    def test_receiver_already_running_is_not_relaunched(self):
        self.hub.app_id = APP
        self.sender.show_answer("Hej")
        self.sender.show_answer("Igen")
        self.assertEqual(self.hub.launches, [])
        self.assertEqual(len(self.hub.casts), 1, "one session serves both replies")

    def test_receiver_closed_between_replies_comes_back_in_a_fresh_session(self):
        self.sender.show_answer("Første")
        first = self.hub.casts[0]
        self.hub.app_id = OTHER  # someone opened another app on the Hub
        self.sender.show_answer("Anden")
        self.assertEqual(self.hub.launches, [APP, APP])
        self.assertTrue(first.disconnected, "the old session is closed, not reused")
        self.assertEqual(len(self.hub.casts), 2)
        self.assertEqual(self.hub.message, "Anden")

    def test_clear_never_launches_a_receiver_that_is_gone(self):
        self.sender.show_answer("Svar")
        self.hub.app_id = OTHER
        self.assertIs(self.sender.clear_message(), False)
        self.assertEqual(self.hub.launches, [APP])
        self.assertEqual(self.hub.app_id, OTHER, "the other app keeps the screen")
        self.assertNotIn("CLEAR_MESSAGE", self.hub.types())

    def test_idle_reset_never_launches_a_receiver_that_is_gone(self):
        self.hub.app_id = OTHER
        self.assertIs(self.sender.send({"type": "SET_STATE", "state": "idle"}), False)
        self.assertEqual(self.hub.launches, [])
        self.assertFalse(self.sender.needs_state_resync, "a receiver that starts later starts idle")

    def test_reply_is_never_shown_by_a_receiver_relaunched_after_thinking(self):
        def close_after_thinking(message):
            if message.get("state") == "thinking":
                self.hub.app_id = OTHER
        self.hub.after_receive = close_after_thinking
        with self.assertRaises(ReceiverGone):
            self.sender.show_answer("Må ikke dukke op i en ny modtager")
        self.assertEqual(self.hub.launches, [APP])
        self.assertNotIn("SHOW_MESSAGE", self.hub.types())
        self.assertEqual(self.hub.app_id, OTHER)

    def test_lost_socket_starts_a_fresh_session(self):
        self.sender.show_answer("Første")
        first = self.hub.casts[0]
        first.socket_client.is_connected = False
        self.sender.show_answer("Anden")
        self.assertTrue(first.disconnected)
        self.assertEqual(len(self.hub.casts), 2)
        self.assertEqual(self.hub.launches, [APP], "receiver kept running; only the socket was new")
        self.assertIn("Cast status: Cast socket lost; opening a fresh session", self.status_lines())


class TestBackoff(SenderTest):
    def test_unreachable_hub_backs_off_and_is_bounded(self):
        self.hub.reachable = False
        delays = []
        for _ in range(7):
            with self.assertRaises(TimeoutError):
                self.sender.connect()
            delays.append(self.sender.retry_in())
            self.clock.now += self.sender.retry_in()
        self.assertEqual(delays, [0, 2, 4, 8, 16, 30, 30])
        self.assertEqual(len(self.hub.casts), 7)

    def test_backing_off_makes_no_network_attempt(self):
        self.hub.reachable = False
        with self.assertRaises(TimeoutError):
            self.sender.show_answer("Hub slukket")  # first failure + its one retry
        self.assertEqual(len(self.hub.casts), 2)
        with self.assertRaises(CastUnavailable):
            self.sender.show_answer("Lige bagefter")
        self.assertEqual(len(self.hub.casts), 2, "refused without touching the network")
        self.clock.now += 2
        self.hub.reachable = True
        self.sender.show_answer("Hub tilbage")
        self.assertEqual(self.hub.message, "Hub tilbage")
        self.assertEqual((self.sender.failures, self.sender.retry_in()), (0, 0))

    def test_first_failure_keeps_the_single_pre_display_retry(self):
        self.hub.app_id = APP  # no launch pause; only the retry sleeps
        self.hub.reachable = False
        calls = []

        def back_after_one(_seconds):
            calls.append(_seconds)
            self.hub.reachable = True
        self.sleep.side_effect = back_after_one
        self.sender.show_answer("Kommer igennem")
        self.assertEqual(calls, [1])
        self.assertEqual(self.hub.message, "Kommer igennem")

    def test_silent_receiver_is_backed_off_like_an_unreachable_hub(self):
        self.hub.app_id = APP
        self.hub.lose = lambda message: True
        with self.assertRaises(TimeoutError):
            self.sender.show_answer("Ingen svarer")
        with self.assertRaises(CastUnavailable):
            self.sender.show_answer("Prøv ikke igen med det samme")
        self.assertEqual(self.hub.received, [])

    def test_status_lines_show_failures_and_recovery(self):
        self.hub.reachable = False
        with self.assertRaises(TimeoutError):
            self.sender.show_answer("x")
        self.clock.now += 2
        self.hub.reachable = True
        self.sender.show_answer("y")
        lines = self.status_lines()
        self.assertIn("Cast status: unavailable (TimeoutError), 1 failure(s) in a row; one retry now", lines)
        self.assertIn("Cast status: unavailable (TimeoutError), 2 failure(s) in a row; next attempt in 2s", lines)
        self.assertEqual(lines[-1], "Cast status: connected; Kaliv receiver acknowledges")


class TestStateResync(SenderTest):
    def test_lost_idle_reset_is_resent_before_the_next_clear(self):
        self.hub.app_id = APP
        self.hub.lose = lambda message: message.get("state") == "idle"
        self.sender.show_answer("Svar")
        self.assertEqual(self.hub.state, "thinking", "the pill is stuck on THINKING")
        self.assertTrue(self.sender.needs_state_resync)
        self.hub.lose = lambda message: False
        self.assertIs(self.sender.clear_message(), True)
        self.assertEqual(self.hub.types()[-2:], ["idle", "CLEAR_MESSAGE"])
        self.assertEqual((self.hub.state, self.hub.message), ("idle", None))
        self.assertFalse(self.sender.needs_state_resync)
        self.assertEqual(self.hub.types().count("SHOW_MESSAGE"), 1, "the reply itself is never resent")

    def test_abandoned_reply_rests_at_idle_not_thinking(self):
        self.hub.app_id = APP
        self.hub.lose = lambda message: message["type"] == "SHOW_MESSAGE"
        with self.assertRaises(TimeoutError):
            self.sender.show_answer("Tabt ACK")
        self.assertEqual(self.sender.desired_state, "idle")

    def test_confirmed_state_adds_no_extra_message(self):
        self.hub.app_id = APP
        self.sender.show_answer("Svar")
        self.sender.clear_message()
        self.assertEqual(self.hub.types(), ["thinking", "SHOW_MESSAGE", "idle", "CLEAR_MESSAGE"])


class TestWorkerAutoClear(SenderTest):
    def test_auto_clear_leaves_another_app_alone(self):
        pending = queue.Queue()
        stop = threading.Event()
        worker = threading.Thread(target=_display_worker_loop,
                                  args=(pending, self.sender, 0.05, stop), daemon=True)
        worker.start()
        try:
            pending.put(PendingReply("Svar", time.monotonic()))
            pending.join()
            self.hub.app_id = OTHER
            deadline = time.monotonic() + 2
            while "nothing to clear" not in self.out.getvalue() and time.monotonic() < deadline:
                time.sleep(0.01)
        finally:
            stop.set()
            worker.join(timeout=2)
        self.assertIn("Cast receiver no longer running; nothing to clear", self.out.getvalue())
        self.assertEqual(self.hub.launches, [APP])
        self.assertEqual(self.hub.app_id, OTHER)


if __name__ == "__main__":
    unittest.main()
