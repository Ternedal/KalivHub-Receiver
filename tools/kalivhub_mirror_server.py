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
# protocol/kaliv-display-v1.json "states"; tests/test_kaliv_display_contract.py
# keeps the two in step.
DISPLAY_STATES = ("idle", "listening", "thinking", "speaking", "offline", "error")
# After the first failure one immediate retry is free (show_answer's own retry);
# from the second consecutive failure on, wait 2, 4, 8, 16, then 30 s at most.
CONNECT_BACKOFF_CAP_SECONDS = 30.0


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


def reject_duplicate_json_keys(pairs):
    """Reject ambiguous signed JSON objects before accepting display text."""
    obj = {}
    for name, value in pairs:
        if name in obj:
            raise ValueError("duplicate JSON member")
        obj[name] = value
    return obj


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
        # compare_digest(str, str) raises TypeError for non-ASCII input.
        # Untrusted HTTP headers must never terminate a request worker.
        if (not isinstance(signature, str)
                or not re.fullmatch(r"v1=[0-9a-f]{64}", signature)):
            return 401, "unauthorized"
        expected = "v1=" + hmac.new(
            self.secret, timestamp.encode("ascii") + b"\n" + raw, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return 401, "unauthorized"
        # An authenticated event may have waited in transport before arrival.
        # Honor its signed creation time, not merely when it entered the queue.
        signed_age = max(0.0, current - int(timestamp))
        if signed_age >= MAX_PENDING_SECONDS:
            return 410, "expired"
        try:
            obj = json.loads(raw.decode("utf-8"),
                             object_pairs_hook=reject_duplicate_json_keys)
        except (UnicodeDecodeError, ValueError, RecursionError):
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
                self.events.put_nowait(
                    PendingReply(text, time.monotonic() - signed_age)
                )
            except queue.Full:
                return 503, "busy"
            self.seen[event_id] = current + 2 * SKEW_SECONDS
        return 202, "accepted"


def read_signed_body(reader, connection, byte_count: int, timeout_seconds: float,
                     clock=time.monotonic) -> bytes:
    """Read one complete bounded payload within one absolute clock deadline."""
    deadline = clock() + timeout_seconds
    remaining = byte_count
    pieces = []
    while remaining:
        seconds = deadline - clock()
        if seconds <= 0:
            raise TimeoutError("request body deadline expired")
        connection.settimeout(seconds)
        part = reader.read1(min(remaining, 4096))
        if not part:
            raise EOFError("short request body")
        pieces.append(part)
        remaining -= len(part)
    return b"".join(pieces)


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
            # Reject ambiguous framing or authentication. BaseHTTPRequestHandler
            # otherwise exposes the first value of duplicate headers, and
            # proxies/clients can disagree about which one is authoritative.
            for name in ("Content-Length", "Content-Type",
                         "X-Kaliv-Timestamp", "X-Kaliv-Signature"):
                if len(self.headers.get_all(name, [])) != 1:
                    return self.respond(400, "invalid_headers")
            if self.headers.get_all("Transfer-Encoding", []):
                return self.respond(400, "invalid_headers")
            length = self.headers.get("Content-Length", "")
            ctype = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if (
                not re.fullmatch(r"[0-9]{1,5}", length)
                or int(length) <= 0
                or int(length) > MAX_BODY
                or ctype != "application/json"
            ):
                return self.respond(413, "invalid_request")
            # Whole-body deadline, not an inactivity timeout. Slow trickle
            # clients cannot occupy authenticated HTTP threads indefinitely.
            try:
                raw = read_signed_body(self.rfile, self.connection,
                                       int(length), READ_TIMEOUT_SECONDS)
            except EOFError:
                return self.respond(400, "short_body")
            except (OSError, TimeoutError):
                return self.respond(408, "request_timeout")
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

class CastUnavailable(ConnectionError):
    """No Cast attempt was made: the sender is backing off after failures."""


class ReceiverGone(ConnectionError):
    """The Kaliv receiver stopped between THINKING and the reply; nothing was shown."""


class CastSender:
    """Single worker owns the Cast connection and sends messages in order.

    Launch rule: only the start of a new reply (a SET_STATE other than idle)
    may start the Kaliv receiver on the Hub. Returning to idle or clearing
    never does: if the receiver is no longer running, nothing of ours is on
    the screen. PyChromecast 14 would otherwise launch the receiver implicitly
    on any send_message, which could take the Hub away from another app just
    to clear a message that is no longer visible.
    """

    def __init__(self, host: str, app_id: str,
                 require_correlated_acks: bool = False, clock=None):
        self.host = host
        self.app_id = app_id
        self.require_correlated_acks = require_correlated_acks
        self.cast = None
        self.controller = None
        self.acks: queue.Queue = queue.Queue(maxsize=64)
        self.correlated_acks = False
        self.ack_timeout = 6.0
        self.launch_settle_seconds = 3.0
        self._clock = clock
        self.failures = 0
        self._retry_at = 0.0
        self._session_had_receiver = False
        # The state we want the Hub to show, and whether this receiver has
        # acknowledged it. Unconfirmed after a lost SET_STATE; the next CLEAR
        # re-sends it before clearing. SHOW_MESSAGE is never re-sent.
        self.desired_state: str | None = None
        self.state_confirmed = True
        self.status_key: str | None = None

    def _now(self) -> float:
        return (self._clock or time.monotonic)()

    def retry_in(self) -> float:
        """Seconds until the next connection attempt is allowed (0: now)."""
        if not self.failures or not self._retry_at:
            return 0.0
        return max(0.0, self._retry_at - self._now())

    @property
    def needs_state_resync(self) -> bool:
        return self.desired_state is not None and not self.state_confirmed

    def _report(self, key: str, text: str) -> None:
        """One observable line per change; every failure is its own line."""
        if key == self.status_key and key != "unavailable":
            return
        self.status_key = key
        print("Cast status:", text, flush=True)

    def _record_failure(self, kind: str) -> None:
        self.failures += 1
        delay = 0.0 if self.failures <= 1 else min(
            CONNECT_BACKOFF_CAP_SECONDS, float(2 ** (self.failures - 1)))
        self._retry_at = self._now() + delay if delay else 0.0
        when = f"next attempt in {delay:.0f}s" if delay else "one retry now"
        self._report("unavailable", f"unavailable ({kind}), {self.failures} failure(s) in a row; {when}")

    def _record_success(self) -> None:
        self._session_had_receiver = True
        if self.failures or self.status_key != "connected":
            self._report("connected", "connected; Kaliv receiver acknowledges")
        self.failures = 0
        self._retry_at = 0.0

    def _running_app(self) -> str | None:
        status = getattr(self.cast, "status", None)
        return getattr(status, "app_id", None) if status is not None else None

    def _transport_alive(self) -> bool:
        client = getattr(self.cast, "socket_client", None)
        return bool(getattr(client, "is_connected", True))

    def connect(self):
        """Open the Cast socket and register the Kaliv channel. Never launches."""
        if self.cast is not None:
            return
        wait = self.retry_in()
        if wait > 0:
            raise CastUnavailable(
                f"Cast backing off {wait:.0f}s after {self.failures} failures")
        cast = None
        try:
            import pychromecast
            from pychromecast.controllers import BaseController

            cast = pychromecast.get_chromecast_from_host((self.host, 8009, None, None, None))
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
            # PyChromecast 14 exposes registration via socket_client;
            # other releases also forward it from Chromecast itself.
            # Accommodate both rather than fail to start the bridge.
            register = getattr(cast, "register_handler", None)
            if not callable(register):
                register = cast.socket_client.register_handler
            register(controller)
            self.cast = cast
            self.controller = controller
        except Exception as exc:
            # PyChromecast's disconnect can itself fail after a broken socket.
            # Never replace the original launch/register error with cleanup.
            if cast is not None:
                try:
                    cast.disconnect()
                except Exception:
                    pass
            self._record_failure(type(exc).__name__)
            raise

    def _launch_receiver(self, previous_app: str | None) -> None:
        self._report("launching", f"starting Kaliv receiver (Hub app was {previous_app or 'none'})")
        try:
            self.cast.start_app(self.app_id)
        except Exception as exc:
            self._record_failure(type(exc).__name__)
            raise
        # The receiver page needs a moment before its message listener runs.
        time.sleep(self.launch_settle_seconds)

    def disconnect(self):
        # Reset the transport *before* disconnecting its socket: callbacks
        # from an older Cast session must not satisfy a new session's ACKs.
        cast = self.cast
        self.cast = None
        self.controller = None
        self.correlated_acks = False
        self._session_had_receiver = False
        self.acks = queue.Queue(maxsize=64)
        if cast is not None:
            try:
                cast.disconnect()
            except Exception:
                # Never mask the original Cast delivery/retry failure.
                pass

    @staticmethod
    def _expectation(payload: dict):
        """The ACK that completes ``payload``; ValueError before any network."""
        command = payload.get("type")
        if command == "SHOW_MESSAGE":
            def matching(ack):
                return ack.get("length") == utf16_units(payload["text"])
            return "KALIV_DISPLAY", "shown", matching
        if command == "SET_STATE":
            def matching(ack):
                return ack.get("state") == payload["state"]
            return "KALIV_STATE", "updated", matching
        if command == "CLEAR_MESSAGE":
            return "KALIV_DISPLAY", "cleared", lambda ack: True
        raise ValueError("Unsupported Cast display command")

    def send(self, payload: dict) -> bool:
        """Send one display command and wait for its ACK.

        Returns False only when the Kaliv receiver is not running and the
        command was idle/clear: there is nothing of ours to reset, and the
        launch rule (class docstring) forbids starting the receiver for it.
        """
        # Reject unknown commands without launching a Cast app or opening a
        # network connection.
        self._expectation(payload)
        command = payload["type"]
        may_launch = command == "SET_STATE" and payload.get("state") != "idle"
        self.connect()
        if self.cast is not None and not self._transport_alive():
            # PyChromecast lost the socket. Start over rather than reuse a
            # session whose callbacks could belong to the old receiver.
            self._report("reconnecting", "Cast socket lost; opening a fresh session")
            self.disconnect()
            self.connect()
        if self.cast is not None:
            running = self._running_app()
            if running != self.app_id:
                if command == "SHOW_MESSAGE":
                    # Never relaunch between THINKING and the reply: the new
                    # receiver would show it without the turn that led to it.
                    raise ReceiverGone("Kaliv receiver stopped before the reply; not shown")
                if not may_launch:
                    if command == "SET_STATE":
                        # A receiver that starts later starts idle.
                        self.desired_state, self.state_confirmed = "idle", True
                    self._report("receiver_absent",
                                 f"Kaliv receiver not running (Hub app {running or 'none'}); nothing to reset")
                    return False
                if self._session_had_receiver:
                    # Our receiver was closed during this session: fresh session.
                    self.disconnect()
                    self.connect()
                    running = self._running_app()
                if running != self.app_id:
                    self._launch_receiver(running)
        if command == "CLEAR_MESSAGE" and self.needs_state_resync:
            # The last SET_STATE was lost (e.g. the idle reset after a reply).
            # Re-send it first so the Hub does not keep saying "Kaliv tænker…".
            self._transmit({"type": "SET_STATE", "state": self.desired_state})
        self._transmit(payload)
        return True

    def _transmit(self, payload: dict) -> None:
        expected_type, expected_result, matching = self._expectation(payload)
        is_state = payload["type"] == "SET_STATE"
        if is_state and payload["state"] in DISPLAY_STATES:
            self.desired_state, self.state_confirmed = payload["state"], False
        while True:
            try:
                self.acks.get_nowait()
            except queue.Empty:
                break
        # The deployed legacy receiver does not echo command IDs. The new
        # receiver does; once observed, never downgrade the process back to
        # accepting ambiguous legacy ACKs.
        request_id = uuid.uuid4().hex
        try:
            self.controller.send_message({**payload, "request_id": request_id})
        except Exception as exc:
            self._record_failure(type(exc).__name__)
            raise
        deadline = time.monotonic() + self.ack_timeout
        while time.monotonic() < deadline:
            try:
                ack = self.acks.get(timeout=min(0.25, max(0.01, deadline - time.monotonic())))
            except queue.Empty:
                continue
            ack_id = ack.get("request_id")
            # Unsolicited diagnostics and stale messages may carry an ID.
            # Enable strict correlation only when the receiver proves it
            # can echo our *current* command. Do not trust arbitrary IDs.
            if (ack_id == request_id
                    and ack.get("type") == expected_type
                    and ack.get("result") == expected_result and matching(ack)):
                self.correlated_acks = True
            if (self.require_correlated_acks or self.correlated_acks) and ack_id != request_id:
                continue
            if ack_id is not None and ack_id != request_id:
                continue
            if (ack.get("type") == expected_type
                    and ack.get("result") == expected_result and matching(ack)):
                if is_state and payload["state"] == self.desired_state:
                    self.state_confirmed = True
                self._record_success()
                return
        # A receiver that never answers is backed off like an unreachable Hub.
        self._record_failure("ack_timeout")
        raise TimeoutError("Cast acknowledgement missing")

    def clear_message(self) -> bool:
        """Use the receiver's existing CLEAR_MESSAGE command and require ACK.

        False: the receiver is no longer running, so nothing was on screen.
        """
        return self.send({"type": "CLEAR_MESSAGE"})

    def _settle_on_idle(self) -> None:
        """After an abandoned reply the Hub should rest at idle, not THINKING."""
        if not (self.desired_state == "idle" and self.state_confirmed):
            self.desired_state, self.state_confirmed = "idle", False

    def show_answer(self, text: str, expires_at: float | None = None):
        """Attempt SHOW_MESSAGE at most once per completed reply.

        A lost Cast ACK cannot distinguish "not shown" from "shown but
        acknowledgement lost". Never resend the answer after SHOW_MESSAGE was
        attempted: that could replay a private response or flash old content.
        A transient failure *before* display may be retried once.
        """
        try:
            self._show_answer(text, expires_at)
        except Exception:
            self._settle_on_idle()
            raise

    def _show_answer(self, text: str, expires_at: float | None):
        for attempt in range(2):
            if expires_at is not None and time.monotonic() >= expires_at:
                raise ExpiredReply("Display event expired before Cast connection")
            display_attempted = False
            try:
                self.send({"type": "SET_STATE", "state": "thinking"})
                # Connecting a sleeping Nest Hub may be slower than the TTL.
                # Never display old replies after a stalled Cast launch.
                # Reserve the full SHOW_MESSAGE ACK window. A message that
                # would almost certainly complete after the 30-second display
                # deadline is safer dropped than shown late.
                if expires_at is not None and time.monotonic() + self.ack_timeout >= expires_at:
                    raise ExpiredReply("Display event too close to expiry for Cast ACK")
                display_attempted = True
                self.send({"type": "SHOW_MESSAGE", "text": text})
                # The reply is already acknowledged as displayed. A failed IDLE
                # ACK must never trigger another SHOW_MESSAGE.
                try:
                    self.send({"type": "SET_STATE", "state": "idle"})
                except Exception as exc:
                    self.disconnect()
                    print("Cast idle state reset failed:", type(exc).__name__,
                          flush=True)
                return
            except ExpiredReply:
                # If we already displayed THINKING, try to reset the receiver
                # before disconnecting. Otherwise an expired answer can leave
                # the Hub saying "Kaliv tænker…" indefinitely.
                if self.cast is not None and self.controller is not None:
                    try:
                        self.send({"type": "SET_STATE", "state": "idle"})
                    except Exception:
                        pass
                self.disconnect()
                raise
            except CastUnavailable:
                # Backing off: nothing was sent, and a retry now would only be
                # refused again.
                self.disconnect()
                raise
            except Exception:
                # The show command could have reached the screen even when its
                # ACK was lost. Never send this reply twice on the same turn.
                if display_attempted and self.cast is not None and self.controller is not None:
                    try:
                        self.send({"type": "SET_STATE", "state": "idle"})
                    except Exception:
                        pass
                self.disconnect()
                if display_attempted or attempt:
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


def _display_worker_loop(pending: queue.Queue, sender, clear_after_seconds: float = 0,
                         stop_event: threading.Event | None = None):
    """One owner for Cast: serialized output and optional no-race auto-clear.

    stop_event supports deterministic offline tests; the production daemon
    remains blocking when auto-clear is disabled.
    """
    clear_at = None
    while stop_event is None or not stop_event.is_set():
        wait = None if clear_at is None else max(0.0, clear_at - time.monotonic())
        if stop_event is not None:
            wait = 0.05 if wait is None else min(wait, 0.05)
        try:
            answer = pending.get(timeout=wait) if wait is not None else pending.get()
        except queue.Empty:
            if clear_at is None or time.monotonic() < clear_at:
                continue
            try:
                if sender.clear_message() is False:
                    print("Cast receiver no longer running; nothing to clear", flush=True)
                else:
                    print("Expired display cleared on Cast", flush=True)
            except Exception as exc:
                sender.disconnect()
                print("Cast display clear failed:", type(exc).__name__, flush=True)
            finally:
                clear_at = None
            continue
        try:
            if deliver_pending(sender, answer):
                print("Cast display acknowledgement received", flush=True)
                clear_at = (time.monotonic() + clear_after_seconds
                            if clear_after_seconds else None)
            else:
                print("Expired Cast display event discarded", flush=True)
        except ExpiredReply:
            print("Expired Cast display event discarded", flush=True)
        except Exception as exc:
            print("Cast mirror failed:", type(exc).__name__, flush=True)
        finally:
            pending.task_done()


def display_worker(pending: queue.Queue, sender, clear_after_seconds: float = 0,
                   stop_event: threading.Event | None = None):
    """Only the display worker may disconnect its Cast transport.

    Shutting down the HTTP listener from another thread must not concurrently
    close a socket in the middle of a Cast command.
    """
    try:
        _display_worker_loop(pending, sender, clear_after_seconds, stop_event)
    finally:
        sender.disconnect()


def serve(cast_host: str, app_id: str, bind: str, port: int, secret: str,
          startup_test: bool = False, clear_after_seconds: int = 0,
          require_correlated_acks: bool = False):
    pending: queue.Queue = queue.Queue(maxsize=16)
    protocol = MirrorProtocol(secret, pending)
    sender = CastSender(cast_host, app_id,
                        require_correlated_acks=require_correlated_acks)

    BoundedHttpServer.allow_reuse_address = True
    server = BoundedHttpServer((bind, port), build_handler(protocol))
    worker_stop = threading.Event()
    worker_thread = threading.Thread(
        target=display_worker,
        args=(pending, sender, clear_after_seconds, worker_stop),
        name="kalivhub-cast", daemon=True,
    )
    worker_thread.start()
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
        worker_stop.set()
        # Cast belongs solely to the worker. Never disconnect it concurrently
        # from the HTTP/main thread, even when a Cast request is still pending.
        worker_thread.join(timeout=8)
        if worker_thread.is_alive():
            print("Cast worker still finishing shutdown; process exit will close sockets", flush=True)


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
    parser.add_argument("--clear-after", type=int, default=0, metavar="SECONDS",
                        help="Optional time to clear a displayed reply; 0 disables (default)")
    parser.add_argument("--strict-acks", action="store_true",
                        help="Require per-command request_id on all Cast ACKs; incompatible with older deployed receiver")
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
    if not 0 <= args.clear_after <= 3600:
        parser.error("--clear-after must be between 0 and 3600 seconds")
    serve(args.cast_host, args.app_id, bind_address, args.port, secret,
          startup_test=args.startup_test, clear_after_seconds=args.clear_after,
          require_correlated_acks=args.strict_acks)


if __name__ == "__main__":
    main()
