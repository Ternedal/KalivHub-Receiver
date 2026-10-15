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
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from kalivhub_mirror_server import (
    CastSender, MAX_DISPLAY_UNITS, MirrorProtocol, build_handler,
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
        self.assertEqual(self.queue.get_nowait(), "Hej fra Kaliv")
        self.assertEqual(self.proto.accept(body, ts, sig), (409, "duplicate"))

    def test_invalid_auth_does_not_enqueue(self):
        body, ts, sig = signed_payload()
        self.assertEqual(self.proto.accept(body, ts, "v1=" + "0"*64)[0], 401)
        self.assertEqual(self.proto.accept(body, str(int(ts)-600), sig)[0], 401)
        self.assertTrue(self.queue.empty())

    def test_forged_message_is_rejected(self):
        body, ts, sig = signed_payload()
        altered = body.replace(b"Hej fra Kaliv", b"Snyd")
        self.assertEqual(self.proto.accept(altered, ts, sig)[0], 401)

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

    def test_queue_overflow_is_not_marked_replay(self):
        body, ts, sig = signed_payload(text="first")
        self.assertEqual(self.proto.accept(body, ts, sig)[0], 202)
        body2, ts2, sig2 = signed_payload(text="second")
        self.assertEqual(self.proto.accept(body2, ts2, sig2)[0], 503)
        self.queue.get_nowait()
        self.assertEqual(self.proto.accept(body2, ts2, sig2)[0], 202)

    def test_private_ips_only(self):
        self.assertTrue(private_lan_ipv4("192.168.1.13"))
        self.assertTrue(private_lan_ipv4("10.0.0.3"))
        self.assertTrue(private_lan_ipv4("100.100.1.2"))
        for bad in ("0.0.0.0", "127.0.0.1", "8.8.8.8",
                    "169.254.2.4", "kaliv.example.org", "::1", "224.0.0.1"):
            with self.subTest(bad=bad):
                self.assertFalse(private_lan_ipv4(bad))

    def test_cast_sender_orders_display_without_model_call(self):
        recorded = []
        sender = CastSender("192.168.1.13", "E975D483")
        sender.send = lambda payload: recorded.append(payload)
        sender.show_answer("Hej")
        self.assertEqual([msg["type"] for msg in recorded],
                         ["SET_STATE", "SHOW_MESSAGE", "SET_STATE"])
        self.assertEqual(recorded[1]["text"], "Hej")


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.events = queue.Queue(maxsize=4)
        self.server = ThreadingHTTPServer(
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

    def test_health_does_not_claim_cast_ready(self):
        code, payload = self.request("GET", "/healthz")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(payload)["status"], "accepting")

    def test_signed_post_and_replay(self):
        body, ts, sig = signed_payload("Hej!")
        headers = {
            "Content-Type": "application/json",
            "X-Kaliv-Timestamp": ts,
            "X-Kaliv-Signature": sig,
        }
        code, _ = self.request("POST", "/v1/events", body, headers)
        self.assertEqual(code, 202)
        self.assertEqual(self.events.get_nowait(), "Hej!")
        code, _ = self.request("POST", "/v1/events", body, headers)
        self.assertEqual(code, 409)

    def test_missing_auth_and_bad_endpoint(self):
        body, _, _ = signed_payload()
        self.assertEqual(self.request("POST", "/v1/events", body,
                         {"Content-Type": "application/json"})[0], 401)
        self.assertEqual(self.request("POST", "/other", body)[0], 404)


if __name__ == "__main__":
    unittest.main()
