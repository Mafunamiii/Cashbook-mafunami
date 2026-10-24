#!/usr/bin/env python3
"""Read-only staging probe for a connection held across a Caddy route switch."""
import argparse
import http.client
import sys


def request(connection):
    connection.request("GET", "/", headers={"Host": "stage.namicash.invalid"})
    response = connection.getresponse()
    response.read()
    if response.status != 200:
        raise RuntimeError(f"gateway returned HTTP {response.status}")
    return response.getheader("X-Nami-Route")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", choices=("blue", "green"), default="blue")
    parser.add_argument("--after", choices=("blue", "green"), default="green")
    args = parser.parse_args()
    conn = http.client.HTTPConnection("127.0.0.1", 18091, timeout=8)
    first = request(conn)
    if first != args.before:
        raise RuntimeError(f"initial route is {first}, expected {args.before}")
    print(f"Initial staging route: {first}. Promote in another terminal, then press Enter.")
    input()
    try:
        held = request(conn)
        reused = True
    except (OSError, http.client.HTTPException):
        conn.close()
        conn = http.client.HTTPConnection("127.0.0.1", 18091, timeout=8)
        held = request(conn)
        reused = False
    conn.close()
    if held not in (args.before, args.after):
        raise RuntimeError(f"unexpected held connection route: {held}")
    fresh = http.client.HTTPConnection("127.0.0.1", 18091, timeout=8)
    try:
        current = request(fresh)
    finally:
        fresh.close()
    if current != args.after:
        raise RuntimeError(f"fresh connection still routes to {current}, expected {args.after}")
    print(f"Held connection: {held} ({'reused' if reused else 'reconnected'}); fresh connection: {current}")
    if held == args.before and reused:
        print("Keep the previous environment running until old connections drain.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, EOFError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
