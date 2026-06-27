#!/usr/bin/env python3
"""Generate a QR code pointing at the SandTable viewer webapp.

Run this once (on the Pi, or anywhere) to produce a PNG you can print and
stick next to the table. It does not need the OctoPrint API key — it just
encodes a URL.

Usage
-----
    python qr.py                              # -> qr.png for http://sandtable.local:8099
    python qr.py --host 192.168.1.53 --port 8099
    python qr.py --url http://sandtable.local:8099 --out label.png
"""
from __future__ import annotations

import argparse

import qrcode


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate a QR code for the SandTable viewer.")
    ap.add_argument("--host", default="sandtable.local", help="hostname or IP of the viewer service")
    ap.add_argument("--port", type=int, default=8099, help="viewer service port")
    ap.add_argument("--url", help="full URL to encode (overrides --host/--port)")
    ap.add_argument("--out", default="qr.png", help="output PNG path")
    args = ap.parse_args(argv)

    url = args.url or f"http://{args.host}:{args.port}"

    qr = qrcode.QRCode(border=2)
    qr.add_data(url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="#1b1712", back_color="#f3e9d2")
    img.save(args.out)

    print(f"URL:   {url}")
    print(f"Saved: {args.out}")
    try:
        qr.print_ascii(invert=True)
    except UnicodeEncodeError:
        pass  # terminal can't render the block characters (e.g. Windows cp1252); PNG is still saved


if __name__ == "__main__":
    main()
