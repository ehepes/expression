#!/usr/bin/env python3
"""Generate the PWA icons: blue gradient rounded square with the
Expectation X mark (hollow outlined X with a solid diagonal slash).

Pure standard library so it runs anywhere: python3 tools/make_icons.py
"""
import os
import struct
import zlib

TOP = (46, 107, 230)     # #2E6BE6
BOTTOM = (18, 64, 168)   # #1240A8
SS = 3                   # supersampling factor for smooth edges

# Mark geometry in a 1000x1000 design space (matches icons/icon.svg).
POLY = [
    (242, 320), (320, 242), (500, 422), (624, 298), (702, 376), (578, 500),
    (758, 680), (680, 758), (500, 578), (376, 702), (298, 624), (422, 500),
]
LINE = ((800, 200), (150, 850))
OUTLINE_W = 42
LINE_W = 120
MARK_SCALE = 1.1


def inside_rounded_rect(x, y, size, r):
    if x < 0 or y < 0 or x > size or y > size:
        return False
    cx = min(max(x, r), size - r)
    cy = min(max(y, r), size - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def seg_dist_sq(px, py, ax, ay, bx, by):
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    t = (wx * vx + wy * vy) / (vx * vx + vy * vy)
    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
    dx, dy = px - (ax + t * vx), py - (ay + t * vy)
    return dx * dx + dy * dy


def poly_boundary_dist_sq(x, y):
    best = 1e18
    n = len(POLY)
    for i in range(n):
        ax, ay = POLY[i]
        bx, by = POLY[(i + 1) % n]
        d = seg_dist_sq(x, y, ax, ay, bx, by)
        if d < best:
            best = d
    return best


def point_in_poly(x, y):
    inside = False
    n = len(POLY)
    j = n - 1
    for i in range(n):
        xi, yi = POLY[i]
        xj, yj = POLY[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def render(size):
    r = size * 0.22
    half_outline_sq = (OUTLINE_W / 2.0) ** 2
    half_line_sq = (LINE_W / 2.0) ** 2
    to_design = (1000.0 / size) / MARK_SCALE
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
                    # design-space coordinates of this sample
                    ux = 500.0 + (fx - size / 2.0) * to_design
                    uy = 500.0 + (fy - size / 2.0) * to_design
                    white = poly_boundary_dist_sq(ux, uy) <= half_outline_sq
                    if not white and not point_in_poly(ux, uy):
                        (a, b) = LINE
                        white = seg_dist_sq(ux, uy, a[0], a[1], b[0], b[1]) <= half_line_sq
                    if white:
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
