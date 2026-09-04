#!/usr/bin/env python3
import argparse
import json
import socket

from stage10_protocol import DEFAULT_HOST, DEFAULT_PORT, decode_line


def main():
    parser = argparse.ArgumentParser(description="Print Stage 10 publisher JSON packets.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--count", type=int, default=5)
    args = parser.parse_args()
    with socket.create_connection((args.host, args.port), timeout=10.0) as sock:
        with sock.makefile("rb") as reader:
            for idx, raw in enumerate(reader):
                packet = decode_line(raw)
                print(json.dumps(packet, indent=2, sort_keys=True))
                if args.count and idx + 1 >= args.count:
                    break


if __name__ == "__main__":
    main()
