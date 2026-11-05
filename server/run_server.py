"""Entry point: python -m server.run_server --transport tcp|udp --port N"""
import argparse

from common.timing import high_res_timer
from server.server_core import Server


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--transport", choices=["tcp", "udp"], required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--host", default="")
    args = ap.parse_args()

    if args.transport == "tcp":
        from server.transport_tcp import TCPTransport
        transport = TCPTransport(args.port, args.host)
    else:
        raise SystemExit("UDP transport not implemented yet")

    print("Brawl Arena server (%s) listening on port %d" % (args.transport, args.port))
    high_res_timer()
    Server(transport).run()


if __name__ == "__main__":
    main()
