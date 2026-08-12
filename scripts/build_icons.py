from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "packaging" / "icons"


def _mix(first: tuple[int, ...], second: tuple[int, ...], fraction: float) -> tuple[int, ...]:
    return tuple(round(a + (b - a) * fraction) for a, b in zip(first, second, strict=True))


def render_icon(size: int = 1024) -> Image.Image:
    scale = size / 1024
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = round(36 * scale)
    radius = round(222 * scale)
    top = (91, 146, 125, 255)
    bottom = (32, 60, 50, 255)

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (margin, margin, size - margin, size - margin), radius=radius, fill=255
    )
    gradient = Image.new("RGBA", (size, size))
    pixels = gradient.load()
    for y in range(size):
        for x in range(size):
            fraction = min(1.0, max(0.0, (x + y) / (2 * max(size - 1, 1))))
            pixels[x, y] = _mix(top, bottom, fraction)
    image.alpha_composite(Image.composite(gradient, Image.new("RGBA", image.size), mask))

    white = (255, 254, 250, 255)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", round(238 * scale))
    except OSError:
        font = ImageFont.load_default(size=round(238 * scale))
    text = "PMT"
    bounds = draw.textbbox((0, 0), text, font=font, stroke_width=round(3 * scale))
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    draw.text(
        ((size - width) / 2, (size - height) / 2 - bounds[1]),
        text,
        fill=white,
        font=font,
        stroke_width=round(3 * scale),
        stroke_fill=white,
    )
    return image


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    icon = render_icon()
    icon.save(OUTPUT / "watchtracker.png", optimize=True)
    icon.save(
        OUTPUT / "watchtracker.ico",
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    icon.save(OUTPUT / "watchtracker.icns", format="ICNS")
    for size in (16, 32, 48, 64, 128, 256, 512):
        resized = icon.resize((size, size), Image.Resampling.LANCZOS)
        resized.save(OUTPUT / f"watchtracker-{size}.png", optimize=True)
    print(f"Generated application icons in {OUTPUT}")


if __name__ == "__main__":
    main()
