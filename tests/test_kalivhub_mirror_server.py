"""Unit and HTTP boundary tests for the opt-in local mirror, no Nest Hub needed."""
import hashlib
import hmac
import http.client
import json
from pathlib import Path
import queue
import sys
import threading
import time
import unittest
import uuid
from unittest.mock import Mock, patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from kalivhub_mirror_server import (
    BoundedHttpServer, CastSender, ExpiredReply, MAX_BODY, MAX_CONNECTIONS, MAX_DISPLAY_UNITS,
    MAX_PENDING_SECONDS, MirrorProtocol, PendingReply, deliver_pending,
    auto_lan_bind, build_handler, display_worker, post_signed_selftest,
    private_lan_ipv4, utf16_units,
)

SECRET = "s" * 40


def signed_payload(text="Hej fra Kaliv", ident=None, timestamp=None):
    body = json.dumps({
        "version": 1,
        "type": "assistant_complete",
        "event_id": ident or str(uuid.uuid4()),
        "text": text,
    }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ts = timestamp or str(int(time.time()))
    signature = "v1=" + hmac.new(
        SECRET.encode(), ts.encode("ascii") + b"\n" + body, hashlib.sha256
    ).hexdigest()
    return body, ts, signature


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.queue = queue.Queue(maxsize=1)
        self.proto = MirrorProtocol(SECRET, self.queue)

    def test_hmac_accepts_once(self):
        body, ts, sig = signed_payload()
        self.assertEqual(self.proto.accept(body, ts, sig), (202, "accepted"))
        self.assertEqual(self.queue.get_nowait().text, "Hej fra Kaliv")
        self.assertEqual(self.proto.accept(body, ts, sig), (409, "duplicate"))

    def test_android_kotlin_hmac_interoperability_vector(self):
        # Same vector as HubMirrorClientTest.kt; catches protocol drift.
        body = (
            '{"version":1,"type":"assistant_complete",'
            '"event_id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","text":"Hej"}'
        ).encode()
        ts = "1700000000"
        signature = "v1=" + hmac.new(
            SECRET.encode(), ts.encode() + b"\n" + body, hashlib.sha256
        ).hexdigest()
        self.assertEqual(
            signature,
            "v1=2bbcd5f9211630bd07c02821477a3f78739305216d244c0d9d18b4ad06a6866e"
        )
        self.assertEqual(
            self.proto.accept(body, ts, signature, now=1700000000),
            (202, "accepted"),
        )

    def test_invalid_auth_does_not_enqueue(self):
        body, ts, sig = signed_payload()
        self.assertEqual(self.proto.accept(body, ts, "v1=" + "0"*64)[0], 401)
        self.assertEqual(self.proto.accept(body, str(int(ts)-600), sig)[0], 401)
        self.assertTrue(self.queue.empty())

    def test_untrusted_signature_header_never_crashes_hmac_comparison(self):
        body, ts, valid = signed_payload()
        for malformed in (
            "v1=é", "v1=" + "a" * 63, "v1=" + "A" * 64,
            "v1=" + "g" * 64, "v2=" + "a" * 64,
            "v1=" + "a" * 65, "", None,
        ):
            with self.subTest(signature=repr(malformed)):
                self.assertEqual(
                    self.proto.accept(body, ts, malformed),
                    (401, "unauthorized"),
                )
                self.assertTrue(self.queue.empty())
        self.assertEqual(
            self.proto.accept(body, ts, valid),
            (202, "accepted"),
        )

    def test_forged_message_is_rejected(self):
        body, ts, sig = signed_payload()
        altered = body.replace(b"Hej fra Kaliv", b"Snyd")
        self.assertEqual(self.proto.accept(altered, ts, sig)[0], 401)

    def test_duplicate_signed_json_keys_are_rejected(self):
        raw = (
            '{"version":1,"type":"assistant_complete",'
            '"event_id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",'
            '"text":"public","text":"private"}'
        ).encode()
        timestamp = str(int(time.time()))
        sig = "v1=" + hmac.new(
            SECRET.encode(), timestamp.encode() + b"\n" + raw, hashlib.sha256
        ).hexdigest()
        self.assertEqual(
            self.proto.accept(raw, timestamp, sig),
            (400, "invalid_json"),
        )
        self.assertTrue(self.queue.empty())

    def test_excessively_nested_signed_json_does_not_crash_server(self):
        raw = (b"[" * 1500) + b"1" + (b"]" * 1500)
        ts = str(int(time.time()))
        sig = "v1=" + hmac.new(
            SECRET.encode(), ts.encode() + b"\n" + raw, hashlib.sha256
        ).hexdigest()
        self.assertEqual(
            self.proto.accept(raw, ts, sig),
            (400, "invalid_json"),
        )
        self.assertTrue(self.queue.empty())

    def test_bad_schema_after_auth_is_rejected(self):
        body = json.dumps({"version": 1, "type": "assistant_complete", "text": "Hej"}).encode()
        ts = str(int(time.time()))
        sig = "v1=" + hmac.new(SECRET.encode(), ts.encode()+b"\n"+body, hashlib.sha256).hexdigest()
        self.assertEqual(self.proto.accept(body, ts, sig)[0], 400)

    def test_bad_text_and_utf16_boundary(self):
        self.assertEqual(utf16_units("😀"), 2)
        body, ts, sig = signed_payload(text="😀" * (MAX_DISPLAY_UNITS//2+1))
        self.assertEqual(self.proto.accept(body, ts, sig)[0], 400)
        body, ts, sig = signed_payload(text="\x01bad")
        self.assertEqual(self.proto.accept(body, ts, sig)[0], 400)

    def test_malformed_unicode_is_rejected_without_server_crash(self):
        raw = b'{"version":1,"type":"assistant_complete","event_id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","text":"\\uD800"}'
        ts = str(int(time.time()))
        sig = "v1=" + hmac.new(SECRET.encode(), ts.encode() + b"\n" + raw, hashlib.sha256).hexdigest()
        self.assertEqual(self.proto.accept(raw, ts, sig), (400, "invalid_text"))

    def test_replay_cache_limit_is_bounded(self):
        self.proto.max_seen = 1
        first, ts, sig = signed_payload(text="first")
        self.assertEqual(self.proto.accept(first, ts, sig)[0], 202)
        self.queue.get_nowait()
        second, ts2, sig2 = signed_payload(text="second")
        self.assertEqual(self.proto.accept(second, ts2, sig2)[0], 503)
        self.assertEqual(self.proto.accept(first, ts, sig)[0], 409)

    def test_maximum_emoji_reply_fits_even_when_json_escapes_surrogates(self):
        raw = json.dumps({
            "version": 1, "type": "assistant_complete",
            "event_id": str(uuid.uuid4()), "text": "😀" * 1000,
        }, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        self.assertGreater(len(raw), 8192)
        self.assertLess(len(raw), MAX_BODY)
        ts = str(int(time.time()))
        sig = "v1=" + hmac.new(
            SECRET.encode(), ts.encode("ascii") + b"\n" + raw, hashlib.sha256
        ).hexdigest()
        self.assertEqual(self.proto.accept(raw, ts, sig), (202, "accepted"))
        self.assertEqual(self.queue.get_nowait().text, "😀" * 1000)

    def test_body_over_global_limit_is_refused(self):
        self.assertEqual(
            self.proto.accept(b"x" * (MAX_BODY + 1), "1700000000", "bad", now=1700000000),
            (413, "invalid_size"),
        )

    def test_queue_overflow_is_not_marked_replay(self):
        body, ts, sig = signed_payload(text="first")
        self.assertEqual(self.proto.accept(body, ts, sig)[0], 202)
        body2, ts2, sig2 = signed_payload(text="second")
        self.assertEqual(self.proto.accept(body2, ts2, sig2)[0], 503)
        self.queue.get_nowait()
        self.assertEqual(self.proto.accept(body2, ts2, sig2)[0], 202)

    def test_auto_bind_selects_cast_route_without_transmitting(self):
        selected = []
        class Socket:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def connect(self, target):
                selected.append(target)
            def getsockname(self):
                return ("192.168.1.77", 54321)
            def send(self, *args):
                raise AssertionError("Auto-bind must not send datagrams")
        with patch("kalivhub_mirror_server.socket.socket", return_value=Socket()):
            self.assertEqual(auto_lan_bind("192.168.1.13"), "192.168.1.77")
        self.assertEqual(selected, [("192.168.1.13", 9)])

    def test_auto_bind_rejects_non_private_source(self):
        class Socket:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def connect(self, _target):
                pass
            def getsockname(self):
                return ("127.0.0.1", 45678)
        with patch("kalivhub_mirror_server.socket.socket", return_value=Socket()):
            with self.assertRaises(ValueError):
                auto_lan_bind("192.168.1.13")

    def test_private_ips_only(self):
        self.assertTrue(private_lan_ipv4("192.168.1.13"))
        self.assertTrue(private_lan_ipv4("10.0.0.3"))
        self.assertTrue(private_lan_ipv4("100.100.1.2"))
        for bad in ("0.0.0.0", "127.0.0.1", "8.8.8.8",
                    "169.254.2.4", "kaliv.example.org", "::1", "224.0.0.1",
                    "192.0.2.10", "198.18.0.1", "255.255.255.255",
                    "172.32.0.1", "192.168.1.013"):
            with self.subTest(bad=bad):
                self.assertFalse(private_lan_ipv4(bad))

    def test_unsolicited_cast_messages_cannot_grow_without_bound(self):
        class BaseController:
            def __init__(self, _namespace, supporting_app_id=None):
                self.app_id = supporting_app_id

        class FakeCast:
            status = SimpleNamespace(app_id="E975D483")
            def wait(self, timeout):
                self.timeout = timeout
            def register_handler(self, controller):
                self.controller = controller
            def disconnect(self):
                pass

        cast = FakeCast()
        fake_py = SimpleNamespace(
            get_chromecast_from_host=lambda _address: cast,
        )
        fake_controllers = SimpleNamespace(BaseController=BaseController)
        with patch.dict(sys.modules, {
            "pychromecast": fake_py,
            "pychromecast.controllers": fake_controllers,
        }):
            sender = CastSender("192.168.1.13", "E975D483")
            sender.connect()
            for index in range(1000):
                cast.controller.receive_message(None, {"sequence": index})
            self.assertEqual(sender.acks.qsize(), 64)
            remaining = [sender.acks.get_nowait()["sequence"] for _ in range(64)]
            self.assertEqual(remaining[0], 936)
            self.assertEqual(remaining[-1], 999)
            sender.disconnect()

    def test_expired_pending_reply_is_never_displayed(self):
        sender = CastSender("192.168.1.13", "E975D483")
        sent = []
        sender.send = lambda payload: sent.append(payload)
        expired = PendingReply("For gammelt svar", queued_at=1000)
        self.assertFalse(deliver_pending(sender, expired, now=1031))
        self.assertEqual(sent, [])

    def test_live_pending_reply_gets_a_cast_expiry_deadline(self):
        sender = CastSender("192.168.1.13", "E975D483")
        calls = []
        sender.show_answer = lambda text, expires_at=None: calls.append((text, expires_at))
        fresh = PendingReply("Ny besked", queued_at=1000)
        self.assertTrue(deliver_pending(sender, fresh, now=1001))
        self.assertEqual(calls, [("Ny besked", 1000 + MAX_PENDING_SECONDS)])

    def test_cast_connection_cannot_show_expired_message_after_slow_start(self):
        sender = CastSender("192.168.1.13", "E975D483")
        sent = []
        sender.send = lambda payload: sent.append(payload)
        sender.disconnect = lambda: None
        with patch("kalivhub_mirror_server.time.monotonic",
                   side_effect=[1000, 1031]):
            with self.assertRaises(ExpiredReply):
                sender.show_answer("For sent", expires_at=1030)
        self.assertEqual(sent, [{"type": "SET_STATE", "state": "thinking"}])

    def test_expiration_resets_existing_thinking_display_before_disconnect(self):
        sender = CastSender("192.168.1.13", "E975D483")
        sent = []
        disconnected = []
        sender.cast = object()  # Simulates an already launched receiver.
        sender.controller = object()
        sender.send = lambda payload: sent.append(payload)
        sender.disconnect = lambda: disconnected.append(True)
        with patch("kalivhub_mirror_server.time.monotonic",
                   side_effect=[1000, 1031]):
            with self.assertRaises(ExpiredReply):
                sender.show_answer("For sent", expires_at=1030)
        self.assertEqual(sent, [
            {"type": "SET_STATE", "state": "thinking"},
            {"type": "SET_STATE", "state": "idle"},
        ])
        self.assertEqual(disconnected, [True])

    def test_cast_connection_cannot_retry_after_deadline(self):
        sender = CastSender("192.168.1.13", "E975D483")
        sent = []
        sender.send = lambda payload: (
            sent.append(payload),
            (_ for _ in ()).throw(OSError("offline"))
        )
        sender.disconnect = lambda: None
        with patch("kalivhub_mirror_server.time.sleep", return_value=None), (
            patch("kalivhub_mirror_server.time.monotonic", side_effect=[1000, 1031])
        ):
            with self.assertRaises(ExpiredReply):
                sender.show_answer("For sent", expires_at=1030)
        self.assertEqual(len(sent), 1)

    def test_cast_sender_orders_display_without_model_call(self):
        recorded = []
        sender = CastSender("192.168.1.13", "E975D483")
        sender.send = lambda payload: recorded.append(payload)
        sender.show_answer("Hej")
        self.assertEqual([msg["type"] for msg in recorded],
                         ["SET_STATE", "SHOW_MESSAGE", "SET_STATE"])
        self.assertEqual(recorded[1]["text"], "Hej")

    def test_cast_retries_one_transient_transport_failure(self):
        sender = CastSender("192.168.1.13", "E975D483")
        sent = []
        disconnected = []
        def flaky(payload):
            sent.append(payload["type"])
            if payload["type"] == "SHOW_MESSAGE" and sent.count("SHOW_MESSAGE") == 1:
                raise OSError("offline")
        sender.send = flaky
        sender.disconnect = lambda: disconnected.append(True)
        with patch("kalivhub_mirror_server.time.sleep", return_value=None):
            sender.show_answer("Velkommen")
        self.assertEqual(sent, ["SET_STATE", "SHOW_MESSAGE", "SET_STATE",
                                "SHOW_MESSAGE", "SET_STATE"])
        self.assertEqual(disconnected, [True])

    def test_disconnect_resets_per_session_ack_buffer_and_correlation(self):
        sender = CastSender("192.168.1.13", "E975D483")
        original_acks = sender.acks
        disconnected = []
        class FakeCast:
            def disconnect(self):
                disconnected.append(True)
        sender.cast = FakeCast()
        sender.controller = object()
        sender.correlated_acks = True
        original_acks.put({"type": "KALIV_DISPLAY", "result": "shown"})
        sender.disconnect()
        self.assertEqual(disconnected, [True])
        self.assertIsNone(sender.cast)
        self.assertIsNone(sender.controller)
        self.assertFalse(sender.correlated_acks)
        self.assertIsNot(sender.acks, original_acks)
        self.assertTrue(sender.acks.empty())
        self.assertEqual(original_acks.qsize(), 1)

    def test_disconnect_failure_does_not_mask_retry_error(self):
        sender = CastSender("192.168.1.13", "E975D483")
        class BrokenCast:
            def disconnect(self):
                raise OSError("network link already broken")
        sender.cast = BrokenCast()
        sender.correlated_acks = True
        sender.disconnect()
        self.assertIsNone(sender.cast)
        self.assertFalse(sender.correlated_acks)

    def test_matching_id_for_unrelated_ack_is_not_receiver_capability(self):
        sender = CastSender("192.168.1.13", "E975D483")
        sender.connect = lambda: None
        def incoming(payload):
            sender.acks.put({
                "type": "KALIV_DIAGNOSTICS",
                "result": "updated",
                "request_id": payload["request_id"],
            })
            sender.acks.put({
                "type": "KALIV_STATE",
                "result": "updated",
                "state": payload["state"],
            })
        sender.controller = SimpleNamespace(send_message=incoming)
        sender.send({"type": "SET_STATE", "state": "thinking"})
        self.assertFalse(sender.correlated_acks)

    def test_unsolicited_mismatched_id_does_not_claim_correlation(self):
        sender = CastSender("192.168.1.13", "E975D483")
        sender.connect = lambda: None
        def send(payload):
            sender.acks.put({
                "type": "KALIV_DIAGNOSTICS", "result": "updated",
                "request_id": "a" * 32,
            })
            # The current deployed receiver still uses legacy ACKs.
            sender.acks.put({
                "type": "KALIV_STATE", "result": "updated",
                "state": payload["state"],
            })
        sender.controller = SimpleNamespace(send_message=send)
        sender.send({"type": "SET_STATE", "state": "thinking"})
        self.assertFalse(sender.correlated_acks)

    def test_correlated_cast_ack_matches_only_this_command(self):
        sender = CastSender("192.168.1.13", "E975D483")
        sender.connect = lambda: None
        ids = []
        def inbound(payload):
            ids.append(payload["request_id"])
            self.assertEqual(len(payload["request_id"]), 32)
            sender.acks.put({
                "type": "KALIV_STATE", "result": "updated",
                "state": payload["state"],
                "request_id": "0" * 32,
            })
            sender.acks.put({
                "type": "KALIV_STATE", "result": "updated",
                "state": payload["state"],
                "request_id": payload["request_id"],
            })
        sender.controller = SimpleNamespace(send_message=inbound)
        sender.send({"type": "SET_STATE", "state": "thinking"})
        self.assertTrue(sender.correlated_acks)
        self.assertEqual(sender.acks.qsize(), 0)
        sender.send({"type": "SET_STATE", "state": "idle"})
        self.assertNotEqual(ids[0], ids[1])

    def test_correlated_receiver_never_downgrades_to_legacy_ack(self):
        sender = CastSender("192.168.1.13", "E975D483")
        sender.connect = lambda: None
        sender.correlated_acks = True
        def inbound(payload):
            sender.acks.put({
                "type": "KALIV_DISPLAY", "result": "shown",
                "length": len(payload["text"]),
            })
            sender.acks.put({
                "type": "KALIV_DISPLAY", "result": "shown",
                "length": len(payload["text"]),
                "request_id": payload["request_id"],
            })
        sender.controller = SimpleNamespace(send_message=inbound)
        sender.send({"type": "SHOW_MESSAGE", "text": "Hej"})
        self.assertTrue(sender.acks.empty())

    def test_legacy_receiver_ack_still_supported_until_correlation_learned(self):
        sender = CastSender("192.168.1.13", "E975D483")
        sender.connect = lambda: None
        sender.controller = SimpleNamespace(
            send_message=lambda payload: sender.acks.put({
                "type": "KALIV_STATE", "result": "updated",
                "state": payload["state"],
            })
        )
        sender.send({"type": "SET_STATE", "state": "thinking"})
        self.assertFalse(sender.correlated_acks)

    def test_clear_display_uses_existing_receiver_ack(self):
        sender = CastSender("192.168.1.13", "E975D483")
        sender.connect = lambda: None
        observed = []
        def receive(payload):
            observed.append(payload)
            sender.acks.put({
                "type": "KALIV_DISPLAY", "result": "cleared",
            })
        sender.controller = SimpleNamespace(send_message=receive)
        sender.clear_message()
        self.assertEqual(observed, [{"type": "CLEAR_MESSAGE"}])

    def test_wrong_ack_result_cannot_complete_other_display_command(self):
        sender = CastSender("192.168.1.13", "E975D483")
        sender.connect = lambda: None
        def receive(payload):
            # Length alone is not enough: a stale CLEARED result is not SHOWN.
            sender.acks.put({
                "type": "KALIV_DISPLAY", "result": "cleared", "length": 4,
            })
            sender.acks.put({
                "type": "KALIV_DISPLAY", "result": "updated", "length": 4,
            })
            sender.acks.put({
                "type": "KALIV_DISPLAY", "result": "shown", "length": 4,
            })
        sender.controller = SimpleNamespace(send_message=receive)
        sender.send({"type": "SHOW_MESSAGE", "text": "Hej!"})
        self.assertTrue(sender.acks.empty())

    def test_wrong_state_ack_result_cannot_satisfy_cast_command(self):
        sender = CastSender("192.168.1.13", "E975D483")
        sender.connect = lambda: None
        def receive(payload):
            sender.acks.put({
                "type": "KALIV_STATE", "state": "thinking", "result": "shown",
            })
            sender.acks.put({
                "type": "KALIV_STATE", "state": "thinking", "result": "updated",
            })
        sender.controller = SimpleNamespace(send_message=receive)
        sender.send({"type": "SET_STATE", "state": "thinking"})
        self.assertTrue(sender.acks.empty())

    def test_unknown_display_command_is_rejected_before_send(self):
        sender = CastSender("192.168.1.13", "E975D483")
        attempts = []
        sender.connect = lambda: attempts.append("network")
        calls = []
        sender.controller = SimpleNamespace(
            send_message=lambda payload: calls.append(payload)
        )
        with self.assertRaises(ValueError):
            sender.send({"type": "DELETE_ALL_MESSAGES"})
        self.assertEqual(calls, [])
        self.assertEqual(attempts, [])

    def test_cast_ack_type_and_display_length_are_checked(self):
        sender = CastSender("192.168.1.13", "E975D483")
        sender.connect = lambda: None
        def incoming(payload):
            sender.acks.put({"type": "KALIV_STATE", "state": "thinking", "result": "updated"})
            sender.acks.put({"type": "KALIV_DISPLAY", "length": 99, "result": "shown"})
            sender.acks.put({"type": "KALIV_DISPLAY", "length": 4, "result": "shown"})
        sender.controller = SimpleNamespace(send_message=incoming)
        sender.send({"type": "SHOW_MESSAGE", "text": "Hej!"})


class DisplayWorkerTests(unittest.TestCase):
    """Run the real worker with an injected clock-friendly stop signal."""

    def test_optional_auto_clear_is_in_order_and_never_races_new_answer(self):
        events = queue.Queue(maxsize=16)
        stopped = threading.Event()
        cleared = threading.Event()
        shown = []
        clear_calls = []

        class FakeCast:
            def show_answer(self, text, expires_at=None):
                shown.append(text)
            def clear_message(self):
                clear_calls.append(tuple(shown))
                cleared.set()
            def disconnect(self):
                pass

        worker = threading.Thread(
            target=display_worker,
            args=(events, FakeCast(), 0.075),
            kwargs={"stop_event": stopped},
            daemon=True,
        )
        worker.start()
        try:
            events.put(PendingReply("første", time.monotonic()))
            deadline = time.monotonic() + 2
            while len(shown) < 1 and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertEqual(shown, ["første"])
            events.put(PendingReply("anden", time.monotonic()))
            self.assertTrue(cleared.wait(2), "Cast clear deadline was not reached")
            self.assertEqual(shown, ["første", "anden"])
            self.assertEqual(clear_calls, [("første", "anden")])
        finally:
            stopped.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())

    def test_auto_clear_disabled_never_sends_clear(self):
        events = queue.Queue(maxsize=16)
        stopped = threading.Event()
        shown = []
        clear_calls = []
        class FakeCast:
            def show_answer(self, text, expires_at=None):
                shown.append(text)
            def clear_message(self):
                clear_calls.append(True)
            def disconnect(self):
                pass
        worker = threading.Thread(
            target=display_worker,
            args=(events, FakeCast(), 0),
            kwargs={"stop_event": stopped},
            daemon=True,
        )
        worker.start()
        try:
            events.put(PendingReply("bliver stående", time.monotonic()))
            deadline = time.monotonic() + 2
            while not shown and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertEqual(shown, ["bliver stående"])
            time.sleep(0.12)
            self.assertEqual(clear_calls, [])
        finally:
            stopped.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.events = queue.Queue(maxsize=4)
        self.server = BoundedHttpServer(
            ("127.0.0.1", 0),
            build_handler(MirrorProtocol(SECRET, self.events)),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, path, data=None, headers=None):
        client = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            client.request(method, path, data, headers or {})
            response = client.getresponse()
            return response.status, response.read()
        finally:
            client.close()

    def test_connection_limit_rejects_slow_clients_without_spawning_threads(self):
        acquired = 0
        try:
            while self.server._slots.acquire(blocking=False):
                acquired += 1
            self.assertEqual(acquired, MAX_CONNECTIONS)
            stale_socket = Mock()
            with patch.object(self.server, "shutdown_request") as close:
                self.server.process_request(stale_socket, ("127.0.0.1", 5555))
                close.assert_called_once_with(stale_socket)
        finally:
            for _ in range(acquired):
                self.server._slots.release()

    def test_health_does_not_claim_cast_ready(self):
        code, payload = self.request("GET", "/healthz")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(payload)["status"], "accepting")

    def test_non_ascii_signature_http_header_returns_401_without_crash(self):
        body, ts, _ = signed_payload("Hej")
        code, data = self.request("POST", "/v1/events", body, {
            "Content-Type": "application/json",
            "X-Kaliv-Timestamp": ts,
            "X-Kaliv-Signature": "v1=é",
        })
        self.assertEqual(code, 401)
        self.assertEqual(json.loads(data)["status"], "unauthorized")
        self.assertTrue(self.events.empty())

    def test_oversized_numeric_content_length_is_rejected_without_integer_parse(self):
        body, ts, sig = signed_payload()
        client = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=5
        )
        try:
            client.putrequest("POST", "/v1/events")
            client.putheader("Content-Type", "application/json")
            client.putheader("Content-Length", "9" * 5000)
            client.putheader("X-Kaliv-Timestamp", ts)
            client.putheader("X-Kaliv-Signature", sig)
            client.endheaders()
            response = client.getresponse()
            self.assertEqual(response.status, 413)
            self.assertEqual(json.loads(response.read())["status"], "invalid_request")
            self.assertTrue(self.events.empty())
        finally:
            client.close()

    def test_duplicate_security_headers_are_rejected_before_reading_body(self):
        body, ts, sig = signed_payload("Hej")
        required = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
            "X-Kaliv-Timestamp": ts,
            "X-Kaliv-Signature": sig,
        }
        for duplicated in required:
            with self.subTest(header=duplicated):
                client = http.client.HTTPConnection(
                    "127.0.0.1", self.server.server_port, timeout=5
                )
                try:
                    client.putrequest("POST", "/v1/events")
                    for name, value in required.items():
                        client.putheader(name, value)
                        if name == duplicated:
                            client.putheader(name, value)
                    client.endheaders(body)
                    response = client.getresponse()
                    self.assertEqual(response.status, 400)
                    self.assertEqual(json.loads(response.read())["status"], "invalid_headers")
                    self.assertTrue(self.events.empty())
                finally:
                    client.close()

    def test_transfer_encoding_header_is_rejected_with_content_length(self):
        body, ts, sig = signed_payload("Hej")
        client = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=5
        )
        try:
            client.putrequest("POST", "/v1/events")
            client.putheader("Content-Type", "application/json")
            client.putheader("Content-Length", str(len(body)))
            client.putheader("X-Kaliv-Timestamp", ts)
            client.putheader("X-Kaliv-Signature", sig)
            client.putheader("Transfer-Encoding", "chunked")
            client.endheaders(body)
            response = client.getresponse()
            self.assertEqual(response.status, 400)
            self.assertTrue(self.events.empty())
            response.read()
        finally:
            client.close()

    def test_signed_post_and_replay(self):
        body, ts, sig = signed_payload("Hej!")
        headers = {
            "Content-Type": "application/json",
            "X-Kaliv-Timestamp": ts,
            "X-Kaliv-Signature": sig,
        }
        code, _ = self.request("POST", "/v1/events", body, headers)
        self.assertEqual(code, 202)
        self.assertEqual(self.events.get_nowait().text, "Hej!")
        code, _ = self.request("POST", "/v1/events", body, headers)
        self.assertEqual(code, 409)

    def test_slow_partial_body_times_out_and_does_not_queue(self):
        # An unauthenticated LAN client must not hold a handler forever.
        with patch("kalivhub_mirror_server.READ_TIMEOUT_SECONDS", 0.2):
            client = http.client.HTTPConnection(
                "127.0.0.1", self.server.server_port, timeout=3,
            )
            try:
                client.putrequest("POST", "/v1/events")
                client.putheader("Content-Type", "application/json")
                client.putheader("Content-Length", "100")
                client.putheader("X-Kaliv-Timestamp", str(int(time.time())))
                client.putheader("X-Kaliv-Signature", "v1=" + "0" * 64)
                client.endheaders()
                client.send(b"x")
                response = client.getresponse()
                self.assertEqual(response.status, 408)
                response.read()
                self.assertTrue(self.events.empty())
            finally:
                client.close()

    def test_signed_android_event_reaches_mock_cast_without_model_call(self):
        body, ts, signature = signed_payload("Svar fra telefonen")
        code, _ = self.request("POST", "/v1/events", body, {
            "Content-Type": "application/json",
            "X-Kaliv-Timestamp": ts,
            "X-Kaliv-Signature": signature,
        })
        self.assertEqual(code, 202)
        sender = CastSender("192.168.1.13", "E975D483")
        forwarded = []
        sender.send = lambda payload: forwarded.append(payload)
        self.assertTrue(deliver_pending(sender, self.events.get_nowait()))
        self.assertEqual(forwarded, [
            {"type": "SET_STATE", "state": "thinking"},
            {"type": "SHOW_MESSAGE", "text": "Svar fra telefonen"},
            {"type": "SET_STATE", "state": "idle"},
        ])
        self.assertTrue(self.events.empty())

    def test_startup_selftest_crosses_real_signed_http_boundary(self):
        status = post_signed_selftest(
            "127.0.0.1", self.server.server_port, SECRET
        )
        self.assertEqual(status, 202)
        reply = self.events.get_nowait()
        self.assertIsInstance(reply, PendingReply)
        self.assertEqual(reply.text, "KalivHub: forbindelsestest fra riggen")
        self.assertLess(time.monotonic() - reply.queued_at, 5)

    def test_startup_selftest_wrong_key_does_not_queue(self):
        import urllib.error
        with self.assertRaises(urllib.error.HTTPError) as captured:
            post_signed_selftest(
                "127.0.0.1", self.server.server_port, "x" * 40
            )
        self.assertEqual(captured.exception.code, 401)
        self.assertTrue(self.events.empty())

    def test_missing_auth_and_bad_endpoint(self):
        body, _, _ = signed_payload()
        self.assertEqual(self.request("POST", "/v1/events", body,
                         {"Content-Type": "application/json"})[0], 400)
        self.assertEqual(self.request("POST", "/other", body)[0], 404)


if __name__ == "__main__":
    unittest.main()
