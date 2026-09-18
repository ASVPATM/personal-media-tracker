"""Handoff 054114: presentation changes must never rewrite collection data."""

import io
from uuid import uuid4

import pytest
from PIL import Image

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect
from test_collection_design import _card, _seed, _switch
from test_collections_browser import browser_server as browser_server
from test_collections_browser import edit_panel
from test_collections_browser import page as page


@pytest.mark.parametrize("mode", ["music", "books"])
def test_metadata_read_only_explicit_edit_and_rating_number(page, browser_server, mode):
    original = (
        "**A book** about *life*. (Source: [Wikipedia](https://en.wikipedia.org/wiki/Book))"
    )
    row = (
        _seed(page, browser_server, mode, description=original)
        if mode == "books"
        else _seed(page, browser_server, mode)
    )
    _switch(page, mode)
    _card(page, row).locator("[data-open-music]").click()
    if mode == "books":
        expect(page.locator("#music-description")).to_have_text("A book about life.")
    edit_panel(page, "metadata")
    expect(
        page.locator(
            "#music-panel-metadata input, #music-panel-metadata textarea, #music-panel-metadata select"
        )
    ).to_have_count(0)
    expect(page.locator("#music-catalog-summary")).to_contain_text(row["title"])
    expect(page.locator("#music-save")).to_be_disabled()
    if mode == "books":
        expect(page.locator(".collection-description-sources a")).to_have_attribute(
            "href", "https://en.wikipedia.org/wiki/Book"
        )
    edit_panel(page, "catalog")
    expect(page.locator("#music-title")).to_be_visible()
    page.locator("#music-title").fill(row["title"] + " corrected")
    page.locator("#music-back-metadata").click()
    expect(page.locator("#music-catalog-summary")).to_contain_text("corrected")
    page.locator("#music-save").click()
    expect(page.locator("#music-editor")).to_be_hidden()
    endpoint = "albums" if mode == "music" else "entries"
    stored = page.request.get(f"{browser_server}/api/{mode}/{endpoint}/{row['id']}").json()
    assert stored["title"] == row["title"] + " corrected"
    assert stored["notes"] == row["notes"]
    if mode == "books":
        assert stored["description"] == original
    page.locator('.music-nav[data-view="music_rankings"]').click()
    expect(_card(page, row).locator(".music-rating")).to_have_text("8.5")


@pytest.mark.parametrize("mode,reveal", [("music", False), ("books", True)])
def test_remove_from_current_list_only(page, browser_server, mode, reveal):
    row = _seed(page, browser_server, mode)
    other = _seed(page, browser_server, mode)
    ids_key = "album_ids" if mode == "music" else "book_ids"
    lists = []
    for _ in range(2):
        response = page.request.post(
            f"{browser_server}/api/{mode}/lists",
            data={"name": str(uuid4()), ids_key: [row["id"], other["id"]]},
        )
        assert response.ok, response.text()
        lists.append(response.json())
    _switch(page, mode)
    page.locator('.music-nav[data-view="music_lists"]').click()
    page.locator(f'[data-open-music-list="{lists[0]["id"]}"]').click()
    expect(page.locator(".music-card")).to_have_count(2)
    if reveal:
        page.evaluate(
            "mode => PMTCollectionSettings.applyPreferences({[mode + '_artwork_reveal']: true})",
            mode,
        )
    page.locator(f'[data-remove-collection-item="{row["id"]}"]').click()
    expect(page.locator(".music-card")).to_have_count(1)
    expect(page.locator("#music-heading")).to_have_text(lists[0]["name"])
    stored = page.request.get(f"{browser_server}/api/{mode}/lists").json()["items"]
    by_id = {item["id"]: item for item in stored}
    assert by_id[lists[0]["id"]][ids_key] == [other["id"]]
    assert by_id[lists[1]["id"]][ids_key] == [row["id"], other["id"]]
    endpoint = "albums" if mode == "music" else "entries"
    assert page.request.get(f"{browser_server}/api/{mode}/{endpoint}/{row['id']}").json() == row
    page.locator("#music-list-rename").click()
    page.locator('.music-rename-form [name="name"]').fill("Renamed after removing")
    page.locator('.music-rename-form [type="submit"]').click()
    expect(page.locator("#music-heading")).to_have_text("Renamed after removing")
    page.locator(f'[data-remove-collection-item="{other["id"]}"]').click()
    expect(page.locator(".music-card")).to_have_count(0)


def test_uniform_music_cards_compact_reveal_and_hover_border(page, browser_server):
    prefix = str(uuid4())[:8]
    rows = [
        _seed(
            page,
            browser_server,
            "music",
            title=prefix + title,
            genres=["britpop"],
            subgenres=["hard bop"],
        )
        for title in [" Short", " A substantially longer album title with several lines"]
    ]
    _switch(page, "music")
    page.locator("#music-query").fill(prefix)
    expect(page.locator(".music-card")).to_have_count(2)
    for width in [1440, 390]:
        page.set_viewport_size({"width": width, "height": 1000})
        cards = [_card(page, row) for row in rows]
        sizes = [card.bounding_box()["height"] for card in cards]
        assert sizes[0] == sizes[1] == 202
        for card in cards:
            expect(card.locator(".entry-signals")).to_contain_text("Britpop")
            expect(card.locator(".entry-signals")).to_contain_text("Hard bop")
            assert (
                card.locator(".music-cover img").evaluate(
                    "img => getComputedStyle(img).objectFit"
                )
                == "cover"
            )
            bounds, info = (
                card.bounding_box(),
                card.locator(".media-info-button").bounding_box(),
            )
            assert info["y"] + info["height"] <= bounds["y"] + bounds["height"]
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.evaluate(
        "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
    )
    page.mouse.move(0, 0)
    card = _card(page, rows[0])
    normal = card.evaluate("node => getComputedStyle(node).borderColor")
    rect = card.bounding_box()
    card.hover()
    assert card.evaluate("node => getComputedStyle(node).borderColor") != normal
    assert card.bounding_box() == rect
    page.mouse.move(0, 0)
    card.locator(".media-info-button").focus()
    assert card.evaluate("node => getComputedStyle(node).borderColor") != normal
    page.evaluate("PMTCollectionSettings.applyPreferences({music_artwork_reveal:true})")
    card = _card(page, rows[0])
    card.hover()
    panel = card.locator(".music-reveal-panel")
    expect(panel).to_be_visible()
    assert panel.bounding_box()["height"] <= card.bounding_box()["height"] * 0.53
    expect(panel.locator(".music-heart")).to_be_visible()
    expect(panel.locator(".media-info-button")).to_be_visible()
    assert panel.evaluate("el => el.scrollHeight <= el.clientHeight + 1")


def test_tracklist_beside_details_with_visible_footer(page, browser_server):
    tracks = [
        {
            "id": str(uuid4()),
            "title": f"Track {i}",
            "position": i,
            "disc": 1,
            "duration_ms": 205111,
        }
        for i in range(1, 31)
    ]
    row = _seed(page, browser_server, "music", tracks=tracks)
    _switch(page, "music")
    _card(page, row).locator("[data-open-music]").click()
    for width in [1440, 900, 390]:
        page.set_viewport_size({"width": width, "height": 900 if width > 390 else 844})
        page.wait_for_function(
            "() => document.querySelector('#music-editor').getBoundingClientRect().bottom <= innerHeight"
        )
        main = page.locator(".collection-details-main").bounding_box()
        track = page.locator("#music-track-preview").bounding_box()
        if width == 1440:
            assert track["x"] >= main["x"] + main["width"]
            assert abs(track["y"] - main["y"]) <= 1
        else:
            assert track["y"] >= main["y"] + main["height"]
        save, dialog = (
            page.locator("#music-save").bounding_box(),
            page.locator("#music-editor").bounding_box(),
        )
        assert (
            save["y"] + save["height"]
            <= dialog["y"] + dialog["height"]
            <= page.viewport_size["height"]
        )
        assert page.locator("#music-editor").evaluate(
            "el => el.scrollWidth <= el.clientWidth + 1"
        )
    expect(page.locator("#music-save")).to_be_disabled()


def test_cross_origin_artwork_never_retried_for_palette(page, browser_server):
    image = io.BytesIO()
    Image.new("RGB", (90, 80), "white").save(image, "PNG")
    image_url = "https://covers.openlibrary.org/b/id/123456789-L.jpg"
    requests = []
    page.route(
        image_url,
        lambda route: (
            requests.append(route.request),
            route.fulfill(body=image.getvalue(), content_type="image/png"),
        ),
    )
    row = _seed(page, browser_server, "books", artwork_data=None, artwork_url=image_url)
    _switch(page, "books")
    image_element = _card(page, row).locator("img")
    expect(image_element).to_be_visible()
    image_element.evaluate(
        "img => { if (img.complete) PMTArtworkPalette.inspect(img); else img.onload = () => PMTArtworkPalette.inspect(img); }"
    )
    page.wait_for_function(
        "url => [...document.images].some(img => img.src === url && img.naturalWidth > 0)",
        arg=image_url,
    )
    for _ in range(4):
        image_element.evaluate("img => PMTArtworkPalette.inspect(img)")
    assert len(requests) == 1
    assert image_element.evaluate("img => img.crossOrigin") is None


def test_description_untrusted_links_and_settings_notice_removed(page, browser_server):
    value = '**Bold** <img src=x onerror="alert(1)"> (Source: [unsafe](javascript:alert))'
    row = _seed(page, browser_server, "books", description=value)
    _switch(page, "books")
    _card(page, row).locator("[data-open-music]").click()
    expect(page.locator("#music-description img")).to_have_count(0)
    edit_panel(page, "metadata")
    expect(page.locator("#music-catalog-summary a")).to_have_count(0)
    expect(page.locator("#music-save")).to_be_disabled()
    page.locator("#music-editor .dialog-close").click()
    page.locator("#open-settings").click()
    expect(page.locator("#settings-intro")).to_have_count(0)
    page.reload(wait_until="networkidle")
    page.locator("#open-settings").click()
    expect(page.locator("#settings-intro")).to_have_count(0)
    assert page.evaluate("PMTCollectionTaxonomy.label('R&B')") == "R&B"
    assert page.evaluate("PMTCollectionTaxonomy.label('électronique', 'fr')") == "Électronique"
    assert page.evaluate("PMTCollectionTaxonomy.label('科幻', 'zh-CN')") == "科幻"


def test_touch_music_controls_fit_and_reveal_does_not_move_neighbors(page, browser_server):
    row = _seed(page, browser_server, "music", title="Touch layout " + str(uuid4()))
    context = page.context.browser.new_context(
        viewport={"width": 390, "height": 844},
        has_touch=True,
        is_mobile=True,
        reduced_motion="reduce",
    )
    touch = context.new_page()
    try:
        touch.goto(f"{browser_server}/?view=music_library", wait_until="networkidle")
        touch.locator("#music-query").fill(row["title"])
        expect(touch.locator(".music-card")).to_have_count(1)
        card = _card(touch, row)
        for selector in (".music-heart", ".media-info-button"):
            box, button = card.bounding_box(), card.locator(selector).bounding_box()
            assert button["width"] >= 44 and button["height"] >= 44
            assert button["x"] + button["width"] <= box["x"] + box["width"]
            assert button["y"] + button["height"] <= box["y"] + box["height"]
        touch.evaluate("PMTCollectionSettings.applyPreferences({music_artwork_reveal:true})")
        card = _card(touch, row)
        card.scroll_into_view_if_needed()
        box = card.bounding_box()
        card.locator("[data-reveal-music]").tap()
        expect(card.locator(".music-reveal-panel")).to_be_visible()
        assert card.bounding_box() == box
        card.locator(".media-info-button").tap()
        expect(touch.locator("#music-editor")).to_be_visible()
    finally:
        context.close()


def test_list_removal_conflict_preserves_all_members(page, browser_server):
    row = _seed(page, browser_server, "music")
    created = page.request.post(
        f"{browser_server}/api/music/lists",
        data={"name": str(uuid4()), "album_ids": [row["id"]]},
    ).json()
    _switch(page, "music")
    page.locator('.music-nav[data-view="music_lists"]').click()
    page.locator(f'[data-open-music-list="{created["id"]}"]').click()

    def concurrent_edit(route):
        # Real optimistic conflict: another device writes after the UI's read
        # but before its removal request reaches the API.
        response = page.request.put(
            f"{browser_server}/api/music/lists/{created['id']}",
            data={
                "name": "Changed elsewhere",
                "album_ids": [row["id"]],
                "version": created["version"],
            },
        )
        assert response.ok, response.text()
        route.continue_()

    page.route(
        f"**/api/music/lists/{created['id']}",
        concurrent_edit,
    )
    button = page.locator(f'[data-remove-collection-item="{row["id"]}"]')
    button.click()
    expect(page.locator("#music-state")).to_contain_text("changed elsewhere")
    expect(button).to_be_enabled()
    expect(_card(page, row)).to_be_visible()
    stored = page.request.get(f"{browser_server}/api/music/lists").json()["items"]
    assert next(item for item in stored if item["id"] == created["id"])["album_ids"] == [
        row["id"]
    ]
