"""Remote poster palette and compact details actions (Chromium + Safari engine)."""

import io
from uuid import uuid4

import pytest
from PIL import Image

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect
from test_collection_design import _card, _seed, _switch
from test_collections_browser import browser_server as browser_server
from test_collections_browser import page as page

pytestmark = pytest.mark.parametrize("page", ["chromium", "webkit"], indirect=True)


@pytest.mark.parametrize("mode", ["music", "books"])
def test_actions_stay_above_save_and_dismiss_without_losing_edits(page, browser_server, mode):
    row = _seed(page, browser_server, mode)
    _switch(page, mode)
    _card(page, row).locator("[data-open-music]").click()
    actions = page.locator("#music-more-actions")
    for width, height in [(1440, 1000), (900, 720), (390, 844)]:
        page.set_viewport_size({"width": width, "height": height})
        actions.locator("summary").click()
        buttons = actions.locator("button:visible")
        assert buttons.count() == (4 if mode == "music" else 3)
        save = page.locator("#music-save").bounding_box()
        for button in buttons.all():
            rect = button.bounding_box()
            assert rect["y"] >= 0
            assert rect["x"] >= 0 and rect["x"] + rect["width"] <= width
            assert rect["y"] + rect["height"] < save["y"]
            assert button.evaluate(
                "el => { const r = el.getBoundingClientRect(); return el.contains(document.elementFromPoint(r.x + r.width/2, r.y + r.height/2)); }"
            )
        page.keyboard.press("Escape")
        expect(actions).not_to_have_attribute("open", "")
        expect(page.locator("#music-editor")).to_be_visible()
    actions.locator("summary").click()
    page.locator("#music-edit-catalog").click()
    page.locator("#music-title").fill(row["title"] + " changed")
    actions.locator("summary").click()
    page.locator("#music-editor-title").click()
    expect(actions).not_to_have_attribute("open", "")
    expect(page.locator("#music-title")).to_have_value(row["title"] + " changed")


def test_screen_reveal_uses_owned_palette_without_cors_probe(page, browser_server):
    poster = f"https://image.tmdb.org/t/p/w500/{uuid4()}.png"
    out = io.BytesIO()
    Image.new("RGB", (60, 90), "#dfae53").save(out, "PNG")
    requests = []
    page.route(
        poster,
        lambda route: (
            requests.append(route.request.url),
            route.fulfill(body=out.getvalue(), content_type="image/png"),
        ),
    )
    row = page.request.post(
        f"{browser_server}/api/entries/manual",
        data={
            "canonical_title": f"Palette {uuid4()}",
            "media_type": "tv",
            "poster_url": poster,
        },
    ).json()["entry"]
    page.route(
        f"**/api/entries/{row['id']}/artwork-palette",
        lambda route: route.fulfill(json={"url": poster, "rgb": [223, 174, 83]}),
    )
    page.request.put(f"{browser_server}/api/settings/general", data={"artwork_reveal": True})
    page.reload()
    card = page.locator(f'.entry-card[data-entry="{row["id"]}"]')
    expect(card).to_be_visible()
    page.wait_for_function(
        "id => document.querySelector(`[data-entry='${id}']`).style.getPropertyValue('--reveal-bg').includes('86%')",
        arg=row["id"],
    )
    assert card.evaluate("el => el.style.getPropertyValue('--reveal-ink')") == "#111820"
    assert len(requests) == 1
