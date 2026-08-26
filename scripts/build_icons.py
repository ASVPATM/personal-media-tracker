from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "packaging" / "icons"
sys.path.insert(0, str(ROOT / "src"))

from watchtracker.icons import render_icon  # noqa: E402


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
