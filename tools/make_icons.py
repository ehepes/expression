#!/usr/bin/env python3
"""Generate the PWA icons (blue gradient rounded square with a white X).

Pure standard library so it runs anywhere: python3 tools/make_icons.py
"""
import os
import struct
import zlib

TOP = (46, 107, 230)     # #2E6BE6
BOTTOM = (18, 64, 168)   # #1240A8
SS = 3                   # supersampling factor for smooth edges


def inside_rounded_rect(x, y, size, r):
    if x < 0 or y < 0 or x > size or y > size:
        return False
    cx = min(max(x, r), size - r)
    cy = min(max(y, r), size - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def render(size):
    r = size * 0.22
    cx = cy = size / 2.0
    bar_half = size * 0.055
    arm = size * 0.30
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            acc_r = acc_g = acc_b = acc_a = 0
            for sy in range(SS):
                for sx in range(SS):
                    fx = x + (sx + 0.5) / SS
                    fy = y + (sy + 0.5) / SS
                    if not inside_rounded_rect(fx, fy, size, r):
                        continue
                    dx, dy = fx - cx, fy - cy
                    u = (dx + dy) * 0.70710678
                    v = (dx - dy) * 0.70710678
                    on_x = (abs(u) < bar_half and abs(v) < arm) or (
                        abs(v) < bar_half and abs(u) < arm
                    )
                    if on_x:
                        cr, cg, cb = 255, 255, 255
                    else:
                        t = fy / size
                        cr = TOP[0] + (BOTTOM[0] - TOP[0]) * t
                        cg = TOP[1] + (BOTTOM[1] - TOP[1]) * t
                        cb = TOP[2] + (BOTTOM[2] - TOP[2]) * t
                    acc_r += cr
                    acc_g += cg
                    acc_b += cb
                    acc_a += 255
            n = SS * SS
            row += bytes(
                (int(acc_r / n), int(acc_g / n), int(acc_b / n), int(acc_a / n))
            )
        rows.append(bytes(row))
    return rows


def write_png(path, size, rows):
    def chunk(tag, data):
        out = struct.pack(">I", len(data)) + tag + data
        return out + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + row for row in rows)
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


def main():
    out_dir = os.path.join(os.path.dirname(__file__), "..", "icons")
    os.makedirs(out_dir, exist_ok=True)
    for size, name in [(512, "icon-512.png"), (192, "icon-192.png"), (180, "apple-touch-icon.png")]:
        path = os.path.join(out_dir, name)
        write_png(path, size, render(size))
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
