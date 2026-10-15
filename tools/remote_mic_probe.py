"""Send explicit Cast mic diagnostic commands; never transfers audio."""
import argparse
import ipaddress
import json
import time

NS = "urn:x-cast:com.kalivhub.micprobe"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", required=True)
    p.add_argument("--app-id", default="E975D483")
    p.add_argument("--command", choices=("GET_STATUS", "GET_DEVICES", "START_MIC_TEST", "STOP_MIC_TEST"), default="START_MIC_TEST")
    args = p.parse_args()
    addr = ipaddress.ip_address(args.host)
    if not (addr.is_private and not addr.is_loopback and not addr.is_link_local):
        p.error("Use a private LAN IP address")
    import pychromecast
    from pychromecast.controllers import BaseController

    class MicProbeController(BaseController):
        def __init__(self):
            super().__init__(NS, supporting_app_id=args.app_id)
        def receive_message(self, _message, data):
            if isinstance(data, dict):
                print("RECEIVER:", json.dumps(data, ensure_ascii=False), flush=True)
            return True

    cast = pychromecast.get_chromecast_from_host((str(addr), 8009, None, None, None))
    try:
        cast.wait(timeout=15)
        ctrl = MicProbeController()
        cast.register_handler(ctrl)
        if not cast.status or cast.status.app_id != args.app_id:
            cast.start_app(args.app_id)
            time.sleep(3)
        print("Sender", args.command, "til", addr, flush=True)
        ctrl.send_message({"type": args.command})
        time.sleep(13 if args.command == "START_MIC_TEST" else 4)
        print("Cast app:", cast.status.app_id if cast.status else "unknown", flush=True)
        print("Ingen respons betyder ikke, at mikrofonen virker.", flush=True)
    finally:
        cast.disconnect()


if __name__ == "__main__":
    main()
