"""
Generuje assets/mathloader.ico — ikonę aplikacji (matematyka + pobieranie).

Rysuje w dużej rozdzielczości i skaluje w dół, żeby krawędzie były gładkie
także w małych rozmiarach (16 px na pasku zadań).

Uruchom:  python tools/make_icon.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "mathloader.ico"

S = 1024                                   # rozmiar roboczy
ICO_SIZES = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]

BLUE_TOP = (88, 166, 255)                  # C.PRIMARY
BLUE_BOTTOM = (31, 111, 235)               # C.PRIMARY_DARK
WHITE = (255, 255, 255)

FONT_CANDIDATES = [
    "C:/Windows/Fonts/segoeuib.ttf",       # Segoe UI Bold
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _load_font(px: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, px)
        except OSError:
            continue
    return ImageFont.load_default()


def _vertical_gradient(size: int, top: tuple, bottom: tuple) -> Image.Image:
    strip = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / max(1, size - 1)
        strip.putpixel((0, y), tuple(
            round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return strip.resize((size, size), Image.Resampling.BILINEAR)


def build() -> Image.Image:
    # ── Tło: zaokrąglony kwadrat wypełniony gradientem ──
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, S - 1, S - 1], radius=int(S * 0.22), fill=255)

    icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    icon.paste(_vertical_gradient(S, BLUE_TOP, BLUE_BOTTOM), (0, 0), mask)

    d = ImageDraw.Draw(icon)

    # ── Litera „M" (matematyka) ──
    font = _load_font(int(S * 0.58))
    bbox = d.textbbox((0, 0), "M", font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text((S / 2 - w / 2 - bbox[0], S * 0.40 - h / 2 - bbox[1]),
           "M", font=font, fill=WHITE)

    # ── Strzałka pobierania pod literą ──
    cx = S / 2
    shaft_w, shaft_top, shaft_bottom = S * 0.075, S * 0.60, S * 0.755
    d.rounded_rectangle(
        [cx - shaft_w / 2, shaft_top, cx + shaft_w / 2, shaft_bottom],
        radius=shaft_w / 2, fill=WHITE)
    head = S * 0.135
    d.polygon([(cx - head, shaft_bottom - head * 0.30),
               (cx + head, shaft_bottom - head * 0.30),
               (cx, shaft_bottom + head * 0.72)], fill=WHITE)

    # ── Podstawka (jak w ikonie „pobierz") ──
    bar_w, bar_h, bar_y = S * 0.42, S * 0.062, S * 0.845
    d.rounded_rectangle(
        [cx - bar_w / 2, bar_y, cx + bar_w / 2, bar_y + bar_h],
        radius=bar_h / 2, fill=WHITE)

    return icon


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    icon = build()
    icon.resize((256, 256), Image.Resampling.LANCZOS).save(
        OUT, format="ICO", sizes=ICO_SIZES)
    icon.resize((256, 256), Image.Resampling.LANCZOS).save(
        OUT.with_suffix(".png"), format="PNG")
    print(f"Zapisano: {OUT}")
    print(f"Podgląd : {OUT.with_suffix('.png')}")


if __name__ == "__main__":
    main()
