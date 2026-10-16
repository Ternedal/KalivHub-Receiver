"""Opt-in Kaliv Android -> local Cast display mirror.

An authenticated LAN POST accepts *completed assistant display text only*.
Never forward Android credentials to the receiver. Nothing calls an LLM.
The HTTP service defaults to loopback; exposing it to a LAN requires an
explicit private interface and --allow-lan.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import ipaddress
import json
import os
import queue
import re
import socket
import urllib.error
import urllib.request
import threading
import time
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

NAMESPACE = "urn:x-cast:com.kalivhub.micprobe"
# Allow UTF-16 display text even when Android JSON escapes each unit as \\uXXXX.
MAX_BODY = 16_384
MAX_DISPLAY_UNITS = 2000
SKEW_SECONDS = 60
MAX_CONNECTIONS = 24
READ_TIMEOUT_SECONDS = 5
MAX_PENDING_SECONDS = 30
SUPPORTED_KEYS = frozenset(("version", "type", "event_id", "text"))


def private_lan_ipv4(address: str) -> bool:
    """IP literals only; no public, link-local, unspecified or DNS targets."""
    try:
        ip = ipaddress.IPv4Address(address)
        allowed = (
            ipaddress.IPv4Network("10.0.0.0/8"),
            ipaddress.IPv4Network("172.16.0.0/12"),
            ipaddress.IPv4Network("192.168.0.0/16"),
            ipaddress.IPv4Network("100.64.0.0/10"),  # Tailscale
        )
        return any(ip in network for network in allowed)
    except (ipaddress.AddressValueError, ValueError):
        return False


def auto_lan_bind(cast_host: str) -> str:
    """Choose the rig's egress interface for Cast without sending any packet."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect((cast_host, 9))  # UDP connect sets route; sends no datagram.
        selected = sock.getsockname()[0]
    if not private_lan_ipv4(selected):
        raise ValueError("No private LAN source IP was selected for the Cast host")
    return selected


def utf16_units(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


@dataclass(frozen=True)
class PendingReply:
    text: str
    queued_at: float


class ExpiredReply(Exception):
    """Message is too old to display, even after a Cast reconnection."""


def deliver_pending(sender, item: PendingReply, now: float | None = None) -> bool:
    """Return False for expired replies without sending anything to Cast."""
    deadline = item.queued_at + MAX_PENDING_SECONDS
    current = time.monotonic() if now is None else now
    if current >= deadline:
        return False
    sender.show_answer(item.text, expires_at=deadline)
    return True


class MirrorProtocol:
    """Thread-safe replay protection with bounded memory."""

    def __init__(self, secret: str, events: queue.Queue):
        if len(secret) < 32:
            raise ValueError("Mirror secret must contain at least 32 characters")
        self.secret = secret.encode("utf-8")
        self.events = events
        self.lock = threading.Lock()
        self.seen: dict[str, float] = {}
        self.max_seen = 4096

    def accept(self, raw: bytes, timestamp: str, signature: str, now: float | None = None) -> tuple[int, str]:
        if not raw or len(raw) > MAX_BODY:
            return 413, "invalid_size"
        current = time.time() if now is None else now
        if not timestamp or not re.fullmatch(r"[0-9]{10,11}", timestamp):
            return 401, "unauthorized"
        if abs(int(timestamp) - current) > SKEW_SECONDS:
            return 401, "unauthorized"
        expected = "v1=" + hmac.new(
            self.secret, timestamp.encode("ascii") + b"\n" + raw, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return 401, "unauthorized"
        try:
            obj = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return 400, "invalid_json"
        if not isinstance(obj, dict) or obj.keys() != SUPPORTED_KEYS:
            return 400, "invalid_schema"
        if type(obj["version"]) is not int or obj["version"] != 1 or obj["type"] != "assistant_complete":
            return 400, "invalid_schema"
        text = obj["text"]
        if not isinstance(text, str) or not text.strip():
            return 400, "invalid_text"
        try:
            if utf16_units(text) > MAX_DISPLAY_UNITS:
                return 400, "invalid_text"
        except UnicodeEncodeError:
            return 400, "invalid_text"
        if any(ord(ch) < 32 and ch not in "\r\n\t" for ch in text):
            return 400, "invalid_text"
        event_id = obj["event_id"]
        if not isinstance(event_id, str):
            return 400, "invalid_event_id"
        try:
            if str(uuid.UUID(event_id)) != event_id:
                return 400, "invalid_event_id"
        except ValueError:
            return 400, "invalid_event_id"
        with self.lock:
            for key, expires in list(self.seen.items()):
                if expires <= current:
                    del self.seen[key]
            if event_id in self.seen:
                return 409, "duplicate"
            if len(self.seen) >= self.max_seen:
                return 503, "busy"
            try:
                self.events.put_nowait(PendingReply(text, time.monotonic()))
            except queue.Full:
                return 503, "busy"
            self.seen[event_id] = current + 2 * SKEW_SECONDS
        return 202, "accepted"


def build_handler(protocol: MirrorProtocol):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def setup(self):
            super().setup()
            self.connection.settimeout(READ_TIMEOUT_SECONDS)

        def respond(self, code: int, status: str) -> None:
            body = json.dumps({"status": status}).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path != "/healthz":
                return self.respond(404, "not_found")
            # Healthy HTTP listener != an active/connected Cast session.
            return self.respond(200, "accepting")

        def do_POST(self):
            if self.path != "/v1/events":
                return self.respond(404, "not_found")
            length = self.headers.get("Content-Length", "")
            ctype = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if (
                not length.isdecimal()
                or int(length) <= 0
                or int(length) > MAX_BODY
                or ctype != "application/json"
                or self.headers.get("Transfer-Encoding")
            ):
                return self.respond(413, "invalid_request")
            try:
                raw = self.rfile.read(int(length))
            except (OSError, TimeoutError):
                return self.respond(408, "request_timeout")
            if len(raw) != int(length):
                return self.respond(400, "short_body")
            code, status = protocol.accept(
                raw,
                self.headers.get("X-Kaliv-Timestamp", ""),
                self.headers.get("X-Kaliv-Signature", ""),
            )
            return self.respond(code, status)

        def log_message(self, _format, *args):
            # Never print chat text, URLs containing secrets or request headers.
            pass

    return Handler



class BoundedHttpServer(ThreadingHTTPServer):
    """Bound simultaneous request threads; reject unauthenticated slow clients."""

    daemon_threads = True
    request_queue_size = 16

    def __init__(self, address, handler):
        self._slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        super().__init__(address, handler)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

class CastSender:
    """Single worker owns the Cast connection and sends messages in order."""

    def __init__(self, host: str, app_id: str):
        self.host = host
        self.app_id = app_id
        self.cast = None
        self.controller = None
        self.acks: queue.Queue = queue.Queue(maxsize=64)

    def connect(self):
        import pychromecast
        from pychromecast.controllers import BaseController

        if self.cast is not None:
            return
        cast = pychromecast.get_chromecast_from_host((self.host, 8009, None, None, None))
        try:
            cast.wait(timeout=15)
            inbound = self.acks

            class Controller(BaseController):
                def __init__(self):
                    super().__init__(NAMESPACE, supporting_app_id=self_app_id)

                def receive_message(self, _message, data):
                    if isinstance(data, dict):
                        try:
                            inbound.put_nowait(data)
                        except queue.Full:
                            # Diagnostics may send unsolicited events for hours.
                            # Receiver callbacks must never block or grow memory.
                            try:
                                inbound.get_nowait()
                            except queue.Empty:
                                pass
                            try:
                                inbound.put_nowait(data)
                            except queue.Full:
                                pass
                    return True

            self_app_id = self.app_id
            controller = Controller()
            cast.register_handler(controller)
            if not cast.status or cast.status.app_id != self.app_id:
                cast.start_app(self.app_id)
                time.sleep(3)
            self.cast = cast
            self.controller = controller
        except Exception:
            cast.disconnect()
            raise

    def disconnect(self):
        if self.cast is not None:
            self.cast.disconnect()
        self.cast = None
        self.controller = None

    def send(self, payload: dict) -> None:
        self.connect()
        while True:
            try:
                self.acks.get_nowait()
            except queue.Empty:
                break
        self.controller.send_message(payload)
        expected = "KALIV_DISPLAY" if payload["type"] == "SHOW_MESSAGE" else "KALIV_STATE"
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            try:
                ack = self.acks.get(timeout=min(0.25, max(0.01, deadline - time.monotonic())))
            except queue.Empty:
                continue
            if ack.get("type") != expected:
                continue
            if expected == "KALIV_DISPLAY" and ack.get("length") != utf16_units(payload["text"]):
                continue
            if expected == "KALIV_STATE" and ack.get("state") != payload["state"]:
                continue
            if ack.get("result") in ("shown", "updated"):
                return
        raise TimeoutError("Cast acknowledgement missing")

    def show_answer(self, text: str, expires_at: float | None = None):
        for attempt in range(2):
            if expires_at is not None and time.monotonic() >= expires_at:
                raise ExpiredReply("Display event expired before Cast connection")
            try:
                self.send({"type": "SET_STATE", "state": "thinking"})
                # Connecting a sleeping Nest Hub may be slower than the TTL.
                # Never display old replies after a stalled Cast launch.
                if expires_at is not None and time.monotonic() >= expires_at:
                    raise ExpiredReply("Display event expired while connecting to Cast")
                self.send({"type": "SHOW_MESSAGE", "text": text})
                self.send({"type": "SET_STATE", "state": "idle"})
                return
            except ExpiredReply:
                self.disconnect()
                raise
            except Exception:
                self.disconnect()
                if attempt:
                    raise
                time.sleep(1)


def post_signed_selftest(bind: str, port: int, secret: str) -> int:
    """Send one signed display-only event through the real local HTTP boundary.

    Always bypasses system proxy settings. Never prints the shared secret or
    includes it in a URL. The localhost caller must target the bound interface.
    """
    payload = json.dumps({
        "version": 1,
        "type": "assistant_complete",
        "event_id": str(uuid.uuid4()),
        "text": "KalivHub: forbindelsestest fra riggen",
    }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    signature = "v1=" + hmac.new(
        secret.encode("utf-8"), timestamp.encode("ascii") + b"\n" + payload,
        hashlib.sha256,
    ).hexdigest()
    request = urllib.request.Request(
        f"http://{bind}:{port}/v1/events",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Kaliv-Timestamp": timestamp,
            "X-Kaliv-Signature": signature,
        },
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=5) as response:
        return response.status


def serve(cast_host: str, app_id: str, bind: str, port: int, secret: str,
          startup_test: bool = False):
    pending: queue.Queue = queue.Queue(maxsize=16)
    protocol = MirrorProtocol(secret, pending)
    sender = CastSender(cast_host, app_id)

    def worker():
        while True:
            answer = pending.get()
            try:
                if deliver_pending(sender, answer):
                    print("Cast display acknowledgement received", flush=True)
                else:
                    print("Expired Cast display event discarded", flush=True)
            except ExpiredReply:
                print("Expired Cast display event discarded", flush=True)
            except Exception as exc:
                # Chat itself is not affected by Cast network failures.
                print("Cast mirror failed:", type(exc).__name__, flush=True)
            finally:
                pending.task_done()

    BoundedHttpServer.allow_reuse_address = True
    server = BoundedHttpServer((bind, port), build_handler(protocol))
    threading.Thread(target=worker, name="kalivhub-cast", daemon=True).start()
    print(f"KalivHub mirror listening on {bind}:{port} (Cast {cast_host}); opt-in only", flush=True)
    if startup_test:
        def run_self_test():
            # The socket is already bound; allow serve_forever to accept.
            time.sleep(0.2)
            try:
                status = post_signed_selftest(bind, port, secret)
                if status == 202:
                    print("Startup HTTP self-test queued; check Nest Hub display / Cast ACK", flush=True)
                else:
                    print(f"Startup HTTP self-test returned unexpected status {status}", flush=True)
            except (urllib.error.URLError, OSError) as exc:
                print("Startup HTTP self-test failed:", type(exc).__name__, flush=True)

        threading.Thread(target=run_self_test, name="kalivhub-smoke",
                         daemon=True).start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        sender.disconnect()


def main():
    parser = argparse.ArgumentParser(description="Opt-in authenticated Android chat mirror to Nest Hub")
    parser.add_argument("--cast-host", required=True, help="Private IPv4 address of Nest Hub")
    parser.add_argument("--app-id", default="E975D483")
    parser.add_argument("--bind", default="127.0.0.1", help="Exact local interface, never 0.0.0.0")
    parser.add_argument("--auto-bind", action="store_true", help="Resolve the private interface used to reach the Cast device; requires --allow-lan")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--allow-lan", action="store_true", help="Explicitly permit binding private LAN interface")
    parser.add_argument("--secret-env", default="KALIVHUB_MIRROR_SECRET")
    parser.add_argument("--startup-test", action="store_true",
                        help="Explicitly queue one signed HTTP test reply for physical Cast verification")
    args = parser.parse_args()
    if not private_lan_ipv4(args.cast_host):
        parser.error("--cast-host must be a private LAN IPv4 literal")
    if args.auto_bind and args.bind != "127.0.0.1":
        parser.error("--auto-bind and explicit --bind are mutually exclusive")
    if args.auto_bind and not args.allow_lan:
        parser.error("--auto-bind requires --allow-lan")
    try:
        bind_address = auto_lan_bind(args.cast_host) if args.auto_bind else args.bind
    except (OSError, ValueError) as exc:
        parser.error("Cannot resolve a safe private LAN bind address: " + str(exc))
    if bind_address != "127.0.0.1" and not (args.allow_lan and private_lan_ipv4(bind_address)):
        parser.error("LAN bind requires --allow-lan and an exact private IPv4 address")
    if not 0 < args.port < 65536:
        parser.error("--port out of range")
    secret = os.environ.get(args.secret_env, "")
    if len(secret) < 32:
        parser.error(f"Set {args.secret_env} to a random secret of at least 32 characters")
    serve(args.cast_host, args.app_id, bind_address, args.port, secret,
          startup_test=args.startup_test)


if __name__ == "__main__":
    main()
