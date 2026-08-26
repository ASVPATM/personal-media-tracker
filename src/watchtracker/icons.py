from __future__ import annotations

import re

from PIL import Image, ImageDraw, ImageFont

DEFAULT_ICON_BACKGROUND = "#111010"
DEFAULT_ICON_TEXT = "#24cd09"


def valid_icon_color(value: str) -> bool:
    return bool(re.fullmatch(r"#[0-9a-fA-F]{6}", str(value)))


def render_icon(
    size: int = 1024,
    *,
    background_color: str = DEFAULT_ICON_BACKGROUND,
    text_color: str = DEFAULT_ICON_TEXT,
) -> Image.Image:
    """Render the signed-build default or a device-local runtime icon."""
    if size < 16:
        raise ValueError("icon size must be at least 16 pixels")
    if not valid_icon_color(background_color) or not valid_icon_color(text_color):
        raise ValueError("icon colors must be six-digit hex values")

    scale = size / 1024
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = round(36 * scale)
    radius = round(222 * scale)
    draw.rounded_rectangle(
        (margin, margin, size - margin, size - margin),
        radius=radius,
        fill=background_color,
    )

    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", round(238 * scale))
    except OSError:
        font = ImageFont.load_default(size=round(238 * scale))
    text = "PMT"
    stroke_width = max(1, round(3 * scale))
    bounds = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    draw.text(
        ((size - width) / 2, (size - height) / 2 - bounds[1]),
        text,
        fill=text_color,
        font=font,
        stroke_width=stroke_width,
        stroke_fill=text_color,
    )
    return image
