#!/usr/bin/env python3
"""Renders Junco's two static glass assets, once, so the app never runs a
blur, shadow or noise shader:

- assets/glass/card-shadow.png: the soft shadow under a glass card, drawn as
  a 9-slice BorderImage (GlassPane.qml). The card's own shape is cut out:
  a shadow showing through the translucent card would grey the glass.
- assets/glass/grain.png: a 128x128 tile of fine luminance noise, drawn
  tiled at ~4% opacity over the glass (shell.qml): the "frost" texture of
  real frosted glass.

    python3 -I tools/make_glass_assets.py
"""
import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "assets" / "glass"

# Shadow -----------------------------------------------------------------------
RADIUS = 16      # the card corner radius (Theme.cardPaneRadius)
EXTENT = 12      # how far the shadow reaches past the card's edge
SIGMA = 6.0      # softness: wide and diffuse
OFFSET_Y = 3     # light from above: the shadow sits a little low
ALPHA = 0.09     # strongest shadow opacity: soft and low
COLOUR = (12, 14, 28)  # near-neutral dark
SS = 4           # supersampling for smooth corners


def shadow():
    border = EXTENT + RADIUS
    size = border * 2 + 2

    def card_mask(dy=0):
        m = Image.new("L", (size * SS, size * SS), 0)
        ImageDraw.Draw(m).rounded_rectangle(
            [EXTENT * SS, (EXTENT + dy) * SS, (size - EXTENT) * SS - 1, (size - EXTENT + dy) * SS - 1],
            radius=RADIUS * SS, fill=255)
        return m.resize((size, size), Image.LANCZOS)

    s = card_mask(OFFSET_Y).filter(ImageFilter.GaussianBlur(SIGMA))
    s = s.point(lambda v: round(v * ALPHA))
    s = ImageChops.multiply(s, ImageChops.invert(card_mask(0)))
    out = Image.new("RGBA", (size, size), COLOUR + (0,))
    out.putalpha(s)
    out.save(OUT / "card-shadow.png")
    print(OUT / "card-shadow.png", out.size, "9-slice border", border)


# Grain ------------------------------------------------------------------------
GRAIN = 128


def grain():
    rnd = random.Random(20261127)  # fixed seed: the same tile every run
    img = Image.new("L", (GRAIN, GRAIN))
    img.putdata([max(0, min(255, round(rnd.gauss(128, 46)))) for _ in range(GRAIN * GRAIN)])
    # Wrap-around is free: independent per-pixel noise tiles seamlessly.
    img.convert("RGB").save(OUT / "grain.png")
    print(OUT / "grain.png", img.size)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    shadow()
    grain()
