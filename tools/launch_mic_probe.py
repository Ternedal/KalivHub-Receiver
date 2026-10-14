"""Launch an already registered, isolated Custom Web Receiver on a local Cast device."""
import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-id", required=True, help="Separate diagnostic Cast App ID")
    parser.add_argument("--host", required=True, help="Local Nest Hub IP address")
    parser.add_argument("--dry-run", action="store_true", help="Validate arguments without connecting")
    args = parser.parse_args()
    import ipaddress
    try:
        host_ip = ipaddress.ip_address(args.host)
    except ValueError:
        parser.error("host must be a local IP address")
    lan_ranges = (
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("fc00::/7"),
    )
    if not any(host_ip in network for network in lan_ranges):
        parser.error("host must be an RFC1918 IPv4 or ULA IPv6 address")
    if not args.app_id.isalnum() or not 4 <= len(args.app_id) <= 32:
        parser.error("app-id must be 4–32 alphanumeric characters")
    if args.dry_run:
        print(f"VALID: diagnostic App ID {args.app_id}; private LAN target {host_ip}")
        print("No Cast connection attempted.")
        return 0
    try:
        import pychromecast
    except ImportError:
        print("Install dependency: python -m pip install pychromecast", file=sys.stderr)
        return 2

    cast = None
    try:
        # pychromecast resolves device metadata and opens the local Cast channel.
        cast = pychromecast.get_chromecast_from_host((str(host_ip), 8009, None, None, None))
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
