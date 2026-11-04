"""Exercise the visible opt-in/progress/review experience without public traffic."""

import json
from uuid import uuid4

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")
from test_browser_e2e import browser_server as browser_server  # noqa: E402, F401
from test_collections_browser import page as page  # noqa: E402, F401


def open_maintenance(page, domain="music"):
    page.locator("#open-settings").click()
    page.locator(f'[data-settings-tab="{domain}"]').click()
    panel = page.locator(f'[data-settings-panel="{domain}"]')
    panel.locator('[data-collection-settings-tab="metadata"]').click()
    panel.locator(f'[data-collection-fill-open="{domain}"]').click()


@pytest.mark.parametrize("page", ["chromium", "webkit"], indirect=True)
def test_offscreen_artwork_is_not_eagerly_loaded_by_decorative_backgrounds(page):
    rows = [
        {
            "id": str(uuid4()),
            "title": f"Lazy fixture {index}",
            "artist": "Fixture",
            "year": 2000,
            "release_type": "album",
            "status": "collected",
            "genres": [],
            "rating": None,
        }
        for index in range(100)
    ]
    for row in rows:
        row["cover_url"] = f"/api/music/albums/{row['id']}/artwork?v=fixture"
    loaded = []

    def artwork(route):
        loaded.append(route.request.url)
        route.fulfill(
            content_type="image/svg+xml",
            body='<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect width="100" height="100" fill="green"/></svg>',
        )

    page.route(
        "**/api/music/albums?**",
        lambda route: route.fulfill(json={"page": 1, "pages": 1, "total": 100, "items": rows}),
    )
    page.route("**/api/music/albums/*/artwork?**", artwork)
    page.locator('button[data-workspace="music"]').click()
    first = page.locator(".music-card").first
    last = page.locator(".music-card").last
    playwright_api.expect(first.locator("img")).to_have_attribute("loading", "eager")
    playwright_api.expect(last.locator("img")).to_have_attribute("loading", "lazy")
    page.wait_for_function("() => document.querySelector('.music-card img').naturalWidth > 0")
    assert len(loaded) < len(rows)
    assert not last.evaluate("node => node.style.getPropertyValue('--collection-art')")
    last.scroll_into_view_if_needed()
    page.wait_for_function(
        "() => [...document.querySelectorAll('.music-card img')].at(-1).naturalWidth > 0"
    )
    assert last.evaluate("node => node.style.getPropertyValue('--collection-art')")


@pytest.mark.parametrize("page", ["chromium", "webkit"], indirect=True)
@pytest.mark.parametrize("domain", ["music", "books"])
def test_pagination_stays_visible_and_navigation_wins_over_background_fill(page, domain):
    from urllib.parse import parse_qs, urlsplit

    page.clock.install()
    status = {
        "run_id": str(uuid4()),
        "total": 3,
        "completed": 0,
        "pending": 3,
        "updated": 0,
        "review_count": 0,
        "cancelled": 0,
        "review": [],
    }
    page.route(
        f"**/api/collections/{domain}/metadata-fill**", lambda route: route.fulfill(json=status)
    )
    calls, held = [], []
    hold_previous = False

    def response(number):
        return {
            "page": number,
            "pages": 3,
            "total": 72,
            "items": [
                {
                    "id": f"00000000-0000-4000-8000-{index:012d}",
                    "title": f"Page {number} title {index}",
                    "artist": "Fixture",
                    "author": "Fixture",
                    "version": 1,
                    "release_type": "album",
                    "book_format": "book",
                    "status": "collected",
                    "genres": [],
                    "tags": [],
                    "rating": None,
                }
                for index in range((number - 1) * 24 + 1, number * 24 + 1)
            ],
        }

    def collection(route):
        number = int(parse_qs(urlsplit(route.request.url).query)["page"][0])
        calls.append(number)
        if hold_previous and number == 1:
            held.append(route)
        else:
            route.fulfill(json=response(number))

    endpoint = "albums" if domain == "music" else "entries"
    page.route(f"**/api/{domain}/{endpoint}?**", collection)
    page.locator(f'button[data-workspace="{domain}"]').click()
    nav = page.locator("#music-pagination")
    playwright_api.expect(nav.locator('[aria-current="page"]')).to_have_text("1")
    nav.get_by_role("button", name="Next page", exact=True).click()
    playwright_api.expect(nav.locator('[aria-current="page"]')).to_have_text("2")
    hold_previous = True
    # Invalidate warm snapshots so this scenario exercises an actual delayed
    # navigation, not an intentionally instantaneous previous-page cache hit.
    page.evaluate("document.dispatchEvent(new Event('pmt-data-changed'))")
    nav.get_by_role("button", name="Previous page", exact=True).click()
    playwright_api.expect(page.locator("#music-content")).to_have_attribute("aria-busy", "true")
    navigation_calls = list(calls)
    status.update(completed=1, pending=2, updated=1)
    page.clock.run_for(9000)
    playwright_api.expect(nav).to_be_visible()
    playwright_api.expect(
        nav.get_by_role("button", name="Next page", exact=True)
    ).to_be_enabled()
    assert calls == navigation_calls, "Metadata polling must not cancel or duplicate navigation"
    assert calls[-1] == 1
    nav.get_by_role("button", name="Last page", exact=True).click()
    playwright_api.expect(nav.locator('[aria-current="page"]')).to_have_text("3")
    assert held
    held[0].fulfill(json=response(1))
    page.evaluate("window.retainedCollectionCard = document.querySelector('.music-card')")
    page.clock.run_for(6500)
    playwright_api.expect(nav.locator('[aria-current="page"]')).to_have_text("3")
    playwright_api.expect(page.locator("#music-content")).to_have_attribute(
        "aria-busy", "false"
    )
    assert page.evaluate(
        "window.retainedCollectionCard === document.querySelector('.music-card')"
    )
    assert calls[-1] == 3
    # Leaving a workspace while its refresh is queued must not leave a stale
    # timer ID that prevents every future refresh when returning to it.
    status.update(completed=2, pending=1, updated=2)
    page.clock.run_for(2000)
    playwright_api.expect(page.locator("#collection-fill-summary")).to_contain_text("2 / 3")
    page.locator('button[data-workspace="screen"]').click()
    hold_previous = False
    page.locator(f'button[data-workspace="{domain}"]').click()
    playwright_api.expect(nav.locator('[aria-current="page"]')).to_have_text("1")
    open_maintenance(page, domain)
    playwright_api.expect(page.locator("#collection-fill-summary")).to_contain_text("2 / 3")
    count_before = len(calls)
    status.update(completed=3, pending=0, updated=3)
    page.clock.run_for(2000)
    playwright_api.expect(page.locator("#collection-fill-summary")).to_contain_text("3 / 3")
    page.clock.run_for(6500)
    # Settings is now its own page. Metadata polling updates its progress, but
    # must not refresh the hidden library until the user returns to that page.
    assert len(calls) == count_before
    page.locator("#collection-fill-dialog .dialog-close").click()
    page.locator(".brand").click()
    playwright_api.expect(nav).to_be_visible()
    playwright_api.expect(page.locator("#music-content")).to_have_attribute(
        "aria-busy", "false"
    )
    assert len(calls) > count_before and calls[-1] == 1


def test_retry_unresolved_and_show_more_review_entries(page):
    sent, limits = [], []
    status = {
        "run_id": str(uuid4()),
        "total": 120,
        "completed": 120,
        "pending": 0,
        "updated": 19,
        "review_count": 101,
        "cancelled": 0,
        "review": [],
        "review_has_more": True,
    }

    def handle(route):
        if route.request.method == "POST":
            sent.append(route.request.post_data_json)
            route.fulfill(json={**status, "pending": 101})
        else:
            limits.append(route.request.url)
            route.fulfill(json=status)

    page.route("**/api/collections/music/metadata-fill**", handle)
    page.locator('button[data-workspace="music"]').click()
    open_maintenance(page)
    page.locator("#collection-fill-more").click()
    page.wait_for_function(
        "document.querySelector('#collection-fill-summary').textContent.includes('120')"
    )
    page.locator("#collection-fill-retry").click()
    assert sent == [
        {"language": "en", "scope": "all", "retry_review": True, "use_wikidata": True}
    ]
    assert any("review_offset=100" in url for url in limits)


@pytest.mark.parametrize("page", ["chromium", "webkit"], indirect=True)
def test_collection_fill_progress_switching_and_cancel(page):
    run = str(uuid4())
    status = {
        "run_id": run,
        "total": 2,
        "completed": 0,
        "pending": 2,
        "updated": 0,
        "review_count": 0,
        "cancelled": 0,
        "review": [],
    }
    calls = []

    def handle(route):
        calls.append(route.request.method)
        if route.request.method == "DELETE":
            status.update(pending=0, completed=2, cancelled=2)
        route.fulfill(json=status)

    page.route("**/api/collections/music/metadata-fill**", handle)
    page.locator('button[data-workspace="music"]').click()
    open_maintenance(page)
    playwright_api.expect(page.locator("#collection-fill-dialog")).to_be_visible()
    playwright_api.expect(page.locator("#collection-fill-summary")).to_contain_text("0 / 2")
    playwright_api.expect(page.locator("#collection-fill-start")).to_be_disabled()
    page.locator("#collection-fill-cancel").click()
    playwright_api.expect(page.locator("#collection-fill-summary")).to_contain_text("2 / 2")
    playwright_api.expect(page.locator("#collection-fill-cancel")).to_be_hidden()
    assert "DELETE" in calls
    page.locator("#collection-fill-dialog .dialog-close").click()
    playwright_api.expect(
        page.locator('[data-collection-fill-banner="music"]')
    ).to_contain_text("Metadata check stopped")
    page.locator(".brand").click()
    page.locator('button[data-workspace="books"]').click()
    playwright_api.expect(page.locator('[data-collection-fill-banner="books"]')).to_be_empty()
    assert (
        page.locator(
            "#music-view [data-collection-fill-open], #music-view [data-collection-fill-banner]"
        ).count()
        == 0
    )


@pytest.mark.parametrize("page", ["chromium", "webkit"], indirect=True)
def test_native_album_removal_confirmation_is_above_editor(page, browser_server):
    title = f"Native confirmation fixture {uuid4()}"
    row = page.request.post(
        f"{browser_server}/api/music/albums", data={"title": title, "artist": "Fixture"}
    ).json()
    page.goto(
        f"{browser_server}/?desktop=macos&mode=music&view=music_library",
        wait_until="networkidle",
    )
    page.locator(f'[data-open-music="{row["id"]}"]').click()
    page.locator("#music-more-actions summary").click()
    page.locator("#music-delete").click()
    confirm = page.locator("#confirm-dialog")
    editor = page.locator("#music-editor")
    playwright_api.expect(confirm).to_have_class(
        __import__("re").compile("native-dialog-active")
    )
    assert editor.evaluate("node => node.inert")
    page.wait_for_function(
        "() => Number(getComputedStyle(document.querySelector('#confirm-dialog')).zIndex) > Number(getComputedStyle(document.querySelector('#music-editor')).zIndex)",
        timeout=2000,
    )
    page.keyboard.press("Escape")
    playwright_api.expect(confirm).to_be_hidden()
    playwright_api.expect(editor).to_be_visible()
    playwright_api.expect(editor).not_to_have_attribute("inert", "")
    assert page.request.get(f"{browser_server}/api/music/albums/{row['id']}").status == 200
    page.locator("#music-more-actions summary").click()
    page.locator("#music-delete").click()
    confirm.locator('[value="confirm"]').click()
    playwright_api.expect(editor).to_be_hidden()
    assert page.request.get(f"{browser_server}/api/music/albums/{row['id']}").status == 404


def test_search_is_compact_and_cover_failure_uses_catalog_fallback(page):
    results = [
        {
            "provider_id": str(uuid4()),
            "title": f"Album {number}",
            "artist": "Fixture",
            "year": 1992,
            "track_count": 9,
            "artwork_url": "https://coverartarchive.org/release/broken/front-500",
            "artwork_fallbacks": [
                "https://coverartarchive.org/release-group/fallback/front-500"
            ],
        }
        for number in range(12)
    ]
    page.route("**/api/music/search?**", lambda route: route.fulfill(json={"results": results}))
    page.route(
        "https://coverartarchive.org/release/broken/**", lambda route: route.fulfill(status=404)
    )
    # A valid transparent one-pixel PNG is sufficient to assert fallback loading.
    import base64

    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLttAAAAABJRU5ErkJggg=="
    )
    page.route(
        "https://coverartarchive.org/release-group/fallback/**",
        lambda route: route.fulfill(content_type="image/png", body=png),
    )
    page.locator('button[data-workspace="music"]').click()
    page.locator("#quick-add-shortcut").click()
    page.locator('#music-search-form [name="query"]').fill("Albums")
    playwright_api.expect(page.locator("[data-music-result]")).to_have_count(8)
    page.wait_for_function(
        "Array.from(document.querySelectorAll('#music-search-results img')).every(img => img.src.includes('/release-group/') && img.naturalWidth > 0)"
    )
    page.locator("[data-more-catalog]").click()
    playwright_api.expect(page.locator("[data-music-result]")).to_have_count(12)


def test_import_explicit_opt_out_and_opt_in_progress(page):
    sent = []
    status = {
        "run_id": str(uuid4()),
        "total": 1,
        "pending": 1,
        "completed": 0,
        "updated": 0,
        "review_count": 0,
        "cancelled": 0,
        "review": [],
    }
    page.route(
        "**/api/collections/music/metadata-fill", lambda route: route.fulfill(json=status)
    )

    def imports(route):
        body = route.request.post_data_json
        if route.request.url.endswith("/preview"):
            route.fulfill(json={"sha256": "fixture", "new_albums": 1, "skipped": 0, "lists": 0})
        else:
            sent.append(body)
            route.fulfill(
                json={
                    "new_albums": 1,
                    **({"metadata": status} if body["fill_metadata"] else {}),
                }
            )

    page.route("**/api/music/import**", imports)
    document = {
        "format": "pmt-music-collection",
        "version": 1,
        "albums": [{"id": str(uuid4()), "title": "Fixture", "artist": "Artist"}],
    }
    page.locator("#open-settings").click()
    page.locator('[data-settings-tab="data"]').click()
    page.locator("#open-import").click()
    page.locator('[data-import-domain="music"]').click()
    page.locator("#music-import-file").set_input_files(
        {
            "name": "collection.json",
            "mimeType": "application/json",
            "buffer": json.dumps(document).encode(),
        }
    )
    playwright_api.expect(page.locator("#collection-import-fill")).to_be_checked()
    page.locator("#collection-import-fill").uncheck()
    page.locator("#music-import-confirm").click()
    playwright_api.expect(page.locator("#music-import-status")).to_contain_text(
        "Collection imported"
    )
    assert sent[0]["fill_metadata"] is False
    page.locator("#music-import-file").set_input_files(
        {
            "name": "again.json",
            "mimeType": "application/json",
            "buffer": json.dumps(document).encode(),
        }
    )
    page.locator("#collection-import-fill").check()
    page.locator("#music-import-confirm").click()
    playwright_api.expect(page.locator("#collection-fill-dialog")).to_be_visible()
    playwright_api.expect(page.locator("#collection-fill-summary")).to_contain_text("0 / 1")
    assert sent[1]["fill_metadata"] is True
