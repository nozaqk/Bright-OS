#!/usr/bin/env python3
"""Diagnostic for the QEMU boot smoke test.

Asks a running QEMU (monitor on a unix socket) for a screendump, then converts
the PPM to PNG so the CI artifact shows what the screen displayed.

Usage: qemu_screendump.py MONITOR_SOCKET PPM_OUT PNG_OUT
"""
import re
import socket
import struct
import sys
import time
import zlib


def drain(sock):
    buf = b""
    try:
        while not buf.rstrip().endswith(b"(qemu)"):
            data = sock.recv(65536)
            if not data:
                break
            buf += data
    except socket.timeout:
        pass
    return buf


def chunk(tag, body):
    crc = zlib.crc32(tag + body) & 0xFFFFFFFF
    return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", crc)


def read_vga_text(mon):
    """Read the 80x25 text buffer at physical 0xB8000 through the monitor.

    Returns 25 lines, or None if the monitor did not answer as expected.
    Only meaningful while the VGA card is in text mode (BIOS/GRUB text menu).
    """
    sock = socket.socket(socket.AF_UNIX)
    sock.settimeout(10)
    try:
        sock.connect(mon)
        drain(sock)
        sock.sendall(b"xp /4000b 0xb8000\n")
        out = drain(sock).decode(errors="replace")
    except OSError:
        return None
    finally:
        sock.close()
    raw = []
    for line in out.splitlines():
        m = re.match(r"^[0-9a-fA-F]+:\s+((?:0x[0-9a-fA-F]{2}\s*)+)", line)
        if m:
            raw.extend(int(v, 16) for v in m.group(1).split())
    if len(raw) < 4000:
        return None
    chars = raw[0:4000:2]
    rows = []
    for r in range(25):
        row = chars[r * 80:(r + 1) * 80]
        rows.append("".join(chr(c) if 32 <= c < 127 else " " for c in row).rstrip())
    return rows


def main():
    mon, ppm, png = sys.argv[1], sys.argv[2], sys.argv[3]
    sock = socket.socket(socket.AF_UNIX)
    sock.settimeout(10)
    sock.connect(mon)
    drain(sock)
    sock.sendall(("screendump " + ppm + "\n").encode())
    drain(sock)
    time.sleep(1)
    sock.close()

    text = read_vga_text(mon)
    if text:
        print("VGA text buffer (80x25, text mode only):")
        for line in text:
            print("| " + line)

    data = open(ppm, "rb").read()
    m = re.match(rb"P6\s+(\d+)\s+(\d+)\s+255\s", data)
    if not m:
        raise SystemExit("unexpected PPM header")
    w, h = int(m.group(1)), int(m.group(2))
    pixels = data[m.end():m.end() + w * h * 3]
    rows = b"".join(b"\x00" + pixels[y * w * 3:(y + 1) * w * 3] for y in range(h))
    out = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(rows))
           + chunk(b"IEND", b""))
    open(png, "wb").write(out)
    print("screendump written:", png, f"{w}x{h}")


if __name__ == "__main__":
    main()
