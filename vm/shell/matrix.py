#!/usr/bin/env python3
"""
The Matrix wallpaper — falling glyphs.

Same shape of thing as galaxy.py: build once, step, draw. Cairo renders text
far more slowly than rectangles, so the column width and trail length are
chosen to keep the number of glyph draws per frame in the hundreds rather
than the thousands.
"""

import random
import string

COLUMN_W = 19
TRAIL = 11
FPS = 12

# Half-width katakana is what the film used; the ASCII is there because not
# every font in a minimal sandbox carries the katakana block, and a wallpaper
# of empty boxes would be worse than a plainer one.
GLYPHS = [chr(c) for c in range(0xFF66, 0xFF9D)] + list(string.digits + "ABCDEFHIJKLMNOPQRSTUVXYZ:.=*+-<>")


class Matrix:
    def __init__(self, seed=3):
        self.rng = random.Random(seed)
        self.columns = []
        self.width = 0
        self.height = 0

    def _build(self, width, height):
        self.width, self.height = width, height
        rows = max(1, height // COLUMN_W)
        self.columns = []
        for _ in range(max(1, width // COLUMN_W)):
            self.columns.append({
                "head": self.rng.uniform(-rows, rows),
                "speed": self.rng.uniform(0.25, 0.9),
                # Each column keeps its own glyphs so they do not all change
                # together, which reads as flicker rather than rain.
                "chars": [self.rng.choice(GLYPHS) for _ in range(TRAIL)],
            })

    def step(self):
        if not self.columns:
            return
        rows = max(1, self.height // COLUMN_W)
        for col in self.columns:
            col["head"] += col["speed"]
            if col["head"] - TRAIL > rows:
                col["head"] = self.rng.uniform(-rows * 0.6, 0)
                col["speed"] = self.rng.uniform(0.25, 0.9)
            # Churn one glyph per column per frame. Redrawing all of them
            # every frame looks like static; none looks like a screenshot.
            col["chars"][self.rng.randrange(TRAIL)] = self.rng.choice(GLYPHS)

    def draw(self, cr, width, height):
        if width != self.width or height != self.height or not self.columns:
            self._build(width, height)

        cr.set_source_rgb(0.008, 0.028, 0.012)
        cr.paint()

        cr.select_font_face("monospace")
        cr.set_font_size(COLUMN_W - 3)

        for i, col in enumerate(self.columns):
            x = i * COLUMN_W + 3
            head = col["head"]
            for t in range(TRAIL):
                row = int(head) - t
                if row < 0 or row * COLUMN_W > height:
                    continue
                y = row * COLUMN_W + COLUMN_W
                if t == 0:
                    cr.set_source_rgb(0.82, 1.0, 0.86)      # the leading glyph
                else:
                    fade = (1 - t / TRAIL) ** 1.6
                    cr.set_source_rgba(0.18, 0.95, 0.35, fade * 0.9)
                cr.move_to(x, y)
                cr.show_text(col["chars"][t])
