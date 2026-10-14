"""Launch an already registered, isolated Custom Web Receiver on a local Cast device."""
import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-id", required=True, help="Separate diagnostic Cast App ID")
    parser.add_argument("--host", required=True, help="Local Nest Hub IP address")
    args = parser.parse_args()
    if not args.app_id.isalnum() or not 4 <= len(args.app_id) <= 32:
        parser.error("app-id must be 4–32 alphanumeric characters")
    try:
        import pychromecast
    except ImportError:
        print("Install dependency: python -m pip install pychromecast", file=sys.stderr)
        return 2

    cast = None
    browser = None
    try:
        # pychromecast resolves device metadata and opens the local Cast channel.
        cast = pychromecast.Chromecast(args.host)
        cast.wait(timeout=15)
        cast.receiver_controller.launch_app(args.app_id)
        print("Launch requested. Check the Nest Hub screen for the diagnostic receiver.")
        print("A launch request is not proof that the receiver started or that audio works.")
        return 0
    except Exception as exc:
        print(f"Cast launch failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        if cast is not None:
            cast.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
