from __future__ import annotations

import base64
import io
from uuid import uuid4

import pytest
from PIL import Image

playwright_api = pytest.importorskip("playwright.sync_api")
from test_collections_browser import (  # noqa: E402
    browser_server as browser_server,
)
from test_collections_browser import (  # noqa: E402
    edit_panel,
    edit_tracks,
)
from test_collections_browser import (  # noqa: E402
    page as page,
)


def _seed(page, server, mode, **changes):
    image = io.BytesIO()
    Image.new("RGB", (80, 100), "#762d72").save(image, "PNG")
    body = {
        "title": f"Design fixture {uuid4()}",
        "artist" if mode == "music" else "author": "Synthetic creator",
        "rating": 8.5,
        "genres": ["Fiction" if mode == "books" else "Electronic"],
        "notes": "Private note retained through design changes",
        "artwork_data": "data:image/png;base64," + base64.b64encode(image.getvalue()).decode(),
        **changes,
    }
    endpoint = "albums" if mode == "music" else "entries"
    response = page.request.post(f"{server}/api/{mode}/{endpoint}", data=body)
    assert response.ok, response.text()
    identifier = response.json()["id"]
    return page.request.get(f"{server}/api/{mode}/{endpoint}/{identifier}").json()


def _switch(page, mode):
    page.locator(f'[data-workspace="{mode}"]').click()
    playwright_api.expect(page.locator("html")).to_have_attribute("data-workspace", mode)
    playwright_api.expect(page.locator("#music-content")).to_have_attribute(
        "aria-busy", "false"
    )


def _card(page, row):
    card = page.locator(f'[data-music-id="{row["id"]}"]')
    playwright_api.expect(card).to_be_visible()
    return card


def _artwork_picker(page):
    actions = page.locator("#music-more-actions")
    if not actions.evaluate("node => node.open"):
        actions.locator("summary").click()
    page.locator("#music-browse-artwork").click()


def _assert_painted_action(button):
    playwright_api.expect(button.locator("svg")).to_be_visible()
    painted = button.evaluate(
        """button => {
          const svg = button.querySelector('svg'), use = svg.querySelector('use');
          const buttonRect = button.getBoundingClientRect(), glyphRect = use.getBoundingClientRect();
          const glyphBounds = use.getBBox(), style = getComputedStyle(svg);
          return {button:buttonRect.toJSON(), glyph:glyphRect.toJSON(),
            paintedWidth:glyphBounds.width, paintedHeight:glyphBounds.height,
            color:style.color, opacity:Number(style.opacity), visibility:style.visibility};
        }"""
    )
    assert painted["paintedWidth"] > 0 and painted["paintedHeight"] > 0, painted
    assert painted["glyph"]["width"] > 0 and painted["glyph"]["height"] > 0, painted
    assert painted["opacity"] > 0 and painted["visibility"] == "visible", painted
    assert painted["color"] not in ("transparent", "rgba(0, 0, 0, 0)"), painted
    for start, end in (("left", "right"), ("top", "bottom")):
        assert painted["glyph"][start] >= painted["button"][start] - 1, painted
        assert painted["glyph"][end] <= painted["button"][end] + 1, painted


def test_screen_list_header_controls_share_baseline(page):
    page.locator('.primary-nav [data-view="lists"]').click()
    playwright_api.expect(page.locator("#lists-view")).to_be_visible()
    controls = [
        "#list-scope",
        "#list-sort",
        "#list-sort-direction",
        "#new-list-name",
        "#create-list-form button",
    ]
    # switchView schedules view-in on the next frame. Even reduced motion keeps
    # one brief keyframe; separate remote bbox calls could sample different frames.
    # Finish that view animation, then compare every control in one DOM snapshot.
    rectangles = page.locator("#lists-view").evaluate(
        """async (view, selectors) => {
          await document.fonts.ready;
          await new Promise(resolve => requestAnimationFrame(resolve));
          await Promise.allSettled(view.getAnimations().map(animation => animation.finished));
          return selectors.map(selector => {
            const node = view.querySelector(selector);
            return node ? node.getBoundingClientRect().toJSON() : null;
          });
        }""",
        controls,
    )
    assert all(rect and rect["width"] > 0 and rect["height"] > 0 for rect in rectangles)
    bottoms = [rect["y"] + rect["height"] for rect in rectangles]
    assert max(bottoms) - min(bottoms) <= 1.5, dict(zip(controls, rectangles, strict=True))
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")


@pytest.mark.parametrize("mode", ["music", "books"])
def test_collection_info_only_card_actions_and_rank_readability(page, browser_server, mode):
    row = _seed(page, browser_server, mode)
    _switch(page, mode)
    card = _card(page, row)
    playwright_api.expect(card.locator(".music-rating")).to_have_count(0)
    playwright_api.expect(card.locator(".status-chip")).to_be_visible()
    if mode == "books":
        playwright_api.expect(card.locator(".entry-signals")).to_contain_text("Fiction")
        playwright_api.expect(card.locator(".entry-signals")).not_to_contain_text("Scripted")
    card.locator(".music-cover-button").click()
    playwright_api.expect(page.locator("#music-editor")).to_be_hidden()
    card.locator("h3").click()
    playwright_api.expect(page.locator("#music-editor")).to_be_hidden()
    for action in ("[data-favorite-music]", "[data-open-music]"):
        _assert_painted_action(card.locator(action))
        assert card.locator(action).evaluate(
            """button => {
              const a = button.getBoundingClientRect();
              const b = button.querySelector('svg').getBoundingClientRect();
              return Math.abs((a.x + a.width/2) - (b.x + b.width/2)) < 1.1
                && Math.abs((a.y + a.height/2) - (b.y + b.height/2)) < 1.1;
            }"""
        ), "The heart and information icons must be centered within their targets."
    card.locator("[data-open-music]").click()
    playwright_api.expect(page.locator('[data-collection-panel="details"]')).to_be_visible()
    playwright_api.expect(page.locator("#music-editor")).to_contain_text(row["title"])
    playwright_api.expect(page.locator("#music-form")).to_be_visible()
    playwright_api.expect(page.locator("#music-save")).to_be_disabled()
    page.locator("#music-editor .dialog-close").click()
    page.locator('.music-nav[data-view="music_rankings"]').click()
    card = _card(page, row)
    playwright_api.expect(card.locator(".music-rating")).to_contain_text("8.5")
    rank = card.locator(".music-rank")
    playwright_api.expect(rank).to_be_visible()
    assert rank.evaluate(
        """node => {
          const color = getComputedStyle(node).backgroundColor;
          return color !== 'rgba(0, 0, 0, 0)' && color !== 'transparent';
        }"""
    )


@pytest.mark.parametrize("mode", ["music", "books"])
def test_quick_add_live_search_is_explicit_and_does_not_create_on_selection(
    page, browser_server, mode
):
    identifier = str(uuid4()) if mode == "music" else "OL987654321M"
    creator = "artist" if mode == "music" else "author"
    payload = {
        "provider_id": identifier,
        "title": f"Search choice {uuid4()}",
        creator: "Synthetic provider creator",
        "year": 2024,
        "genres": ["Fixture genre"],
        "tracks": [],
        "release_type" if mode == "music" else "book_format": "album"
        if mode == "music"
        else "book",
    }
    page.route(
        f"**/api/{mode}/search?*", lambda route: route.fulfill(json={"results": [payload]})
    )
    page.route(
        f"**/api/{mode}/metadata/{identifier}", lambda route: route.fulfill(json=payload)
    )
    _switch(page, mode)
    endpoint = "albums" if mode == "music" else "entries"
    before = page.request.get(f"{browser_server}/api/{mode}/{endpoint}").json()["total"]
    playwright_api.expect(page.locator("#music-add")).to_have_count(0)
    page.locator("#quick-add-shortcut").click()
    playwright_api.expect(page.locator("#music-search-dialog")).to_be_visible()
    playwright_api.expect(page.locator("#music-editor")).to_be_hidden()
    playwright_api.expect(page.locator("#music-manual-add")).to_be_hidden()
    with page.expect_response(lambda response: f"/api/{mode}/search?" in response.url):
        page.locator('#music-search-form [name="query"]').fill("Search choice")
    result = page.locator("[data-music-result]")
    playwright_api.expect(result).to_contain_text(payload["title"])
    result.click()
    playwright_api.expect(page.locator("#music-search-dialog")).to_be_hidden()
    playwright_api.expect(page.locator("#music-editor")).to_be_visible()
    assert page.request.get(f"{browser_server}/api/{mode}/{endpoint}").json()["total"] == before
    playwright_api.expect(page.locator("#music-title")).to_have_value(payload["title"])
    page.locator("#music-save").click()
    playwright_api.expect(page.locator("#music-editor")).to_be_hidden()
    assert (
        page.request.get(f"{browser_server}/api/{mode}/{endpoint}").json()["total"]
        == before + 1
    )


def test_collection_appearance_settings_are_independent_and_persist(page, browser_server):
    defaults = {
        f"{mode}_artwork_{option}": False
        for mode in ("music", "books")
        for option in ("tint", "full_color", "reveal")
    }
    response = page.request.put(f"{browser_server}/api/settings/general", data=defaults)
    assert response.ok
    page.reload(wait_until="networkidle")
    _switch(page, "music")
    page.locator("#open-settings").click()
    page.locator('[data-settings-tab="music"]').click()
    for selector in ("music-artwork-tint", "music-artwork-full-color", "music-artwork-reveal"):
        with page.expect_response(
            lambda response: (
                response.url.endswith("/api/settings/general")
                and response.request.method == "PUT"
            )
        ) as saved:
            page.locator(f"#{selector}").check()
        assert saved.value.ok
    playwright_api.expect(page.locator("#music-artwork-tint")).to_be_disabled()
    playwright_api.expect(page.locator("#music-artwork-full-color")).to_be_disabled()
    page.locator('[data-settings-tab="books"]').click()
    playwright_api.expect(page.locator("#books-artwork-reveal")).not_to_be_checked()
    playwright_api.expect(page.locator("#books-artwork-tint")).to_be_enabled()
    playwright_api.expect(page.locator("html")).to_have_attribute("data-workspace", "music")
    values = page.request.get(f"{browser_server}/api/settings/general").json()
    assert values["music_artwork_reveal"] is True
    assert values["books_artwork_reveal"] is False
    page.reload(wait_until="networkidle")
    page.locator("#open-settings").click()
    page.locator('[data-settings-tab="music"]').click()
    playwright_api.expect(page.locator("#music-artwork-reveal")).to_be_checked()
    playwright_api.expect(page.locator("#music-artwork-tint")).to_be_disabled()
    page.request.put(f"{browser_server}/api/settings/general", data=defaults)


@pytest.mark.parametrize("mode", ["music", "books"])
def test_artwork_reveal_does_not_open_details_or_reflow_neighbors(page, browser_server, mode):
    first = _seed(
        page,
        browser_server,
        mode,
        **({"page_count": 300, "current_page": 10} if mode == "books" else {}),
    )
    second = _seed(page, browser_server, mode)
    page.request.put(
        f"{browser_server}/api/settings/general",
        data={f"{mode}_artwork_reveal": True},
    )
    view = "music_library" if mode == "music" else "book_library"
    page.goto(f"{browser_server}/?view={view}", wait_until="networkidle")
    card = _card(page, first)
    neighbor = _card(page, second)
    trigger = card.locator("[data-reveal-music]")
    playwright_api.expect(trigger).to_have_attribute("aria-expanded", "false")
    original = neighbor.bounding_box()
    card.hover()
    playwright_api.expect(trigger).to_have_attribute("aria-expanded", "true")
    for action in ("[data-favorite-music]", "[data-open-music]"):
        _assert_painted_action(card.locator(action))
    if mode == "books":
        playwright_api.expect(card).to_contain_text("10/300")
    playwright_api.expect(page.locator("#music-editor")).to_be_hidden()
    assert neighbor.bounding_box() == original
    page.mouse.move(0, 0)
    playwright_api.expect(trigger).to_have_attribute("aria-expanded", "false")
    trigger.focus()
    trigger.press("Enter")
    playwright_api.expect(trigger).to_have_attribute("aria-expanded", "true")
    playwright_api.expect(page.locator("#music-editor")).to_be_hidden()
    trigger.press("Escape")
    playwright_api.expect(trigger).to_have_attribute("aria-expanded", "false")
    page.locator('.music-nav[data-view="music_rankings"]').click()
    card = _card(page, first)
    playwright_api.expect(card.locator("[data-reveal-music]")).to_have_count(0)
    playwright_api.expect(card.locator(".music-rating")).to_be_visible()
    playwright_api.expect(card.locator("[data-open-music]")).to_be_visible()


def test_track_overview_numbers_disc_and_editing_are_separate(page, browser_server):
    row = _seed(
        page,
        browser_server,
        "music",
        tracks=[
            {"disc": disc, "position": position, "title": f"Disc {disc} track {position}"}
            for disc, position in [(1, 1), (1, 2), (1, 3), (2, 1), (2, 2)]
        ],
    )
    _switch(page, "music")
    _card(page, row).locator("[data-open-music]").click()
    edit_panel(page, "details")
    playwright_api.expect(page.locator('[data-collection-tab="tracks"]')).to_have_count(0)
    preview = page.locator("#music-track-preview")
    playwright_api.expect(preview).to_be_visible()
    assert preview.locator(".collection-track-number").all_text_contents() == [
        "1",
        "2",
        "3",
        "1",
        "2",
    ]
    playwright_api.expect(page.locator("#music-track-editor")).to_be_hidden()
    playwright_api.expect(page.locator("#music-add-track")).to_be_hidden()
    assert preview.locator("input").count() == 0
    edit_tracks(page)
    playwright_api.expect(page.locator("#music-track-editor")).to_be_visible()
    page.locator("#music-track-rows .track-title").nth(1).fill("Revised track title")
    page.locator("#music-save").click()
    playwright_api.expect(page.locator("#music-editor")).to_be_hidden()
    saved = page.request.get(f"{browser_server}/api/music/albums/{row['id']}").json()
    assert [track["id"] for track in saved["tracks"]] == [
        track["id"] for track in row["tracks"]
    ]
    assert [track["position"] for track in saved["tracks"]] == [1, 2, 3, 1, 2]
    assert saved["notes"] == row["notes"]
    assert saved["rating"] == row["rating"]


@pytest.mark.parametrize(
    "mode,width,height", [("books", 1440, 900), ("music", 1440, 900), ("books", 390, 844)]
)
def test_collection_overview_fit_and_short_edit_preserves_data(
    page, browser_server, mode, width, height
):
    row = _seed(
        page,
        browser_server,
        mode,
        genres=["Fiction, science fiction, general"],
        subgenres=["Space, exploration"],
        tags=["Keep, label"],
        **(
            {
                "description": "A detailed synopsis. " * 200,
                "page_count": 400,
                "current_page": 53,
            }
            if mode == "books"
            else {
                "tracks": [
                    {"title": f"Track {i}", "position": i, "duration_ms": 123456 + i}
                    for i in range(1, 31)
                ]
            }
        ),
    )
    page.set_viewport_size({"width": width, "height": height})
    _switch(page, mode)
    _card(page, row).locator("[data-open-music]").click()
    overview = page.locator("#music-editor")
    playwright_api.expect(overview).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    geometry = overview.evaluate(
        """dialog => { const r = dialog.getBoundingClientRect(); return {
          width: r.width, right:r.right, y:r.y, bottom:r.bottom,
          overflowX:dialog.scrollWidth-dialog.clientWidth,
          overflowY:dialog.scrollHeight-dialog.clientHeight
        }; }"""
    )
    assert geometry["right"] <= width + 1 and geometry["y"] >= 0
    assert geometry["bottom"] <= height + 1 and geometry["overflowX"] <= 1, overview.evaluate(
        """dialog => [...dialog.querySelectorAll('*')].filter(node => {
          const r = node.getBoundingClientRect(), d = dialog.getBoundingClientRect();
          return r.width > 0 && (r.right > d.right || r.left < d.left);
        }).map(node => ({id:node.id, tag:node.tagName, class:node.className,
          width:node.getBoundingClientRect().width,
          right:node.getBoundingClientRect().right})).slice(0,15)"""
    )
    if width >= 1000:
        assert geometry["overflowY"] <= 1, (
            "The overview should scroll internally, not move the whole dialog."
        )
    save_bounds = page.locator("#music-save").bounding_box()
    assert save_bounds["y"] + save_bounds["height"] <= geometry["bottom"] + 1, (
        "Save must remain visible outside the content scroll region"
    )
    edit_panel(page)
    playwright_api.expect(page.locator("#music-save")).to_be_disabled()
    page.locator('#music-form [name="notes"]').fill("New private note")
    page.locator("#music-save").click()
    playwright_api.expect(overview).to_be_hidden()
    endpoint = "albums" if mode == "music" else "entries"
    saved = page.request.get(f"{browser_server}/api/{mode}/{endpoint}/{row['id']}").json()
    assert saved["notes"] == "New private note"
    for key in (
        "title",
        "rating",
        "genres",
        "subgenres",
        "tags",
        "artwork_data",
        "provider_id",
    ):
        assert saved[key] == row[key]
    if mode == "books":
        assert saved["current_page"] == 53 and saved["page_count"] == 400
        assert saved["description"] == row["description"]
    else:
        assert saved["tracks"] == row["tracks"]


@pytest.mark.parametrize("mode", ["music", "books"])
def test_alternate_artwork_is_previewed_and_preserves_all_other_fields(
    page, browser_server, mode
):
    provider_id = str(uuid4()) if mode == "music" else "OL22334455M"
    row = _seed(
        page,
        browser_server,
        mode,
        provider_id=provider_id,
        subgenres=["Fixture subgenre"],
        tags=["Keep this tag"],
        **(
            {"page_count": 250, "current_page": 46}
            if mode == "books"
            else {"tracks": [{"title": "Retained recording", "position": 1}]}
        ),
    )
    endpoint = "albums" if mode == "music" else "entries"
    artwork_url = "https://covers.openlibrary.org/b/id/13579-L.jpg?default=false"
    page.route(
        f"**/api/{mode}/{endpoint}/{row['id']}/artwork-options",
        lambda route: route.fulfill(
            json={
                "options": [
                    {
                        "url": artwork_url,
                        "thumbnail_url": artwork_url,
                        "label": "Alternate fixture cover",
                        "source": "Open Library",
                    }
                ],
                "warning": None,
            }
        ),
    )
    image = io.BytesIO()
    Image.new("RGB", (20, 30), "#195434").save(image, "PNG")
    page.route(
        "https://covers.openlibrary.org/**",
        lambda route: route.fulfill(content_type="image/png", body=image.getvalue()),
    )
    _switch(page, mode)
    _card(page, row).locator("[data-open-music]").click()
    _artwork_picker(page)
    playwright_api.expect(page.locator('[name="collection-artwork"]')).to_be_visible()
    page.locator("#music-artwork-dialog .dialog-close").click()
    edit_panel(page)
    playwright_api.expect(page.locator("#music-save")).to_be_disabled()
    untouched = page.request.get(f"{browser_server}/api/{mode}/{endpoint}/{row['id']}").json()
    assert untouched == row
    edit_panel(page, "details")
    _artwork_picker(page)
    page.locator('[name="collection-artwork"]').check()
    playwright_api.expect(page.locator("#music-artwork-dialog")).to_be_visible()
    page.locator("#music-artwork-apply").click()
    playwright_api.expect(page.locator("#music-artwork-dialog")).to_be_hidden()
    playwright_api.expect(page.locator("#music-save")).to_be_enabled()
    # Choosing a cover is still only a draft until Save, exactly like metadata edits.
    assert page.request.get(f"{browser_server}/api/{mode}/{endpoint}/{row['id']}").json() == row
    page.locator("#music-save").click()
    playwright_api.expect(page.locator("#music-editor")).to_be_hidden()
    saved = page.request.get(f"{browser_server}/api/{mode}/{endpoint}/{row['id']}").json()
    assert saved["artwork_data"] is None
    assert saved["artwork_url"] == artwork_url
    for key in (
        "title",
        "rating",
        "status",
        "genres",
        "subgenres",
        "notes",
        "tags",
        "provider_id",
    ):
        assert saved[key] == row[key]
    if mode == "music":
        assert saved["tracks"] == row["tracks"]
    else:
        assert saved["current_page"] == 46 and saved["page_count"] == 250


def _screen_reference(page, browser_server):
    title = f"Screen reference {uuid4()}"
    response = page.request.post(
        f"{browser_server}/api/entries/manual",
        data={
            "canonical_title": title,
            "media_type": "movie",
            "release_year": 2024,
            "status": "plan_to_watch",
            "provider_genres": ["Drama"],
            "overview": "A short synthetic description for visual parity.",
        },
    )
    assert response.ok, response.text()
    identifier = response.json()["entry"]["id"]
    page.reload(wait_until="networkidle")
    page.locator("#library-toolbar-search").fill(title)
    playwright_api.expect(page.locator("#library [data-entry]")).to_have_count(1)
    card = page.locator(f'#library [data-entry="{identifier}"]')
    playwright_api.expect(card).to_be_visible()
    return card


def _tile_geometry(card):
    return card.evaluate(
        """node => {
          const rect = element => element.getBoundingClientRect().toJSON();
          const textStyle = element => {
            const s = getComputedStyle(element);
            return {size:s.fontSize, weight:s.fontWeight, lineHeight:s.lineHeight};
          };
          const button = selector => {
            const b = node.querySelector(selector);
            return {rect:rect(b), style:textStyle(b)};
          };
          return {card:rect(node), poster:rect(node.querySelector('.poster')),
            copy:rect(node.querySelector('.entry-copy')),
            signals:rect(node.querySelector('.entry-signals')),
            actions:rect(node.querySelector('.entry-actions')),
            titleStyle:textStyle(node.querySelector('h3')),
            statusStyle:textStyle(node.querySelector('.status-chip')),
            favorite:button('.favorite-toggle'), info:button('.media-info-button'),
            padding:getComputedStyle(node).padding, borderRadius:getComputedStyle(node).borderRadius};
        }"""
    )


@pytest.mark.parametrize(
    "mode,width", [("music", 1440), ("books", 1440), ("music", 390), ("books", 390)]
)
def test_collection_cards_match_rendered_screen_layout(page, browser_server, mode, width):
    row = _seed(page, browser_server, mode, title=f"Collection reference {uuid4()}")
    page.set_viewport_size({"width": width, "height": 1000})
    reference = _tile_geometry(_screen_reference(page, browser_server))
    _switch(page, mode)
    # Different fixture populations can stretch a CSS-grid row to a taller
    # neighbor. Compare one card per workspace, not unrelated neighboring rows.
    page.locator("#music-query").fill(row["title"])
    playwright_api.expect(page.locator(".music-card")).to_have_count(1)
    actual = _tile_geometry(_card(page, row))
    assert actual["poster"]["right"] < actual["copy"]["left"]
    assert actual["poster"]["top"] <= actual["copy"]["top"] + 1
    assert actual["signals"]["left"] >= actual["copy"]["left"] - 1
    assert actual["actions"]["left"] >= actual["poster"]["right"]
    assert actual["favorite"]["rect"]["bottom"] <= actual["info"]["rect"]["top"] + 1
    for part in ("card", "poster"):
        for dimension in ("width", "height"):
            if mode == "music" and dimension == "height":
                # Album art intentionally uses a square rather than a film frame.
                if part == "poster":
                    assert actual[part]["height"] == pytest.approx(actual[part]["width"], abs=1)
                else:
                    assert actual[part]["height"] <= reference[part]["height"] + 1.5
                continue
            assert actual[part][dimension] == pytest.approx(
                reference[part][dimension], abs=1.5
            ), {
                "part": part,
                "dimension": dimension,
                "actual": {
                    key: {metric: actual[key][metric] for metric in ("width", "height")}
                    for key in ("card", "poster", "copy", "signals", "actions")
                },
                "reference": {
                    key: {metric: reference[key][metric] for metric in ("width", "height")}
                    for key in ("card", "poster", "copy", "signals", "actions")
                },
            }
    for part in ("favorite", "info"):
        for dimension in ("width", "height"):
            assert actual[part]["rect"][dimension] == pytest.approx(
                reference[part]["rect"][dimension], abs=1
            )
    for style in ("titleStyle", "statusStyle", "padding", "borderRadius"):
        assert actual[style] == reference[style], (style, actual[style], reference[style])
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")


@pytest.mark.parametrize("mode", ["music", "books"])
def test_legacy_collected_is_not_offered_or_rewritten_by_notes_edit(page, browser_server, mode):
    row = _seed(page, browser_server, mode, status="collected")
    _switch(page, mode)
    card = _card(page, row)
    assert "Collected" not in card.inner_text()
    card.locator("[data-open-music]").click()
    assert "Collected" not in page.locator("#music-editor").inner_text()
    edit_panel(page, "notes")
    page.locator('#music-form [name="notes"]').fill("Legacy note updated")
    page.locator("#music-save").click()
    playwright_api.expect(page.locator("#music-editor")).to_be_hidden()
    endpoint = "albums" if mode == "music" else "entries"
    stored = page.request.get(f"{browser_server}/api/{mode}/{endpoint}/{row['id']}").json()
    assert stored["status"] == "collected"
    assert stored["notes"] == "Legacy note updated"
    assert stored["rating"] == row["rating"]


def test_book_taxonomy_is_concise_without_rewriting_provider_labels(page, browser_server):
    genres = [
        "Fiction, science fiction, general",
        "Dune (Imaginary place)",
        "British and Irish fiction (fictional works by one author)",
        "Bombing of Dresden, Germany, 1945",
    ]
    subgenres = ["Fiction, Romance, Historical, Regency"]
    row = _seed(page, browser_server, "books", genres=genres, subgenres=subgenres)
    _switch(page, "books")
    card = _card(page, row)
    text = card.locator(".entry-signals").inner_text()
    assert "Science fiction" in text and "Regency romance" in text
    for raw in genres + subgenres:
        assert raw not in text
    card.locator("[data-open-music]").click()
    playwright_api.expect(page.locator("#music-overview")).to_contain_text("Science fiction")
    playwright_api.expect(page.locator("#music-overview")).to_contain_text("Regency romance")
    edit_panel(page, "metadata")
    page.locator("#music-raw-provider-terms").locator("..").locator(":scope > summary").click()
    for raw in genres + subgenres:
        playwright_api.expect(page.locator("#music-raw-provider-terms")).to_contain_text(raw)
    edit_panel(page, "notes")
    page.locator('#music-form [name="notes"]').fill("Taxonomy is display-only")
    page.locator("#music-save").click()
    playwright_api.expect(page.locator("#music-editor")).to_be_hidden()
    saved = page.request.get(f"{browser_server}/api/books/entries/{row['id']}").json()
    assert saved["genres"] == genres and saved["subgenres"] == subgenres
    exported = page.request.get(f"{browser_server}/api/exports/book-collection.json").json()
    # Export must retain the actual source labels, not the shortened display taxonomy.
    exported_row = next(book for book in exported["books"] if book["id"] == row["id"])
    assert exported_row["genres"] == genres and exported_row["subgenres"] == subgenres


@pytest.mark.parametrize(
    "mode,width", [("music", 1440), ("books", 1440), ("books", 900), ("music", 390)]
)
def test_collection_library_controls_share_one_screen_style_toolbar(page, mode, width):
    page.set_viewport_size({"width": width, "height": 1000})
    reference = page.locator("#library-view .library-toolbar").evaluate(
        "node => { const s = getComputedStyle(node); return {radius:s.borderRadius, padding:s.padding, position:s.position}; }"
    )
    _switch(page, mode)
    toolbar = page.locator(".music-toolbar")
    selectors = [
        "#music-query",
        "#music-refresh",
        "#music-toggle-filters",
        "#music-sort",
        "#music-sort-direction",
        "#music-page-size",
    ]
    geometry = toolbar.evaluate(
        """(node, selectors) => {
          const rect = node.getBoundingClientRect(), s = getComputedStyle(node);
          return {toolbar:rect.toJSON(), style:{radius:s.borderRadius, padding:s.padding, position:s.position},
            controls:selectors.map(selector => {
              const control = node.querySelector(selector);
              return control ? control.getBoundingClientRect().toJSON() : null;
            })};
        }""",
        selectors,
    )
    assert geometry["style"] == reference
    for selector, rect in zip(selectors, geometry["controls"], strict=True):
        assert rect and rect["width"] > 0 and rect["height"] > 0, selector
        assert rect["left"] >= geometry["toolbar"]["left"] - 1, selector
        assert rect["right"] <= geometry["toolbar"]["right"] + 1, selector
        assert rect["top"] >= geometry["toolbar"]["top"] - 1, selector
        assert rect["bottom"] <= geometry["toolbar"]["bottom"] + 1, selector
    playwright_api.expect(page.locator("#music-filter-options")).to_be_hidden()
    page.locator("#music-toggle-filters").click()
    playwright_api.expect(page.locator("#music-filter-options")).to_be_visible()
    playwright_api.expect(page.locator("#music-toggle-filters")).to_have_attribute(
        "aria-expanded", "true"
    )
    assert "collected" not in page.locator("#music-status option").evaluate_all(
        "nodes => nodes.map(node => node.value)"
    )
    page.locator("#music-toggle-filters").click()
    endpoint = "albums" if mode == "music" else "entries"
    with page.expect_response(
        lambda response: (
            f"/api/{mode}/{endpoint}?" in response.url and "page_size=48" in response.url
        )
    ) as resized:
        page.locator("#music-page-size").select_option("48")
    assert resized.value.ok
    with page.expect_response(
        lambda response: (
            f"/api/{mode}/{endpoint}?" in response.url and "direction=asc" in response.url
        )
    ) as reordered:
        page.locator("#music-sort-direction").click()
    assert reordered.value.ok
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")


def _detail_geometry(dialog):
    return dialog.evaluate(
        """async node => {
          await document.fonts.ready;
          await new Promise(resolve => requestAnimationFrame(resolve));
          await Promise.allSettled(node.getAnimations().map(animation => animation.finished));
          const rect = selector => node.querySelector(selector).getBoundingClientRect().toJSON();
          const style = getComputedStyle(node.querySelector('.dialog-tabs [role="tab"]'));
          return {dialog:node.getBoundingClientRect().toJSON(), art:rect('.entry-dialog-art'),
            content:rect('.entry-dialog-content'), tabs:rect('.dialog-tabs'),
            tabStyle:{fontSize:style.fontSize, fontWeight:style.fontWeight, borderRadius:style.borderRadius}};
        }"""
    )


@pytest.mark.parametrize("mode", ["music", "books"])
def test_screen_artwork_flags_never_transform_collection_cards(page, browser_server, mode):
    row = _seed(page, browser_server, mode)
    _switch(page, mode)
    card = _card(page, row)
    colors = """node => {
      const s = getComputedStyle(node);
      return {background:s.backgroundColor, image:s.backgroundImage,
        padding:s.padding, width:node.getBoundingClientRect().width};
    }"""
    reference = card.evaluate(colors)
    response = page.request.put(
        f"{browser_server}/api/settings/general",
        data={
            "media_artwork_tint": True,
            "media_artwork_full_color": True,
            "artwork_reveal": True,
        },
    )
    assert response.ok
    page.reload(wait_until="networkidle")
    card = _card(page, row)
    assert card.evaluate(colors) == reference
    playwright_api.expect(
        card.locator(".pmt-artwork-panel, [data-reveal-music]")
    ).to_have_count(0)
    playwright_api.expect(card.locator(".entry-copy")).to_be_visible()
    assert page.request.put(
        f"{browser_server}/api/settings/general",
        data={f"{mode}_artwork_reveal": True},
    ).ok
    page.reload(wait_until="networkidle")
    card = _card(page, row)
    playwright_api.expect(card.locator(".pmt-artwork-panel")).to_have_count(0)
    assert (
        card.locator(".music-reveal-panel").evaluate("node => getComputedStyle(node).position")
        == "absolute"
    )
    card.hover()
    playwright_api.expect(card.locator("[data-reveal-music]")).to_have_attribute(
        "aria-expanded", "true"
    )
    card.locator("[data-open-music]").click()
    playwright_api.expect(page.locator("#music-editor")).to_be_visible()
    playwright_api.expect(page.locator("#music-save")).to_be_disabled()


@pytest.mark.parametrize("mode,width", [("music", 1440), ("books", 1440), ("books", 900)])
def test_collection_details_follow_screen_art_and_tab_layout(page, browser_server, mode, width):
    row = _seed(page, browser_server, mode)
    page.set_viewport_size({"width": width, "height": 1000})
    screen = _screen_reference(page, browser_server)
    screen.locator("[data-details]").click()
    playwright_api.expect(page.locator("#entry-dialog")).to_be_visible()
    reference = _detail_geometry(page.locator("#entry-dialog"))
    page.locator("#entry-dialog .dialog-close").click()
    _switch(page, mode)
    _card(page, row).locator("[data-open-music]").click()
    actual = _detail_geometry(page.locator("#music-editor"))
    assert actual["art"]["right"] <= actual["content"]["left"]
    assert actual["tabs"]["left"] >= actual["content"]["left"] - 1
    assert actual["art"]["top"] <= actual["tabs"]["top"] + 1
    for part in ("dialog", "art"):
        assert actual[part]["width"] == pytest.approx(reference[part]["width"], abs=1.5), (
            part,
            actual,
            reference,
        )
    assert actual["tabStyle"] == reference["tabStyle"]
    tabs = page.locator("[data-collection-tab]:visible")
    assert tabs.evaluate_all("nodes => nodes.map(node => node.dataset.collectionTab)") == [
        "details",
        "notes",
        "genres",
        "metadata",
    ] + (["contents"] if mode == "books" else [])
    for panel in ("notes", "genres", "metadata", "details"):
        edit_panel(page, panel)
        playwright_api.expect(
            page.locator(f'[data-collection-panel="{panel}"]')
        ).to_be_visible()
        playwright_api.expect(page.locator("#music-save")).to_be_visible()
        playwright_api.expect(page.locator("#music-save")).to_be_disabled()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
