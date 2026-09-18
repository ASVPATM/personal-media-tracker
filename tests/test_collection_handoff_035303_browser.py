"""Cross-collection regressions from the 035303 handoff, using synthetic data."""

import base64
import io

import pytest
from PIL import Image

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect
from test_collection_design import _card, _seed, _switch
from test_collections_browser import browser_server as browser_server
from test_collections_browser import edit_panel
from test_collections_browser import page as page


@pytest.mark.parametrize("mode", ["music", "books"])
def test_overrides_counts_settings_and_clean_rankings(page, browser_server, mode):
    row = _seed(
        page,
        browser_server,
        mode,
        genres=["Fantasy" if mode == "books" else "Electronic"],
        completion_count=2,
    )
    _switch(page, mode)
    card = _card(page, row)
    expect(card.locator(".collection-count-chip")).to_have_count(0)
    card.locator("[data-open-music]").click()
    edit_panel(page, "genres")
    expect(page.locator("#music-panel-genres")).not_to_contain_text("Short labels")
    page.locator('[name="genre_removals"]').fill("Fantasy" if mode == "books" else "Electronic")
    page.locator('[name="genre_additions"]').fill("My classification")
    expect(page.locator("#music-effective-genres")).to_contain_text("My classification")
    page.locator("#music-save").click()
    expect(page.locator("#music-editor")).to_be_hidden()
    expect(_card(page, row).locator(".entry-signals")).to_contain_text("My classification")
    page.locator("#open-settings").click()
    page.locator(f'[data-settings-tab="{mode}"]').click()
    panel = page.locator(f'[data-settings-panel="{mode}"]')
    panel.locator('[data-collection-settings-tab="metadata"]').click()
    expect(panel.locator(".collection-provider-copy")).to_be_visible()
    expect(page.locator(f"#{mode}-show-counts")).to_be_hidden()
    panel.locator('[data-collection-settings-tab="appearance"]').click()
    with page.expect_response("**/api/settings/general"):
        page.locator(f"#{mode}-show-counts").check()
    page.locator("#settings-dialog .dialog-close").click()
    expect(_card(page, row).locator(".collection-count-chip")).to_contain_text("2")
    page.locator('.music-nav[data-view="music_rankings"]').click()
    rank = _card(page, row)
    expect(rank.locator(".ranking-scores")).to_be_visible()
    expect(
        rank.locator(
            ".status-chip, .genre-chip, .collection-count-chip, .music-page-progress, .favorite-toggle"
        )
    ).to_have_count(0)
    page.locator('.music-nav[data-view="music_listening"]').click()
    expect(page.locator(".music-toolbar.dashboard-heading")).to_be_visible()
    expect(page.locator("#music-listening-scope")).to_be_visible()
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")


@pytest.mark.parametrize("color,light", [("#fff9d0", True), ("#122036", False)])
def test_reveal_palette_and_page_counter_keep_readable_contrast(
    page, browser_server, color, light
):
    image = io.BytesIO()
    Image.new("RGB", (90, 120), color).save(image, "PNG")
    row = _seed(
        page,
        browser_server,
        "books",
        artwork_data="data:image/png;base64," + base64.b64encode(image.getvalue()).decode(),
        page_count=120,
        current_page=30,
    )
    _switch(page, "books")
    page.evaluate("PMTCollectionSettings.applyPreferences({books_artwork_reveal:true})")
    card = _card(page, row)
    card.hover()
    page.wait_for_function(
        "id => document.querySelector(`[data-music-id='${id}']`).style.getPropertyValue('--reveal-bg') !== ''",
        arg=row["id"],
    )
    colors = card.evaluate(
        """card => { const panel = card.querySelector('.music-reveal-panel'), counter = panel.querySelector('.music-page-progress > span'), p = getComputedStyle(panel), c = getComputedStyle(counter); const s = getComputedStyle(card); return {ink:p.color, countInk:c.color, bg:p.backgroundColor, countBg:c.backgroundColor, borders:[s.borderLeftWidth,s.borderRightWidth,s.borderTopWidth,s.borderBottomWidth]}; }"""
    )
    assert colors["ink"] == ("rgb(17, 24, 32)" if light else "rgb(255, 255, 255)")
    assert colors["countInk"] == colors["ink"]
    assert colors["countBg"] not in ("rgb(255, 255, 255)", "rgba(0, 0, 0, 0)")
    assert colors["borders"] == ["1px"] * 4


def test_short_title_does_not_autosearch_but_explicit_search_works(page):
    _switch(page, "books")
    requests = []
    page.route(
        "**/api/books/search?*",
        lambda route: (requests.append(route.request.url), route.fulfill(json={"results": []})),
    )
    page.locator("#quick-add-shortcut").click()
    page.locator('#music-search-form [name="query"]').fill("It")
    expect(page.locator("#music-search-status")).to_contain_text("press Search")
    assert requests == []
    page.locator('#music-search-form button[type="submit"]').click()
    expect(page.locator("#music-search-status")).to_contain_text("No matches")
    assert len(requests) == 1 and "q=It" in requests[0]


def test_book_edition_change_is_explicit_and_keeps_private_data(page, browser_server):
    row = _seed(
        page,
        browser_server,
        "books",
        provider_id="OL100M",
        work_id="OL999W",  # stale cached association must not choose another work
        year=None,
        page_count=None,
        current_page=20,
        completion_count=4,
    )
    alternative = {
        "provider_id": "OL101M",
        "title": row["title"],
        "author": "Author",
        "year": 2014,
        "page_count": 320,
        "book_format": "paperback",
        "edition": "2014 · Paperback · Publisher",
        "edition_info": {"name": "Second edition", "format": "Paperback"},
        "genres": [],
        "subgenres": [],
        "chapters": [],
    }
    page.route(
        "**/api/books/metadata/OL100M/editions?*",
        lambda route: route.fulfill(json={"results": [alternative]}),
    )
    page.route("**/api/books/metadata/OL101M", lambda route: route.fulfill(json=alternative))
    _switch(page, "books")
    _card(page, row).locator("[data-open-music]").click()
    edit_panel(page, "metadata")
    expect(page.locator("#music-edition-info")).to_contain_text(
        "missing its year or page count"
    )
    page.locator("#music-choose-edition").click()
    expect(page.locator("#music-search-results")).to_contain_text("320")
    page.locator('[data-music-result="OL101M"]').click()
    expect(page.locator("#music-search-dialog")).to_be_hidden()
    assert page.request.get(f"{browser_server}/api/books/entries/{row['id']}").json() == row
    edit_panel(page, "metadata")
    expect(page.locator("#music-edition-info")).to_contain_text("Second edition")
    page.locator("#music-save").click()
    expect(page.locator("#music-editor")).to_be_hidden()
    saved = page.request.get(f"{browser_server}/api/books/entries/{row['id']}").json()
    assert saved["year"] == 2014 and saved["page_count"] == 320
    assert saved["current_page"] == 20 and saved["completion_count"] == 4
    assert saved["notes"] == row["notes"]
