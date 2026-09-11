from __future__ import annotations

import re

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")

from test_browser_e2e import browser_server as browser_server  # noqa: E402
from test_handoff_20260910_browser import page as page  # noqa: E402


def create_entry(page, base, **overrides):
    response = page.request.post(
        f"{base}/api/entries/manual",
        data={
            "canonical_title": "Original public title",
            "original_title": "Original public title",
            "media_type": "anime",
            "provider_source": "tvmaze",
            "provider_id": "42",
            "overview": "Original provider summary",
            "release_year": 2020,
            "runtime_minutes": 111,
            "episode_count": 1200,
            "personal_rating": 8.5,
            "view_count": 4,
            "notes": "Never send or translate private notes",
            **overrides,
        },
    )
    assert response.status == 201, response.text()
    return response.json()["entry"]


@pytest.mark.parametrize(
    "language,views", [("en", "4 views"), ("fr", "4 vu"), ("zh-CN", "4 次观看")]
)
def test_compact_counts_remain_readable_and_accessible(
    page, browser_server, tmp_path, language, views
):
    entry = create_entry(
        page,
        browser_server,
        canonical_title=f"Compact {language}",
        provider_id={"en": "61", "fr": "62", "zh-CN": "63"}[language],
    )
    page.request.put(
        f"{browser_server}/api/settings/general",
        data={"interface_language": language, "show_tile_view_counts": True},
    )
    page.goto(browser_server, wait_until="networkidle")
    card = page.locator(f'#library [data-entry="{entry["id"]}"]')
    playwright_api.expect(card.locator(".view-chip")).to_have_text(views)
    progress = card.locator("[data-episode-progress]")
    playwright_api.expect(progress).to_have_attribute("aria-label", re.compile("1200"))
    assert re.sub(r"\s+", " ", progress.inner_text()).strip() == "1200 1200"
    assert progress.locator("small").count() == 0
    for width in (1440, 720, 390):
        page.set_viewport_size({"width": width, "height": 1000})
        card.scroll_into_view_if_needed()
        assert card.locator(".view-chip").evaluate(
            "el => getComputedStyle(el).whiteSpace === 'nowrap'"
        )
        assert progress.evaluate("el => el.scrollWidth <= el.clientWidth + 1")
        assert card.locator(".entry-actions").evaluate(
            "el => el.scrollWidth <= el.clientWidth + 1"
        )
        page.screenshot(
            path=str(tmp_path / f"compact-{language}-{width}.png"), animations="disabled"
        )


def test_provider_text_is_consistent_across_library_rankings_details_and_refinement(
    page, browser_server, tmp_path
):
    entry = create_entry(page, browser_server, provider_id="71")
    path = f"**/entries/{entry['id']}/localized-metadata"
    calls = []

    def translate(route):
        language = page.locator("html").get_attribute("lang")
        calls.append(language)
        route.fulfill(
            json={
                "language": language,
                "status": "translated",
                "title": "Titre officiel" if language == "fr" else "官方中文标题",
                "overview": "Résumé officiel" if language == "fr" else "官方中文简介",
            }
        )

    page.route(path, translate)
    page.request.put(
        f"{browser_server}/api/settings/general",
        data={"interface_language": "fr", "advanced_ratings_enabled": True},
    )
    page.goto(browser_server, wait_until="networkidle")
    card = page.locator(f'#library [data-entry="{entry["id"]}"]')
    playwright_api.expect(card.locator("h3")).to_have_text("Titre officiel")
    card.locator("[data-details]").click()
    playwright_api.expect(page.locator("#entry-dialog-title")).to_contain_text("Titre officiel")
    playwright_api.expect(page.locator(".entry-description p")).to_have_text("Résumé officiel")
    page.locator("#entry-dialog .dialog-close").click()
    page.evaluate("switchView('rankings')")
    tile = page.locator(f'#rankings-list [data-entry="{entry["id"]}"]')
    playwright_api.expect(tile.locator("h3")).to_have_text("Titre officiel")
    assert calls.count("fr") == 1  # One lookup shared by all three surfaces.
    page.request.put(
        f"{browser_server}/api/settings/general", data={"interface_language": "zh-CN"}
    )
    page.evaluate("applyInterfaceLanguage('zh-CN')")
    playwright_api.expect(tile.locator("h3")).to_have_text("官方中文标题")
    playwright_api.expect(tile.locator(".ranking-scores")).to_contain_text("你的评分")
    playwright_api.expect(page.locator("#rankings-help")).to_contain_text("技术排名以")
    page.evaluate("id => startSingleTitleRefinement(id)", entry["id"])
    playwright_api.expect(page.locator("#assessment-heading")).to_have_text(
        "完善偏好 · 官方中文标题"
    )
    playwright_api.expect(
        page.locator("#assessment-memory-card [data-display-summary]")
    ).to_have_text("官方中文简介")
    playwright_api.expect(page.locator("#assessment-context")).to_contain_text(
        "其中 3 次为重看"
    )
    playwright_api.expect(page.locator("#assessment-question-progress")).to_contain_text("题")
    assert calls.count("zh-CN") == 1
    # Every current and stored legacy question must have translated prompt/endpoints.
    rubric = page.request.get(f"{browser_server}/api/ratings/rubric").json()
    for dimension in rubric["dimensions"]:
        translated = page.evaluate("key => rubricCatalogs['zh-CN'][key]", dimension["key"])
        assert len(translated) == 3
        assert all(re.search(r"[\u4e00-\u9fff]", text) for text in translated)
    for width in (1440, 390):
        page.set_viewport_size({"width": width, "height": 1000})
        assert page.locator("#assessment-dialog").evaluate(
            "el => el.scrollWidth <= el.clientWidth + 1"
        )
        page.screenshot(
            path=str(tmp_path / f"chinese-refinement-{width}.png"), animations="disabled"
        )
    current = page.request.get(f"{browser_server}/api/entries/{entry['id']}").json()
    assert current["catalog_item"] == entry["catalog_item"]
    assert current["notes"] == entry["notes"]
    assert current["personal_rating"] == entry["personal_rating"]


def test_captured_chinese_runtime_help_genres_and_search_status(page, browser_server):
    entry = create_entry(
        page,
        browser_server,
        canonical_title="Captured copy",
        media_type="movie",
        provider_id="72",
    )
    page.request.put(
        f"{browser_server}/api/settings/general", data={"interface_language": "zh-CN"}
    )
    page.goto(browser_server, wait_until="networkidle")
    page.evaluate("id => openEntry(id)", entry["id"])
    playwright_api.expect(page.locator("#entry-overview-facts")).to_contain_text("111 分钟")
    page.evaluate("renderSeriesReleases({supported: false})")
    assert "Automatic tracking" not in page.locator("#series-release-panel").text_content()
    assert "自动追踪" in page.locator("#series-release-panel").text_content()
    assert page.evaluate("['Android', 'Cops', 'Detective'].map(metadataLabel)") == [
        "仿生人",
        "警察",
        "侦探",
    ]
    definitions = page.request.get(f"{browser_server}/api/insights").json()["definitions"]
    translated = page.evaluate(
        "values => values.map(translatedText)", list(definitions.values())
    )
    assert all(
        original != text
        for original, text in zip(definitions.values(), translated, strict=True)
    )
    assert page.evaluate("translatedText('Library mix')") == "媒体库构成"
    assert page.evaluate("translatedText('Searching…')") == "正在搜索…"


def test_quick_add_localizes_only_display_and_keeps_fallbacks(page, browser_server):
    page.request.put(
        f"{browser_server}/api/settings/general", data={"interface_language": "zh-CN"}
    )
    page.goto(browser_server, wait_until="networkidle")
    pending = []

    def translate(route):
        if route.request.url.endswith("provider_id=82"):
            route.fulfill(json={"language": "zh-CN", "status": "unavailable"})
        else:
            pending.append(route)

    page.route("**/metadata/localized-metadata?*", translate)
    source = {
        "provider": "kitsu",
        "provider_id": "80",
        "title": "Official original",
        "year": 2020,
        "media_type": "anime",
        "overview": "Original summary",
    }
    with page.expect_request("**/metadata/localized-metadata?*"):
        page.evaluate("result => openQuickAddDetails(result)", source)
    playwright_api.expect(page.locator("#quick-translation-status")).to_contain_text("正在检查")
    pending.pop().fulfill(
        json={"language": "zh-CN", "status": "translated", "title": "官方中文名称"}
    )
    playwright_api.expect(page.locator("#quick-add-details-heading")).to_contain_text(
        "官方中文名称"
    )
    playwright_api.expect(page.locator("#quick-add-preview p[translate='no']")).to_have_text(
        "Original summary"
    )
    assert page.evaluate("state.selectedResult") == source
    assert page.locator("#quick-translation-status").text_content().find("TMDb") >= 0
    # A delayed prior selection cannot replace the next selection's title/description.
    first, second = (
        {**source, "provider_id": "81"},
        {**source, "provider_id": "82", "title": "Next selection"},
    )
    with page.expect_request("**/metadata/localized-metadata?*"):
        page.evaluate("result => openQuickAddDetails(result)", first)
    with page.expect_response("**/metadata/localized-metadata?*provider_id=82"):
        page.evaluate("result => openQuickAddDetails(result)", second)
    pending[0].fulfill(
        json={"language": "zh-CN", "status": "translated", "title": "Wrong old title"}
    )
    playwright_api.expect(page.locator("#quick-translation-status")).to_contain_text("TMDb")
    playwright_api.expect(page.locator("#quick-add-details-heading")).to_contain_text(
        "Next selection"
    )
    assert "Wrong old title" not in page.locator("#quick-add-details-dialog").inner_text()


def test_entry_translation_rejects_stale_language_and_identity(page, browser_server):
    entry = create_entry(
        page, browser_server, provider_id="91", canonical_title="Stable saved title"
    )
    pending = []
    page.route(
        f"**/entries/{entry['id']}/localized-metadata", lambda route: pending.append(route)
    )
    # A loading label is set before fetch reaches the route handler. Wait for
    # actual intercepted requests instead of relying on a no-op evaluation to
    # flush callbacks on a busy CI runner.
    page.expose_function("pendingTranslationCount", lambda: len(pending))
    page.request.put(
        f"{browser_server}/api/settings/general", data={"interface_language": "fr"}
    )
    page.goto(browser_server, wait_until="domcontentloaded")
    card = page.locator(f'#library [data-entry="{entry["id"]}"]')
    playwright_api.expect(card).to_have_attribute("data-translation-status", "loading")
    page.wait_for_function("async () => await pendingTranslationCount() === 1")
    original_key = page.evaluate("entry => displayTranslationKey(entry)", entry)
    # Rebinding after a source change invalidates the old in-flight display response.
    changed = {
        **entry,
        "catalog_item": {
            **entry["catalog_item"],
            "provider_id": "92",
            "canonical_title": "New saved identity",
        },
    }
    page.evaluate(
        "entry => bindEntryDisplay(document.querySelector(`[data-entry='${entry.id}']`), entry, {immediate:true})",
        changed,
    )
    page.wait_for_function("async () => await pendingTranslationCount() === 2")
    assert len(pending) == 2
    pending[1].fulfill(
        json={"language": "fr", "status": "translated", "title": "Nouveau titre"}
    )
    playwright_api.expect(card.locator("h3")).to_have_text("Nouveau titre")
    pending[0].fulfill(json={"language": "fr", "status": "translated", "title": "Old identity"})
    # Let the stale response actually settle before checking that it was ignored.
    page.evaluate("key => displayTranslations.get(key).promise", original_key)
    playwright_api.expect(card.locator("h3")).to_have_text("Nouveau titre")
    page.request.put(
        f"{browser_server}/api/settings/general", data={"interface_language": "zh-CN"}
    )
    page.route(
        f"**/entries/{entry['id']}/localized-metadata",
        lambda route: route.fulfill(
            json={"language": "fr", "status": "translated", "title": "Wrong locale"}
        ),
    )
    page.evaluate("applyInterfaceLanguage('zh-CN')")
    playwright_api.expect(card.locator("h3")).to_have_text("Stable saved title")
    playwright_api.expect(card).to_have_attribute("data-translation-status", "unavailable")


def test_translation_queue_is_bounded_and_deduplicates_requests(page):
    # Exercise the real request scheduler with deferred local requests, no provider calls.
    page.route(
        "**/display-queue-test/*",
        lambda route: route.fulfill(json={"language": "en", "status": "unavailable"}),
    )
    result = page.evaluate("""async () => {
        const originalApi = api;
        const release = [];
        let active = 0, maximum = 0, calls = 0;
        api = async () => {
            calls += 1; active += 1; maximum = Math.max(maximum, active);
            await new Promise(resolve => release.push(resolve));
            active -= 1;
            return {language:'en', status:'translated', title:'Synthetic'};
        };
        try {
            const jobs = Array.from({length: 7}, (_, index) => requestDisplayTranslation('/display-queue-test/' + index, 'queue-' + index));
            const duplicate = requestDisplayTranslation('/display-queue-test/0', 'queue-0');
            const initial = active;
            while (release.length || displayTranslationQueue.length || active) {
                release.splice(0).forEach(resolve => resolve());
                await new Promise(resolve => setTimeout(resolve, 0));
            }
            await Promise.all([...jobs, duplicate]);
            return {initial, maximum, calls, cached: displayTranslations.size};
        } finally { api = originalApi; }
    }""")
    assert result["initial"] == result["maximum"] == 3
    assert result["calls"] == 7
    assert result["cached"] <= 256
