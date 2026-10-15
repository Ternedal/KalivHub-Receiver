"""Local, opt-in ModelRig -> Nest Hub Cast bridge. No LAN HTTP server or credentials."""
import argparse
import ipaddress
import json
import time
import urllib.request

NS = "urn:x-cast:com.kalivhub.micprobe"

def extract_answer(payload):
    if not isinstance(payload, dict):
        return ""
    message = payload.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    return payload.get("response", "") if isinstance(payload.get("response"), str) else ""

def main():
    parser = argparse.ArgumentParser(description="Send one local ModelRig chat response to Nest Hub")
    parser.add_argument("--host", required=True, help="Nest Hub private LAN IP")
    parser.add_argument("--app-id", default="E975D483")
    parser.add_argument("--backend", default="http://127.0.0.1:8080/api/v1/chat")
    parser.add_argument("--token-env", default="MODELRIG_DEVICE_TOKEN")
    parser.add_argument("--model", required=True)
    parser.add_argument("--prompt", required=True)
    args = parser.parse_args()
    import os
    from urllib.parse import urlsplit
    host = ipaddress.ip_address(args.host)
    if not host.is_private or host.is_loopback or host.is_link_local:
        parser.error("--host must be a private LAN IP")
    target = urlsplit(args.backend)
    if target.scheme != "http" or target.hostname not in ("127.0.0.1", "localhost") or target.username or target.password or target.fragment or target.query or target.port is None:
        parser.error("--backend must be an HTTP loopback endpoint")
    token = os.environ.get(args.token_env, "")
    if not token:
        parser.error("Missing ModelRig device token in environment variable " + args.token_env)
    import pychromecast
    from pychromecast.controllers import BaseController
    class Display(BaseController):
        def __init__(self):
            super().__init__(NS, supporting_app_id=args.app_id)
        def receive_message(self, _, data):
            if isinstance(data, dict):
                print("RECEIVER:", json.dumps(data, ensure_ascii=False))
            return True
    cast = pychromecast.get_chromecast_from_host((str(host), 8009, None, None, None))
    try:
        cast.wait(timeout=15)
        display = Display()
        cast.register_handler(display)
        if not cast.status or cast.status.app_id != args.app_id:
            cast.start_app(args.app_id)
            time.sleep(4)
        acknowledgements = []
        original_receive = display.receive_message
        def collect(message, data):
            if isinstance(data, dict):
                acknowledgements.append(data)
            return original_receive(message, data)
        display.receive_message = collect
        def send(payload):
            expected = "KALIV_DISPLAY" if payload["type"] == "SHOW_MESSAGE" else "KALIV_STATE"
            display.send_message(payload)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if any(x.get("type") == expected and x.get("result") in ("shown", "updated") for x in acknowledgements):
                    acknowledgements.clear()
                    return
                time.sleep(0.1)
            raise RuntimeError("Missing receiver acknowledgement: " + expected)
        send({"type": "SET_STATE", "state": "thinking"})
        body = json.dumps({"model": args.model, "messages": [{"role": "user", "content": args.prompt}], "stream": False}).encode("utf-8")
        request = urllib.request.Request(args.backend, data=body, headers={"Content-Type": "application/json", "Authorization": "Bearer " + token}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                if response.status != 200:
                    raise RuntimeError("Unexpected ModelRig status")
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise RuntimeError("ModelRig response too large")
            answer = extract_answer(json.loads(raw))
            if not answer.strip():
                raise RuntimeError("ModelRig returned no answer")
            send({"type": "SHOW_MESSAGE", "text": answer[:2000]})
            send({"type": "SET_STATE", "state": "idle"})
            print("ModelRig answer delivered to Cast (check RECEIVER acknowledgement).")
        except Exception as exc:
            send({"type": "SET_STATE", "state": "offline"})
            print("ModelRig request failed:", type(exc).__name__)
            raise SystemExit(1)
    finally:
        cast.disconnect()

if __name__ == "__main__":
    main()
