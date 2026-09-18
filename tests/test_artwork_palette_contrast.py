"""Translucency must not trade away readable text or require artwork requests."""

from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright


def luminance(rgb):
    values = [value / 255 for value in rgb]
    linear = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in values
    ]
    return sum(
        value * weight for value, weight in zip(linear, [0.2126, 0.7152, 0.0722], strict=True)
    )


def ratio(a, b):
    one, two = sorted((luminance(a), luminance(b)))
    return (two + 0.05) / (one + 0.05)


def test_palette_contrast_at_worst_case_backdrop_and_no_network():
    source = Path("src/watchtracker/static/artwork-palette.js").read_text()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        requests = []
        page.on("request", lambda request: requests.append(request.url))
        page.evaluate(source)
        results = page.evaluate("""async () => {
          const colors = ['#000000','#ffffff','#808080','#888888','#999999','#ff0000','#00ff00','#0000ff','#ffff00','#ff00ff','#00ffff','#ab9122','#987321'];
          const results = [];
          for (const color of colors) {
            const canvas = document.createElement('canvas'); canvas.width = canvas.height = 12;
            const ctx = canvas.getContext('2d'); ctx.fillStyle = color; ctx.fillRect(0,0,12,12);
            const card = document.createElement('article'); card.className = 'entry-card';
            const img = new Image(); card.append(img); document.body.append(card);
            img.src = canvas.toDataURL(); await img.decode(); PMTArtworkPalette.inspect(img);
            const value = name => card.style.getPropertyValue('--reveal-' + name);
            results.push({bg:value('bg'), surface:value('surface'), ink:value('ink'), muted:value('muted')}); card.remove();
          }
          return results;
        }""")
        assert not requests
        for row in results:
            assert "86%" in row["bg"], row
            surface = [
                int(value)
                for value in row["surface"].removeprefix("rgb(").removesuffix(")").split()
            ]
            ink = [int(row["ink"][index : index + 2], 16) for index in (1, 3, 5)]
            muted = [int(row["muted"][index : index + 2], 16) for index in (1, 3, 5)]
            backdrop = 255 if row["ink"] == "#ffffff" else 0
            combined = [value * 0.86 + backdrop * 0.14 for value in surface]
            assert ratio(ink, combined) >= 4.5, row
            assert ratio(muted, combined) >= 4.5, row
        browser.close()
