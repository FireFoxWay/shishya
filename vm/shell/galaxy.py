#!/usr/bin/env python3
"""
The galaxy wallpaper, ported from notepro.

Same spiral: four branches, the same spin, the same gradient from a hot
yellow-white core out to violet at the rim. notepro drew it in WebGL with
12,000 points; there is no WebGL here, so this is Cairo — which means far
fewer points and a cheaper projection, chosen so the desktop still feels
instant while the clone is working.

Everything that makes it recognisable is kept: the branch structure, the
spin, the colour ramp, the slow rotation, and the distant starfield behind.
"""

import math
import random

# notepro's numbers, unchanged — this is why it looks like the same galaxy.
BRANCHES = 4
SPIN = 1.35
RAND = 0.55
RAND_POW = 3
RADIUS = 10.0

# 12,000 points is a WebGL number. Cairo redraws on the CPU, so this is lower
# — but measured rather than guessed: at 1,700 points the desktop used under
# 5% of one core, so there was room for more. Batching by colour is what makes
# that affordable; setting a source per point is what makes particle fields
# slow, not the points.
COUNT = 4200
STARS = 900
FPS = 14

GRAD = [
    (0.00, (1.000, 0.953, 0.816)),   # hot yellow-white core
    (0.24, (1.000, 0.694, 0.361)),   # orange
    (0.48, (1.000, 0.416, 0.271)),   # red-orange
    (0.72, (0.784, 0.290, 0.353)),   # red fading toward violet
    (1.00, (0.416, 0.310, 0.878)),   # violet at the rim
]


def colour_at(t):
    t = min(max(t, 0.0), 1.0)
    for i in range(len(GRAD) - 1):
        t0, c0 = GRAD[i]
        t1, c1 = GRAD[i + 1]
        if t0 <= t <= t1:
            k = (t - t0) / ((t1 - t0) or 1)
            return tuple(a + (b - a) * k for a, b in zip(c0, c1))
    return GRAD[-1][1]


def build(seed=7):
    """Positions and colours, generated once. The shape never changes — only
    the angle we view it from — so there is no reason to rebuild per frame."""
    rng = random.Random(seed)
    points = []
    for i in range(COUNT):
        r = (rng.random() ** 1.5) * RADIUS
        branch = ((i % BRANCHES) / BRANCHES) * math.tau
        spin = r * SPIN

        def scatter(scale=1.0):
            return (rng.random() ** RAND_POW) * (1 if rng.random() < 0.5 else -1) * RAND * r * scale

        x = math.cos(branch + spin) * r + scatter()
        y = scatter(0.25)
        z = math.sin(branch + spin) * r + scatter()
        points.append((x, y, z, colour_at(r / RADIUS)))

    stars = []
    for _ in range(STARS):
        theta = rng.random() * math.tau
        phi = math.acos(2 * rng.random() - 1)
        rad = 24 + rng.random() * 26
        stars.append((rad * math.sin(phi) * math.cos(theta),
                      rad * math.sin(phi) * math.sin(theta),
                      rad * math.cos(phi)))
    return points, stars


class Galaxy:
    """Draws the spiral, tilted and slowly turning."""

    def __init__(self):
        self.points, self.stars = build()
        self.angle = 0.0
        self.tilt = 0.78          # flatter, so the arms read as arms

    def step(self):
        self.angle += 0.0016      # about one turn every seven minutes

    def draw(self, cr, width, height):
        cr.set_source_rgb(0.016, 0.020, 0.035)
        cr.paint()

        cx, cy = width * 0.5, height * 0.52
        # Fill the screen: most points sit near the core (r scales as
        # random**1.5), so a tight scale leaves the arms invisible.
        scale = min(width, height) / (RADIUS * 1.35)
        cos_a, sin_a = math.cos(self.angle), math.sin(self.angle)
        cos_t, sin_t = math.cos(self.tilt), math.sin(self.tilt)

        # Starfield first, so the spiral sits in front of it.
        cr.set_source_rgba(1, 1, 1, 0.42)
        for x, y, z in self.stars:
            sx = x * cos_a - z * sin_a
            sz = x * sin_a + z * cos_a
            px = cx + sx * scale * 0.32
            py = cy + (y * cos_t - sz * sin_t) * scale * 0.32
            if 0 <= px < width and 0 <= py < height:
                cr.rectangle(px, py, 1, 1)
        cr.fill()

        # Points batched into colour buckets: setting a source per point is
        # what makes a Cairo particle field slow, not the points themselves.
        buckets = {}
        for x, y, z, colour in self.points:
            sx = x * cos_a - z * sin_a
            sz = x * sin_a + z * cos_a
            px = cx + sx * scale
            py = cy + (y * cos_t - sz * sin_t) * scale
            if not (0 <= px < width and 0 <= py < height):
                continue
            key = (round(colour[0], 1), round(colour[1], 1), round(colour[2], 1))
            buckets.setdefault(key, []).append((px, py, sz))

        for (r, g, b), pts in buckets.items():
            cr.set_source_rgba(r, g, b, 0.95)
            for px, py, sz in pts:
                # Nearer points a touch larger: enough depth to stop it
                # reading as a flat sticker.
                size = 2.1 if sz > 0 else 1.5
                cr.rectangle(px, py, size, size)
            cr.fill()

        # A soft core, drawn last so it glows over the arms.
        glow = cairo_radial(cr, cx, cy, scale * 3.0)
        cr.set_source(glow)
        cr.arc(cx, cy, scale * 3.0, 0, math.tau)
        cr.fill()


def cairo_radial(cr, cx, cy, radius):
    import cairo
    g = cairo.RadialGradient(cx, cy, 0, cx, cy, radius)
    g.add_color_stop_rgba(0.0, 1.0, 0.96, 0.85, 0.55)
    g.add_color_stop_rgba(0.45, 1.0, 0.75, 0.45, 0.16)
    g.add_color_stop_rgba(1.0, 1.0, 0.6, 0.3, 0.0)
    return g
