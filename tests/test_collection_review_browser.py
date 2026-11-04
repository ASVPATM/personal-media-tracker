"""Compact review, confirmation layering and bounded speculative navigation."""

from uuid import uuid4

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")
from test_browser_e2e import browser_server as browser_server  # noqa: E402, F401
from test_collection_fill_browser import open_maintenance  # noqa: E402
from test_collections_browser import page as page  # noqa: E402, F401


@pytest.mark.parametrize("page", ["chromium", "webkit"], indirect=True)
def test_review_comparison_spelling_confirmation_and_apply(page, tmp_path):
    identifier, provider_id = str(uuid4()), str(uuid4())
    entry = {
        "id": identifier,
        "version": 1,
        "title": "Imported Synthetic",
        "artist": "Short Creator",
        "year": None,
    }
    candidate = {
        "title": "Verified Synthetic",
        "artist": "Complete Credited Creator",
        "year": 2001,
        "provider_id": provider_id,
        "edition_info": {"original_year": 1999, "name": "Original edition"},
    }
    decisions = []
    status = {
        "run_id": str(uuid4()),
        "total": 1,
        "completed": 1,
        "updated": 0,
        "pending": 0,
        "review_count": 1,
        "review_has_more": False,
        "review": [{"id": identifier, "title": entry["title"], "reason": "review"}],
    }

    def review(route):
        if route.request.method == "POST":
            payload = route.request.post_data_json
            decisions.append(payload)
            entry.update(
                title=payload.get("title", candidate["title"]), version=entry["version"] + 1
            )
            route.fulfill(json={"entry": entry, "decision": payload["action"]})
        elif "/candidates?" in route.request.url:
            route.fulfill(json={"version": entry["version"], "results": [candidate]})
        else:
            route.fulfill(json={"entry": entry, "duplicate": None, "resolution": None})

    page.route(
        "**/api/collections/music/metadata-fill**", lambda route: route.fulfill(json=status)
    )
    page.route("**/api/collections/music/review/**", review)
    page.route("**/api/music/metadata/*", lambda route: route.fulfill(json=candidate))
    page.locator('button[data-workspace="music"]').click()
    open_maintenance(page)
    page.locator("[data-fill-review]").click()
    dialog = page.locator("#collection-review-dialog")
    playwright_api.expect(dialog).to_be_visible()
    playwright_api.expect(dialog.locator('[name="title"]')).to_have_value("Imported Synthetic")
    dialog.locator('[name="creator"]').fill("Corrected Creator")
    dialog.locator("[data-review-spelling]").click()
    playwright_api.expect(page.locator("#confirm-title")).to_have_text("Edit imported spelling")
    playwright_api.expect(page.locator("#confirm-message")).to_contain_text("Corrected Creator")
    page.locator("#confirm-submit").click()
    playwright_api.expect(
        dialog.locator('[data-review-search] button[type="submit"]')
    ).to_be_enabled()
    dialog.locator('[data-review-search] button[type="submit"]').click()
    dialog.locator("[data-review-candidate]").click()
    playwright_api.expect(dialog.locator("[data-review-comparison]")).to_contain_text(
        "Complete Credited Creator"
    )
    playwright_api.expect(dialog.locator("[data-review-apply]")).to_be_visible()
    assert dialog.evaluate("node => node.getBoundingClientRect().bottom <= innerHeight")
    page.screenshot(path=str(tmp_path / "review.png"), animations="disabled")
    dialog.locator("[data-review-apply]").click()
    playwright_api.expect(dialog).not_to_be_visible()
    assert [row["action"] for row in decisions] == ["spelling", "apply"]
    assert decisions[-1]["version"] == 2


def test_cache_clear_has_specific_confirmation_and_is_not_library_delete(page):
    deletes = []

    def cache(route):
        if route.request.method == "DELETE":
            deletes.append(route.request.url)
        route.fulfill(json={"files": 12, "bytes": 12345, "can_clear": True})

    page.route("**/api/collections/cache", cache)
    page.locator("#open-settings").click()
    page.locator('[data-settings-tab="music"]').click()
    panel = page.locator('[data-settings-panel="music"]')
    panel.locator('[data-collection-settings-tab="metadata"]').click()
    panel.locator("[data-cache-clear]").click()
    playwright_api.expect(page.locator("#confirm-title")).to_have_text(
        "Clear downloaded cover cache"
    )
    playwright_api.expect(page.locator("#confirm-message")).to_contain_text(
        "Uploaded artwork, your library and backups are kept"
    )
    with page.expect_response(
        lambda response: (
            response.request.method == "DELETE"
            and response.url.endswith("/api/collections/cache")
        )
    ):
        page.locator("#confirm-submit").click()
    assert len(deletes) == 1


@pytest.mark.parametrize("page", ["chromium", "webkit"], indirect=True)
def test_navigation_cache_has_principal_boundary_and_bounded_pages(page):
    result = page.evaluate("""async () => {
      const cache = window.PMTCollectionNavigation.create();
      let calls = 0;
      const load = async () => { calls++; return {items: [{id:'synthetic'}]}; };
      for (let number = 1; number <= 20; number++) await cache.read('member-one:music:library', `/api/music/albums?page=${number}`, load);
      await cache.read('member-one:music:library', '/api/music/albums?page=20', load);
      const before = cache.diagnostics();
      await cache.read('member-two:music:library', '/api/music/albums?page=20', load);
      const owner = cache.diagnostics();
      const started = cache.begin();
      document.dispatchEvent(new Event('pmt-principal-changed'));
      return {calls, before, owner, after:cache.diagnostics(), aborted:started.controller.signal.aborted};
    }""")
    assert result["calls"] == 21
    assert result["before"]["snapshots"] == 3 and result["before"]["hits"] == 1
    assert result["owner"]["snapshots"] == 1
    assert result["after"]["snapshots"] == 0 and result["aborted"]


@pytest.mark.parametrize("page", ["chromium", "webkit"], indirect=True)
def test_next_page_intent_warms_only_four_covers(page):
    loaded = []

    def image(route):
        loaded.append(route.request.url)
        route.fulfill(
            content_type="image/svg+xml",
            body='<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50"><rect width="50" height="50" fill="green"/></svg>',
        )

    page.route("**/cache-probe-*", image)
    page.evaluate("""async () => {
      window.warmProbe = window.PMTCollectionNavigation.create();
      const fetchPage = async () => ({items:Array.from({length:24}, (_, n) => ({id:String(n), cover_url:`/cache-probe-${n}`}))});
      await window.warmProbe.read('synthetic:music', '/api/music/albums?page=1', async () => ({items:[]}));
      const nav = document.createElement('nav'); nav.id = 'warm-probe';
      nav.innerHTML = '<button data-page="2">Probe next</button>'; document.body.append(nav);
      window.warmProbe.bindNext(nav, 1, 'synthetic:music', '/api/music/albums?page=1', fetchPage);
      nav.querySelector('button').dispatchEvent(new Event('pointerenter'));
    }""")
    page.wait_for_function(
        "() => window.warmProbe.diagnostics().warmed === 1 && !window.warmProbe.diagnostics().speculative"
    )
    assert len(loaded) == 4
    result = page.evaluate("window.warmProbe.diagnostics()")
    assert result["speculativeCovers"] == 4 and result["snapshots"] == 2
    page.locator("#warm-probe").evaluate("node => node.remove()")
