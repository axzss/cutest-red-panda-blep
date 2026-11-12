"""Cutest-picture entry: a baby red panda with a flower crown, sticking
its tongue out (a "blep").

The program draws one 1024x1024 picture with a pure-stdlib software
renderer (no third-party imports: the grading sandbox runs Python 3.13
stdlib only) and writes it to $MAKEFUN_OUTPUT_DIR/entry.png
(default /output/entry.png).

Everything is deterministic: fixed seeds, no time, no unseeded
randomness. Two runs write byte-identical files.
"""

import math
import os
import struct
import zlib


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def lerp(a, b, t):
    return a + (b - a) * t


def lerp_rgb(c1, c2, t):
    return (round(lerp(c1[0], c2[0], t)),
            round(lerp(c1[1], c2[1], t)),
            round(lerp(c1[2], c2[2], t)))


def grad_color(stops, t):
    """stops: sorted list of (pos 0..1, (r,g,b)). Returns interpolated color."""
    if t <= stops[0][0]:
        return stops[0][1]
    if t >= stops[-1][0]:
        return stops[-1][1]
    for i in range(len(stops) - 1):
        p0, c0 = stops[i]
        p1, c1 = stops[i + 1]
        if p0 <= t <= p1:
            f = 0.0 if p1 == p0 else (t - p0) / (p1 - p0)
            return lerp_rgb(c0, c1, f)
    return stops[-1][1]


def lcg(seed):
    """Tiny deterministic pseudo-random generator (LCG). Yields floats in [0,1)."""
    x = seed & 0x7FFFFFFF
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x / 0x7FFFFFFF


class Canvas:
    def __init__(self, w=1024, h=1024):
        self.w = w
        self.h = h
        self.buf = bytearray(w * h * 3)

    # ---- low level -------------------------------------------------
    def _px(self, x, y):
        i = (y * self.w + x) * 3
        b = self.buf
        return (b[i], b[i + 1], b[i + 2])

    def _set(self, x, y, rgb):
        i = (y * self.w + x) * 3
        b = self.buf
        b[i] = rgb[0]
        b[i + 1] = rgb[1]
        b[i + 2] = rgb[2]

    def _blend(self, x, y, rgb, a):
        if a <= 0.0:
            return
        if a >= 1.0:
            self._set(x, y, rgb)
            return
        i = (y * self.w + x) * 3
        b = self.buf
        b[i] = round(rgb[0] * a + b[i] * (1.0 - a))
        b[i + 1] = round(rgb[1] * a + b[i + 1] * (1.0 - a))
        b[i + 2] = round(rgb[2] * a + b[i + 2] * (1.0 - a))

    def solid_span(self, y, x0, x1, rgb):
        """Fill integer pixel span [x0, x1] on row y with a solid color."""
        if y < 0 or y >= self.h:
            return
        x0 = max(0, int(x0))
        x1 = min(self.w - 1, int(x1))
        if x1 < x0:
            return
        n = x1 - x0 + 1
        base = (y * self.w + x0) * 3
        self.buf[base:base + n * 3] = bytes(rgb) * n

    def alpha_span(self, y, x0, x1, rgb, a):
        """Blend a solid-color span over the row with alpha a."""
        if a <= 0.0 or y < 0 or y >= self.h:
            return
        x0 = max(0, int(x0))
        x1 = min(self.w - 1, int(x1))
        if x1 < x0:
            return
        if a >= 1.0:
            self.solid_span(y, x0, x1, rgb)
            return
        buf = self.buf
        ia = 1.0 - a
        r, g, bl = rgb
        for x in range(x0, x1 + 1):
            i = (y * self.w + x) * 3
            buf[i] = round(r * a + buf[i] * ia)
            buf[i + 1] = round(g * a + buf[i + 1] * ia)
            buf[i + 2] = round(bl * a + buf[i + 2] * ia)

    # ---- gradients -------------------------------------------------
    def vgrad(self, stops):
        """Fill the whole canvas with a vertical gradient."""
        for y in range(self.h):
            c = grad_color(stops, y / (self.h - 1))
            self.solid_span(y, 0, self.w - 1, c)

    def vgrad_rect(self, y0, y1, stops):
        """Vertical gradient over rows [y0, y1]."""
        y0 = max(0, int(y0))
        y1 = min(self.h - 1, int(y1))
        span = max(1, y1 - y0)
        for y in range(y0, y1 + 1):
            c = grad_color(stops, (y - y0) / span)
            self.solid_span(y, 0, self.w - 1, c)

    # ---- shapes ----------------------------------------------------
    def circle(self, cx, cy, r, rgb, alpha=1.0):
        self.ellipse(cx, cy, r, r, rgb, alpha)

    def ellipse(self, cx, cy, rx, ry, rgb, alpha=1.0):
        """Filled ellipse with analytic anti-aliased edges."""
        if rx <= 0 or ry <= 0:
            return
        y0 = max(0, int(math.floor(cy - ry - 1)))
        y1 = min(self.h - 1, int(math.ceil(cy + ry + 1)))
        for y in range(y0, y1 + 1):
            dy = (y + 0.5 - cy) / ry
            if abs(dy) >= 1.0:
                continue
            dx = rx * math.sqrt(1.0 - dy * dy)
            x0f = cx - dx
            x1f = cx + dx
            xl = int(math.floor(x0f))
            xr = int(math.floor(x1f))
            if xr - xl <= 1:
                # thin sliver: blend one pixel by coverage
                cov = clamp(x1f - x0f, 0.0, 1.0)
                if 0 <= xl < self.w:
                    self._blend(xl, y, rgb, alpha * cov)
                continue
            # edge pixels by fractional coverage
            cov_l = clamp((xl + 1) - x0f, 0.0, 1.0)
            cov_r = clamp(x1f - xr, 0.0, 1.0)
            if 0 <= xl < self.w:
                self._blend(xl, y, rgb, alpha * cov_l)
            if 0 <= xr < self.w:
                self._blend(xr, y, rgb, alpha * cov_r)
            self.alpha_span(y, xl + 1, xr - 1, rgb, alpha)

    def poly(self, pts, rgb, alpha=1.0):
        """Filled polygon (scanline) with anti-aliased edges."""
        if len(pts) < 3:
            return
        ys = [p[1] for p in pts]
        y0 = max(0, int(math.floor(min(ys))))
        y1 = min(self.h - 1, int(math.ceil(max(ys))))
        n = len(pts)
        for y in range(y0, y1 + 1):
            yc = y + 0.5
            xs = []
            for i in range(n):
                x0, y0p = pts[i]
                x1, y1p = pts[(i + 1) % n]
                if (y0p <= yc < y1p) or (y1p <= yc < y0p):
                    t = (yc - y0p) / (y1p - y0p)
                    xs.append(x0 + t * (x1 - x0))
            if len(xs) < 2:
                continue
            xs.sort()
            for k in range(0, len(xs) - 1, 2):
                x0f, x1f = xs[k], xs[k + 1]
                if x1f <= x0f:
                    continue
                xl = int(math.floor(x0f))
                xr = int(math.floor(x1f))
                if xr - xl <= 1:
                    cov = clamp(x1f - x0f, 0.0, 1.0)
                    if 0 <= xl < self.w:
                        self._blend(xl, y, rgb, alpha * cov)
                    continue
                cov_l = clamp((xl + 1) - x0f, 0.0, 1.0)
                cov_r = clamp(x1f - xr, 0.0, 1.0)
                if 0 <= xl < self.w:
                    self._blend(xl, y, rgb, alpha * cov_l)
                if 0 <= xr < self.w:
                    self._blend(xr, y, rgb, alpha * cov_r)
                self.alpha_span(y, xl + 1, xr - 1, rgb, alpha)

    def poly_vgrad(self, pts, stops, y_top, y_bot):
        """Filled polygon whose color follows a vertical gradient between y_top/y_bot."""
        if len(pts) < 3:
            return
        ys = [p[1] for p in pts]
        y0 = max(0, int(math.floor(min(ys))))
        y1 = min(self.h - 1, int(math.ceil(max(ys))))
        n = len(pts)
        span = max(1.0, y_bot - y_top)
        for y in range(y0, y1 + 1):
            yc = y + 0.5
            xs = []
            for i in range(n):
                x0, y0p = pts[i]
                x1, y1p = pts[(i + 1) % n]
                if (y0p <= yc < y1p) or (y1p <= yc < y0p):
                    t = (yc - y0p) / (y1p - y0p)
                    xs.append(x0 + t * (x1 - x0))
            if len(xs) < 2:
                continue
            xs.sort()
            c = grad_color(stops, clamp((y - y_top) / span, 0.0, 1.0))
            for k in range(0, len(xs) - 1, 2):
                self.solid_span(y, int(math.ceil(xs[k])), int(math.floor(xs[k + 1])), c)

    def stroke(self, pts, width, rgb, alpha=1.0):
        """Thick polyline drawn as overlapping circles (round caps/joins).

        The polyline is densified first so circles overlap and the line
        reads smooth, never dotted, whatever spacing the caller used.
        """
        r = width / 2.0
        step = max(1.5, width * 0.35)
        dense = [pts[0]]
        for i in range(len(pts) - 1):
            x0, y0 = pts[i]
            x1, y1 = pts[i + 1]
            d = math.hypot(x1 - x0, y1 - y0)
            n = max(1, int(d / step))
            for k in range(1, n + 1):
                t = k / n
                dense.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
        for (x, y) in dense:
            self.circle(x, y, r, rgb, alpha)

    def glow(self, cx, cy, r, rgb, a_max=0.35, rings=9):
        """Soft glow: concentric circles, alpha fading outward."""
        for k in range(rings, 0, -1):
            rr = r * k / rings
            a = a_max * (1.0 - k / (rings + 1.0))
            self.circle(cx, cy, rr, rgb, a)

    # ---- curves ----------------------------------------------------
    @staticmethod
    def bezier(p0, p1, p2, p3, steps=32):
        pts = []
        for i in range(steps + 1):
            t = i / steps
            mt = 1.0 - t
            x = (mt ** 3 * p0[0] + 3 * mt * mt * t * p1[0] +
                 3 * mt * t * t * p2[0] + t ** 3 * p3[0])
            y = (mt ** 3 * p0[1] + 3 * mt * mt * t * p1[1] +
                 3 * mt * t * t * p2[1] + t ** 3 * p3[1])
            pts.append((x, y))
        return pts

    @staticmethod
    def quad(p0, p1, p2, steps=24):
        pts = []
        for i in range(steps + 1):
            t = i / steps
            mt = 1.0 - t
            x = mt * mt * p0[0] + 2 * mt * t * p1[0] + t * t * p2[0]
            y = mt * mt * p0[1] + 2 * mt * t * p1[1] + t * t * p2[1]
            pts.append((x, y))
        return pts

    # ---- output ----------------------------------------------------
    def save_png(self, path):
        """Encode the buffer as a PNG (filter 0, or filter 1 if smaller)."""
        w, h = self.w, self.h
        raw0 = bytearray()
        raw1 = bytearray()
        buf = self.buf
        for y in range(h):
            row = bytes(buf[y * w * 3:(y + 1) * w * 3])
            raw0.append(0)
            raw0 += row
            raw1.append(1)
            prev = 0
            out = bytearray()
            for i, b in enumerate(row):
                if i < 3:
                    out.append(b)
                else:
                    out.append((b - row[i - 3]) & 0xFF)
            raw1 += out
        c0 = zlib.compress(bytes(raw0), 6)
        data = c0
        if len(c0) > 950000:
            c1 = zlib.compress(bytes(raw1), 6)
            if len(c1) < len(c0):
                data = c1

        def chunk(typ, payload):
            c = struct.pack(">I", len(payload)) + typ + payload
            c += struct.pack(">I", zlib.crc32(typ + payload) & 0xFFFFFFFF)
            return c

        ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
        png = b"\x89PNG\r\n\x1a\n"
        png += chunk(b"IHDR", ihdr)
        png += chunk(b"IDAT", data)
        png += chunk(b"IEND", b"")
        with open(path, "wb") as f:
            f.write(png)
        return len(png)


# ---- the picture: a baby red panda with a flower crown, tongue out ----
# Big round face fills the frame so it reads instantly at 300px:
# huge glossy eyes, blush cheeks, a flower crown, and a little pink
# tongue sticking out (a "blep").

def bokeh(c, seed=5, n=16):
    rnd = lcg(seed)
    cols = [(255, 255, 255), (244, 183, 205), (255, 224, 138), (255, 255, 255)]
    for i in range(n):
        x = int(next(rnd) * 1024)
        y = int(next(rnd) * 1024)
        r = 18 + next(rnd) * 55
        col = cols[i % len(cols)]
        c.circle(x, y, r, col, 0.10 + next(rnd) * 0.10)


def petals(c, seed=9, n=10):
    rnd = lcg(seed)
    for _ in range(n):
        x = int(next(rnd) * 1024)
        y = int(next(rnd) * 1024)
        rx = 10 + next(rnd) * 12
        c.ellipse(x, y, rx, rx * 0.55, (244, 143, 177), 0.55)


def flower(c, cx, cy, petal_col, r=26):
    """Five-petal daisy with a yellow center."""
    for k in range(5):
        ang = -math.pi / 2 + k * (2 * math.pi / 5)
        px = cx + math.cos(ang) * r * 0.62
        py = cy + math.sin(ang) * r * 0.62
        c.ellipse(px, py, r * 0.52, r * 0.52, petal_col)
    c.circle(cx, cy, r * 0.34, (255, 214, 120))


def flower_crown(c, head_cx, head_cy, head_r, y_lift=8):
    """Flowers + leaves sitting on the top arc of a round head."""
    cols = [(244, 143, 177), (255, 255, 255), (244, 143, 177),
            (255, 255, 255), (244, 143, 177)]
    for i, fx in enumerate([330, 420, 512, 604, 694]):
        dx = fx - head_cx
        fy = head_cy - math.sqrt(max(0.0, head_r * head_r - dx * dx)) + y_lift
        # leaf behind each flower
        c.ellipse(fx - 26, fy + 16, 16, 7, (143, 191, 127), 0.9)
        c.ellipse(fx + 26, fy + 16, 16, 7, (143, 191, 127), 0.9)
        flower(c, fx, fy, cols[i], 26 if i != 2 else 30)


def draw_panda():
    c = Canvas(1024, 1024)
    c.vgrad([(0.0, (253, 243, 227)), (0.55, (250, 226, 232)), (1.0, (244, 203, 220))])
    bokeh(c, seed=5)
    petals(c, seed=9)

    rust = (194, 105, 54)
    rust_dark = (163, 77, 36)
    cream = (248, 236, 220)
    dark = (59, 42, 32)
    pink = (242, 160, 168)

    # shoulders at the bottom
    c.ellipse(512, 1080, 430, 260, rust)
    c.ellipse(512, 1060, 200, 130, cream, 0.95)

    # ears
    c.circle(300, 300, 98, rust_dark)
    c.circle(724, 300, 98, rust_dark)
    c.circle(300, 300, 92, rust)
    c.circle(724, 300, 92, rust)
    c.ellipse(300, 312, 48, 58, cream)
    c.ellipse(724, 312, 48, 58, cream)

    # head (dark rim then main)
    c.circle(512, 540, 308, rust_dark)
    c.circle(512, 540, 298, rust)

    # cream eye patches + muzzle
    c.ellipse(380, 500, 118, 138, cream)
    c.ellipse(644, 500, 118, 138, cream)
    c.ellipse(512, 668, 178, 122, cream)

    # huge glossy eyes
    for ex in (380, 644):
        c.circle(ex, 500, 64, dark)
        c.circle(ex - 20, 478, 19, (255, 255, 255))
        c.circle(ex + 18, 524, 7, (255, 255, 255), 0.9)
        # upper lash arc
        arc = Canvas.quad((ex - 52, 452), (ex, 428), (ex + 52, 452), 16)
        c.stroke(arc, 7, dark)

    # nose: small rounded oval
    c.ellipse(512, 620, 36, 24, dark)
    c.circle(500, 612, 6, (255, 255, 255), 0.65)

    # mouth: little "w" smile
    m1 = Canvas.quad((472, 652), (492, 672), (512, 652), 12)
    m2 = Canvas.quad((512, 652), (532, 672), (552, 652), 12)
    c.stroke(m1, 5, dark)
    c.stroke(m2, 5, dark)
    # tiny tongue sticking out (the blep)
    c.ellipse(512, 678, 26, 30, (240, 130, 150))
    c.ellipse(512, 672, 18, 18, (244, 150, 168))

    # blush
    c.ellipse(322, 648, 56, 34, pink, 0.75)
    c.ellipse(702, 648, 56, 34, pink, 0.75)

    # fur texture: a few soft darker arcs on the cheeks
    for (x0, y0, x1, y1) in [(300, 720, 360, 740), (664, 720, 724, 740),
                             (330, 760, 380, 772), (644, 760, 694, 772)]:
        c.stroke(Canvas.quad((x0, y0), ((x0 + x1) / 2, y0 + 8), (x1, y1), 10),
                 4, rust_dark, 0.35)

    # flower crown on the head arc
    flower_crown(c, 512, 540, 298)
    return c


if __name__ == "__main__":
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "entry.png")
    canvas = draw_panda()
    size = canvas.save_png(out_path)
    print(f"cutest red panda (blep) -> {out_path} ({size} bytes)")
