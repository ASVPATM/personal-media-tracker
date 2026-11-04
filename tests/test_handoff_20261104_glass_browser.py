"""Rendered glass strength, continuous reveal surfaces, and detail-panel geometry."""

from io import BytesIO

import pytest
from PIL import Image, ImageChops, ImageStat

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect
from test_collection_design import _card, _seed, _switch
from test_collections_browser import browser_server as browser_server
from test_collections_browser import page as page
from test_handoff_20261103_225456_browser import screen_entry
from test_handoff_20261103_followup_browser import settled

pytestmark = pytest.mark.parametrize("page", ["chromium", "webkit"], indirect=True)


def rgba(locator, property_name="backgroundColor"):
    return locator.evaluate(
        """(e, property) => {
      const canvas=document.createElement('canvas'); canvas.width=canvas.height=1;
      const ctx=canvas.getContext('2d'); ctx.fillStyle=getComputedStyle(e)[property];
      ctx.fillRect(0,0,1,1); return [...ctx.getImageData(0,0,1,1).data];
    }""",
        property_name,
    )


def contrast(a, b):
    def luminance(rgb):
        values = [x / 255 for x in rgb[:3]]
        linear = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in values]
        return sum(x * w for x, w in zip(linear, [0.2126, 0.7152, 0.0722], strict=True))

    x, y = sorted([luminance(a), luminance(b)])
    return (y + 0.05) / (x + 0.05)


def open_detail(page, server, domain):
    if domain == "screen":
        screen_entry(page, server)
        dialog = page.locator("#entry-dialog")
    else:
        row = _seed(
            page,
            server,
            domain,
            **(
                {"tracks": [{"title": "First", "position": 1, "disc": 1}]}
                if domain == "music"
                else {}
            ),
        )
        _switch(page, domain)
        _card(page, row).locator("[data-open-music]").click()
        dialog = page.locator("#music-editor")
    settled(dialog)
    return dialog


@pytest.mark.parametrize("domain", ["screen", "music", "books"])
@pytest.mark.parametrize("native", [False, True])
def test_glass_changes_actual_layers_and_pixels_not_just_the_slider(
    page, browser_server, domain, native
):
    if native:
        page.goto(browser_server + "?desktop=macos", wait_until="networkidle")
    dialog = open_detail(page, browser_server, domain)
    main = dialog.locator(".detail-main")
    inner = dialog.locator(".entry-dialog-art")
    alpha = []
    captures = []
    for value in (0, 50, 100):
        page.evaluate("value=>applyInterfaceTransparency(value)", value)
        settled(main)
        alpha.append([rgba(main)[3], rgba(inner)[3]])
        captures.append(Image.open(BytesIO(main.screenshot())).convert("RGB"))
    assert alpha[0] == [255, 255]
    assert 120 < alpha[1][0] < 200
    assert alpha[2][0] < 85 and alpha[2][1] < 25, alpha
    assert ImageStat.Stat(ImageChops.difference(captures[0], captures[2])).mean[0] > 5
    assert ImageStat.Stat(ImageChops.difference(captures[1], captures[2])).mean[0] > 3
    # Removing panel paint must not fade the form or text along with it.
    expect(main).to_have_css("opacity", "1")
    expect(dialog.locator(".dialog-tabs button").first).to_have_css("opacity", "1")
    if domain != "books":
        sidecar = dialog.locator(".connected-sidecar")
        assert rgba(sidecar) == rgba(main)
    if domain == "books":
        page.locator('[data-collection-tab="contents"]').click()
        label = page.locator("#music-panel-contents label")
        assert rgba(label, "color") == rgba(main, "color")
        expect(label).to_have_css("font-weight", "700")
    visible_view = page.locator("#main > .app-view:not([hidden])").first
    expect(visible_view).to_have_css("filter", "blur(8px)")
    dialog.locator(".dialog-close").click()
    expect(visible_view).to_have_css("filter", "none")


@pytest.mark.parametrize("domain", ["screen", "music"])
def test_detail_panels_stay_aligned_without_decorative_connector(page, browser_server, domain):
    dialog = open_detail(page, browser_server, domain)
    expect(dialog.locator(".detail-connector")).to_have_count(0)
    for width in (1440, 900, 390):
        page.set_viewport_size({"width": width, "height": 950})
        settled(dialog)
        a, b = [
            dialog.locator(selector).bounding_box()
            for selector in (".detail-main", ".connected-sidecar")
        ]
        assert a and b and b["height"] > 0
        if width > 820:
            assert 8 <= b["x"] - (a["x"] + a["width"]) <= 20, (a, b)
            assert abs(a["y"] - b["y"]) < 2, (a, b)
        else:
            assert 8 <= b["y"] - (a["y"] + a["height"]) <= 20, (a, b)
            assert abs(a["x"] - b["x"]) < 2, (a, b)
        assert b["x"] >= 0 and b["x"] + b["width"] <= width


@pytest.mark.parametrize("domain", ["music", "books"])
def test_rankings_filters_follow_glass_scale(page, browser_server, domain):
    _seed(page, browser_server, domain)
    _switch(page, domain)
    page.locator('.primary-nav [data-view="music_rankings"]').click()
    bar = page.locator("#music-filters")
    expect(bar).to_be_visible()
    page.evaluate("()=>applyInterfaceTransparency(0)")
    settled(bar)
    assert rgba(bar)[3] == 255
    page.evaluate("()=>applyInterfaceTransparency(100)")
    settled(bar)
    assert rgba(bar)[3] < 85


@pytest.mark.parametrize("domain", ["screen", "music", "books"])
def test_reveal_uses_one_translucent_sheet_with_readable_unboxed_content(
    page, browser_server, domain
):
    if domain == "screen":
        row = screen_entry(page, browser_server, media_type="movie")
        page.locator("#entry-dialog .dialog-close").click()
        page.request.put(
            browser_server + "/api/settings/general", data={"artwork_reveal": True}
        )
        page.reload(wait_until="networkidle")
        card = page.locator(f'[data-entry="{row["id"]}"]')
        panel = card.locator(".pmt-artwork-panel")
    else:
        row = _seed(page, browser_server, domain)
        page.request.put(
            browser_server + "/api/settings/general", data={f"{domain}_artwork_reveal": True}
        )
        page.reload(wait_until="networkidle")
        _switch(page, domain)
        card = _card(page, row)
        panel = card.locator(".music-reveal-panel")
    card.hover()
    expect(panel).to_be_visible()
    page.evaluate("()=>applyInterfaceTransparency(0)")
    settled(panel)
    solid = rgba(panel)
    assert solid[3] == 255
    page.evaluate("()=>applyInterfaceTransparency(60)")
    settled(panel)
    middle = rgba(panel)
    page.evaluate("()=>applyInterfaceTransparency(100)")
    settled(panel)
    background = rgba(panel)
    assert 0 < background[3] < 105 < middle[3] < 180
    for group in panel.locator(".entry-copy, .entry-signals, .entry-actions").all():
        assert rgba(group)[3] == 0
    caption = panel.locator(".entry-copy")
    ink = rgba(caption, "color")
    assert contrast(ink, solid) >= 4.5
    # The normal setting supports contrast over either artwork extreme. At the
    # high-transparency end, artwork is intentionally more visible and the text
    # halo supports letter edges; inspect actual preview images as well.
    for extreme in (0, 255):
        composite = [
            middle[i] * middle[3] / 255 + extreme * (1 - middle[3] / 255) for i in range(3)
        ]
        assert contrast(ink, composite) >= 4.5, (ink, middle, composite)
    assert caption.evaluate("e=>getComputedStyle(e).textShadow") != "none"
    heart = panel.locator(".favorite-toggle")
    expect(heart).to_be_visible()
    assert heart.evaluate(
        "e=>{const r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}"
    )
