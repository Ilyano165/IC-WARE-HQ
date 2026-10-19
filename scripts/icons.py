"""Erzeugt die App-Icons aus der Geometrie von web/img/logo.svg (32×32-Raster): Windows-.ico und PWA-PNGs.

    python3 scripts/icons.py      # schreibt windows/installer/ichq.ico, web/img/icon-192.png, icon-512.png
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


def zeichne(px: int, rand: float = 0.0) -> Image.Image:
    """``rand``: Anteil Innenabstand (PWA „maskable" braucht eine Sicherheitszone)."""
    img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = px / 32
    d.rounded_rectangle((0, 0, px - 1, px - 1), radius=0 if rand else 7 * s, fill="#060708")
    k = (1 - 2 * rand) * s
    o = rand * px

    def p(x: float, y: float) -> tuple[float, float]:
        return (o + x * k, o + y * k)
    d.rounded_rectangle((*p(4, 5), *p(10, 27)), radius=1 * k, fill="#F4F6F5")
    d.polygon([p(28, 5), p(14, 5), p(14, 27), p(28, 27), p(28, 21), p(20, 21), p(20, 11), p(28, 11)], fill="#19E56E")
    return img


if __name__ == "__main__":
    zeichne(256).save(ROOT / "windows/installer/ichq.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                                                                     (128, 128), (256, 256)])
    zeichne(192).save(ROOT / "src/ichq/web/img/icon-192.png")
    zeichne(512).save(ROOT / "src/ichq/web/img/icon-512.png")
    zeichne(512, rand=0.1).save(ROOT / "src/ichq/web/img/icon-maskable-512.png")
