"""Handoff 063737: scoped catalog selection, shared import and compact UI."""

import json
from uuid import uuid4

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect
from test_collection_design import _card, _seed, _switch
from test_collections_browser import browser_server as browser_server
from test_collections_browser import edit_panel
from test_collections_browser import page as page

pytestmark = pytest.mark.parametrize("page", ["chromium", "webkit"], indirect=True)


def test_book_tracking_alignment_and_edition_only_in_metadata(page, browser_server):
    row = _seed(
        page,
        browser_server,
        "books",
        current_page=12,
        completion_count=2,
        provider_id=f"OL{uuid4().int % 10**20}M",
        edition_info={"name": "Test edition"},
    )
    _switch(page, "books")
    _card(page, row).locator("[data-open-music]").click()
    expect(page.locator("#music-edition-info")).to_be_hidden()
    positions = page.locator(
        '#music-panel-details input[name="current_page"], #music-panel-details input[name="completion_count"]'
    ).evaluate_all("items => items.map(item => item.getBoundingClientRect().y)")
    assert abs(positions[0] - positions[1]) < 2
    edit_panel(page, "metadata")
    expect(page.locator("#music-edition-info")).to_contain_text("Test edition")
    expect(page.locator("#music-choose-edition")).to_be_visible()
    expect(page.locator("#music-save")).to_be_disabled()


def test_book_search_work_then_edition_back_and_pending_save(page, browser_server):
    _switch(page, "books")
    work = {
        "provider_id": "OL1M",
        "work_id": "OL1W",
        "title": "A chosen book",
        "author": "Original author",
        "original_year": 1950,
    }
    edition = {
        **work,
        "provider_id": "OL2M",
        "year": 2004,
        "page_count": 420,
        "publisher": "Chosen Press",
        "edition": "Paperback · Chosen Press",
        "language": "eng",
        "book_format": "paperback",
    }
    seen = []
    page.route("**/api/books/search?*", lambda route: route.fulfill(json={"results": [work]}))
    page.route(
        "**/api/books/works/OL1W/editions?*",
        lambda route: (
            seen.append(route.request.url),
            route.fulfill(json={"results": [edition]}),
        ),
    )
    page.route(
        "**/api/books/metadata/OL2M",
        lambda route: route.fulfill(
            json={
                k: v
                for k, v in edition.items()
                if k not in {"edition", "language", "original_year"}
            }
        ),
    )
    page.locator("#quick-add-shortcut").click()
    page.locator('#music-search-form [name="query"]').fill("A chosen book")
    page.locator('#music-search-form button[type="submit"]').click()
    expect(page.locator("[data-book-work]")).to_have_count(1)
    expect(page.locator("#music-search-results")).not_to_contain_text("Chosen Press")
    page.locator("[data-book-work]").click()
    expect(page.locator("#music-search-results")).to_contain_text("Chosen Press")
    expect(page.locator("#music-edition-title")).to_have_text(work["title"])
    assert "preferred=OL1M" in seen[0]
    page.locator("#music-back-book-search").click()
    expect(page.locator("[data-book-work]")).to_have_count(1)
    page.locator("[data-book-work]").click()
    page.locator('[data-music-result="OL2M"]').click()
    expect(page.locator("#music-editor")).to_be_visible()
    expect(page.locator('#music-form [name="year"]')).to_have_value("2004")
    expect(page.locator('#music-form [name="page_count"]')).to_have_value("420")
    expect(page.locator('#music-form [name="release_type"]')).to_have_value("paperback")
    # Choosing is a draft, not an import or a save.
    assert (
        page.request.get(f"{browser_server}/api/books/entries?q=A+chosen+book").json()["total"]
        == 0
    )
    page.locator("#music-editor .dialog-close").click()


@pytest.mark.parametrize("mode", ["music", "books"])
def test_reading_listening_ignores_hidden_library_filters(page, browser_server, mode):
    row = _seed(
        page,
        browser_server,
        mode,
        status="reading" if mode == "books" else "listening",
        rating=None,
        favorite=False,
    )
    _switch(page, mode)
    page.locator("#music-query").fill("No matching items")
    page.locator("#music-sort").select_option("rating")
    page.locator(".music-nav[data-view=music_listening]").click()
    expect(page.locator("#music-filters")).to_be_hidden()
    expect(_card(page, row)).to_be_visible()
    expect(page.locator(".watching-heading-actions #music-refresh")).to_be_visible()
    expect(page.locator("#music-updated")).to_be_hidden()
    page.locator("#music-listening-scope select").select_option("plan_to_listen")
    expect(page.locator(f'[data-music-id="{row["id"]}"]')).to_have_count(0)
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    expect(page.locator("#music-refresh")).to_be_visible()
    page.locator(".music-nav[data-view=music_library]").click()
    expect(page.locator("#music-filters")).to_be_visible()
    expect(page.locator("#music-query")).to_have_value("No matching items")


def test_unified_import_choice_prompt_and_wrong_domain_safety(page, browser_server):
    page.locator("#open-settings").click()
    page.locator('[data-settings-tab="data"]').click()
    screen_prompt = page.locator("#ai-import-prompt").inner_text()
    for domain, marker in [("books", "pmt-book-collection"), ("music", "pmt-music-collection")]:
        page.locator("#import-prompt-mode").select_option(domain)
        expect(page.locator("#ai-import-prompt")).to_contain_text(marker)
        expect(page.locator("#ai-import-prompt")).to_contain_text("collected for unknown")
    page.locator("#import-prompt-mode").select_option("screen")
    assert page.locator("#ai-import-prompt").inner_text() == screen_prompt
    page.locator("#open-import").click()
    page.locator('[data-import-domain="books"]').click()
    document = {
        "format": "pmt-music-collection",
        "version": 1,
        "albums": [
            {
                "id": str(uuid4()),
                "title": "Imported album " + str(uuid4()),
                "artist": "Artist",
                "status": "collected",
            }
        ],
        "lists": [],
    }
    file = {
        "name": "albums.json",
        "mimeType": "application/json",
        "buffer": json.dumps(document).encode(),
    }
    page.locator("#music-import-file").set_input_files(file)
    expect(page.locator("#music-import-status")).to_contain_text("different collection")
    expect(page.locator("#music-import-confirm")).to_be_hidden()
    page.locator("#collection-import-dialog .dialog-close").click()
    expect(page.locator("#settings-dialog")).to_be_visible()
    page.locator("#open-import").click()
    page.locator('[data-import-domain="music"]').click()
    page.locator("#music-import-file").set_input_files(file)
    expect(page.locator("#music-import-status")).to_contain_text("1 new releases")
    title = document["albums"][0]["title"]
    assert (
        page.request.get(f"{browser_server}/api/music/albums", params={"q": title}).json()[
            "total"
        ]
        == 0
    )
    page.locator("#music-import-confirm").click()
    expect(page.locator("#music-import-status")).to_contain_text(
        "Existing entries were not overwritten"
    )
    assert (
        page.request.get(f"{browser_server}/api/music/albums", params={"q": title}).json()[
            "total"
        ]
        == 1
    )
    assert (
        page.request.get(f"{browser_server}/api/books/entries", params={"q": title}).json()[
            "total"
        ]
        == 0
    )
    page.locator("#collection-import-dialog .dialog-close").click()
    page.locator("#open-import").click()
    page.locator('[data-import-domain="screen"]').click()
    expect(page.locator("#import-dialog")).to_be_visible()


@pytest.mark.parametrize(
    "language,add,list_name,rock",
    [
        ("fr", "Ajouter des genres", "Nom de la liste", "Rock artistique"),
        ("zh-CN", "添加流派", "清单名称", "艺术摇滚"),
    ],
)
def test_missing_translations_and_lowercase_provider_genres(
    page, browser_server, language, add, list_name, rock
):
    row = _seed(
        page, browser_server, "music", genres=["electronic", "art rock"], subgenres=["art rock"]
    )
    _switch(page, "music")
    page.evaluate("language => applyInterfaceLanguage(language)", language)
    _card(page, row).locator("[data-open-music]").click()
    edit_panel(page, "genres")
    expect(page.locator("#music-panel-genres")).to_contain_text(add)
    expect(page.locator("#music-effective-genres")).to_contain_text(rock)
    page.locator("#music-editor .dialog-close").click()
    page.locator(".music-nav[data-view=music_lists]").click()
    expect(page.locator("#music-list-name")).to_have_attribute("placeholder", list_name)
    page.locator(".music-nav[data-view=music_insights]").click()
    expect(page.locator("#music-content")).to_contain_text(rock)
    saved = page.request.get(f"{browser_server}/api/music/albums/{row['id']}").json()
    assert saved["genres"] == row["genres"] and saved["version"] == row["version"]
