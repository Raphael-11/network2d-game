"""Entry point: python -m client.run_client --host SERVER_IP [--port 5000] [--transport tcp] [--name alice]"""
import argparse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--transport", choices=["tcp", "udp"], default="tcp")
    ap.add_argument("--host", required=True, help="server IP or hostname")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--name", default=None)
    args = ap.parse_args()

    if args.transport != "tcp":
        raise SystemExit("UDP transport not implemented yet")

    from client.ui import run
    run(args.host, args.port, args.name)


if __name__ == "__main__":
    main()
