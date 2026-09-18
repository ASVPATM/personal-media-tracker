from __future__ import annotations

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")

from test_browser_e2e import browser_server as browser_server  # noqa: E402


@pytest.fixture
def page(browser_server):
    with playwright_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.request.put(
            f"{browser_server}/api/settings/general",
            data={"onboarding_complete": True, "interface_language": "en"},
        )
        page.goto(browser_server, wait_until="networkidle")
        yield page
        browser.close()
        assert errors == []


def test_community_precision_and_all_three_date_forms(page, browser_server):
    entry = page.request.post(
        f"{browser_server}/api/entries/manual",
        data={
            "canonical_title": "Date and decimal fixture",
            "media_type": "movie",
            "personal_rating": 8.2,
            "public_score": 8.020999999999999,
            "started_date": "2026-09-09",
            "finished_date": "2026-09-10",
        },
    ).json()["entry"]
    page.evaluate("id => openEntry(id)", entry["id"])
    playwright_api.expect(page.locator("#entry-overview-facts")).to_contain_text("8.02/10")
    assert "999999" not in page.locator("#entry-dialog").inner_text()
    finish = page.locator("#entry-finished")
    playwright_api.expect(finish).to_have_attribute("min", "2026-09-09")
    finish.fill("2026-09-08")
    assert (
        finish.evaluate("el => el.validationMessage")
        == "Finished date cannot be before started date."
    )
    page.locator('#entry-form button[type="submit"]').click()
    assert (
        page.request.get(f"{browser_server}/api/entries/{entry['id']}").json()["finished_date"]
        == "2026-09-10"
    )
    finish.fill("2026-09-09")
    assert finish.evaluate("el => el.checkValidity()")
    page.locator('#entry-form button[type="submit"]').click()
    playwright_api.expect(page.locator("#entry-dialog")).not_to_be_visible()
    assert (
        page.request.get(f"{browser_server}/api/entries/{entry['id']}").json()["finished_date"]
        == "2026-09-09"
    )

    page.evaluate("document.querySelector('#manual-dialog').showModal()")
    page.locator('#manual-form [name="canonical_title"]').fill("Must not save invalid dates")
    page.locator('#manual-form [name="started_date"]').fill("2026-09-10")
    page.locator('#manual-form [name="finished_date"]').fill("2026-09-09")
    assert not page.locator("#manual-form").evaluate("form => form.checkValidity()")
    page.locator('#manual-form [name="started_date"]').fill("")
    assert page.locator("#manual-form").evaluate("form => form.checkValidity()")
    page.evaluate("document.querySelector('#manual-form').reset()")
    playwright_api.expect(
        page.locator('#manual-form [name="finished_date"]')
    ).to_have_attribute("min", "")
    page.evaluate("document.querySelector('#manual-dialog').close()")

    page.evaluate("""() => openQuickAddDetails({
        provider: "tmdb_movie", provider_id: "browser-101", title: "Quick date fixture",
        media_type: "movie", year: 2024
    })""")
    page.locator("#quick-started").fill("2026-09-10")
    page.locator("#quick-finished").fill("2026-09-09")
    assert not page.locator("#quick-add-details-form").evaluate("form => form.checkValidity()")
    page.locator("#quick-finished").fill("2026-09-10")
    assert page.locator("#quick-add-details-form").evaluate("form => form.checkValidity()")
    page.locator("#back-to-quick-add").click()


def test_rating_review_disappears_after_the_last_missing_rating(page, browser_server):
    entry = page.request.post(
        f"{browser_server}/api/entries/manual",
        data={
            "canonical_title": "AAA Unrated fixture",
            "media_type": "movie",
            "status": "watched",
            "personal_rating": None,
        },
    ).json()["entry"]
    page.locator("#open-settings").click()
    page.locator('[data-settings-tab="screen"]').click()
    page.locator('[data-screen-settings-tab="metadata"]').click()
    playwright_api.expect(page.locator("#review-ratings")).to_have_text(
        "Add missing ratings (1)"
    )
    page.locator("#review-ratings").click()
    playwright_api.expect(page.locator("#entry-id")).to_have_value(entry["id"])
    page.locator("#entry-rating").fill("8.5")
    page.locator("#save-next-rating").click()
    playwright_api.expect(page.locator("#save-next-rating")).to_be_hidden()
    page.locator("#entry-dialog .dialog-close").click()
    page.locator("#open-settings").click()
    page.locator('[data-settings-tab="screen"]').click()
    page.locator('[data-screen-settings-tab="metadata"]').click()
    playwright_api.expect(page.locator("#review-ratings")).to_have_text("No missing ratings")
    playwright_api.expect(page.locator("#review-ratings")).to_be_disabled()
    assert (
        page.request.get(f"{browser_server}/api/entries/{entry['id']}").json()[
            "personal_rating"
        ]
        == 8.5
    )


@pytest.mark.parametrize(
    "language,title,overview",
    [
        ("zh-CN", "已翻译的推荐", "来自数据源的中文简介"),
        ("fr", "Recommandation traduite", "Résumé traduit du fournisseur"),
    ],
)
def test_translated_recommendations_keep_originals_on_partial_failure(
    page, browser_server, language, title, overview, tmp_path
):
    page.request.put(
        f"{browser_server}/api/settings/general", data={"interface_language": language}
    )
    page.goto(f"{browser_server}/?view=recommendations", wait_until="networkidle")
    envelope = {
        "run": {"id": "fixture", "state": "completed"},
        "personalized": True,
        "results": [
            {
                "id": f"result-{index}",
                "catalog_id": f"catalog-{index}",
                "rank": index,
                "title": f"Original {index}",
                "overview": f"Original summary {index}",
                "year": 2024,
                "media_type": "movie",
                "genres": ["Drama"],
                "provider_source": "tmdb_movie",
                "provider_id": f"test-{index}",
                "match": 0.9 - index / 10,
                "display_match": 90 - index * 10,
            }
            for index in range(1, 4)
        ],
    }
    page.route(
        "**/recommendation-runs/fixture/results", lambda route: route.fulfill(json=envelope)
    )
    page.route(
        "**/recommendation-runs/fixture/localized-metadata?offset=0",
        lambda route: route.fulfill(
            json={
                "language": language,
                "results": {
                    "result-1": {"status": "translated", "title": title, "overview": overview},
                    "result-2": {"status": "translated", "title": title + " 2"},
                    "result-3": {"status": "temporarily_unavailable"},
                },
            }
        ),
    )
    page.evaluate("loadRecommendationResults('fixture')")
    first = page.locator('[data-recommendation-result="result-1"]')
    playwright_api.expect(first.locator("h4")).to_have_text(title)
    playwright_api.expect(first.locator(".recommendation-overview")).to_have_text(overview)
    playwright_api.expect(
        page.locator('[data-recommendation-result="result-2"] .recommendation-overview')
    ).to_have_text("Original summary 2")
    playwright_api.expect(
        page.locator('[data-recommendation-result="result-3"] h4')
    ).to_have_text("Original 3")
    playwright_api.expect(
        page.locator("#recommendation-translation-status")
    ).not_to_have_attribute("aria-busy", "true")
    assert page.locator(".recommendation-score strong").all_text_contents() == [
        "80",
        "70",
        "60",
    ]
    assert page.locator(".recommendation-rank").all_text_contents() == ["1", "2", "3"]
    first.locator("[data-recommendation-customize]").click()
    playwright_api.expect(page.locator("#quick-add-details-dialog")).to_contain_text(title)
    page.locator("#back-to-quick-add").click()
    page.locator("#quick-add-dialog .dialog-close").click()
    page.screenshot(
        path=str(tmp_path / f"recommendations-{language}.png"), animations="disabled"
    )

    # A delayed old run may not replace a newer list, even in the same language.
    page.unroute("**/recommendation-runs/fixture/localized-metadata?offset=0")
    page.route(
        "**/recommendation-runs/fixture/localized-metadata?offset=0",
        lambda route: route.fulfill(
            json={
                "language": language,
                "results": {"result-1": {"status": "translated", "title": "STALE"}},
            }
        ),
    )
    page.evaluate(
        """async envelope => {
        renderRecommendationResults(envelope);
        const pending = loadRecommendationTranslations(envelope);
        renderRecommendationResults({run: {id: 'newer'}, personalized: true,
            results: [{...envelope.results[0], title: 'Newer result', rank: 1}]});
        await pending;
    }""",
        envelope,
    )
    playwright_api.expect(page.locator(".recommendation-result h4")).to_have_text(
        "Newer result"
    )


def test_reported_chinese_dynamic_copy_and_month_labels(page, browser_server, tmp_path):
    page.request.put(
        f"{browser_server}/api/settings/general", data={"interface_language": "zh-CN"}
    )
    page.goto(f"{browser_server}/?view=insights", wait_until="networkidle")
    playwright_api.expect(page.locator("#insights-content")).not_to_be_empty()
    strings = [
        "Shown averages are raw personal ratings. Ordering adds a small confidence adjustment; at least 3 rated titles are required for a favourite callout.",
        "median",
        "average",
        "unrated",
        "Recommendations ready",
        "Create a list",
        "Add to list…",
        "Generate again",
        "Ranked directly by your personal 1–10 rating. Ties use a stable title order.",
        "No confirmed active shows",
        "No dated episodes in the next 60 days",
        "No shared-list or integration notifications.",
        "No upcoming dated episodes",
        "Optional metadata token",
        "No server is connected to this device yet.",
        "Open Tailscale and connect this computer first.",
        "Import handling",
        "Account ID",
        "Access token",
        "Refresh token",
        "Client ID",
        "Client secret",
        "Required · Provider access token",
        "Import handling help",
    ]
    translated = page.evaluate("values => values.map(translatedText)", strings)
    for original, value in zip(strings, translated, strict=True):
        assert value != original, original
    assert page.evaluate("activityPeriodLabel('2026-01')") == "2026年1月"
    page.evaluate("""() => renderEnrichmentStatus({
        status: 'completed', total: 14, processed: 14, enriched: 14, failed: 0,
        needs_confirmation: 0, match_reasons: {stable_provider_id: 14},
        message: 'Resolved or refreshed 14 entries; 0 unresolved need confirmation; 0 failed.',
        warnings: ['Jikan search is temporarily unavailable.']
    })""")
    enrichment = page.locator("#enrichment-status").text_content()
    assert "已匹配或刷新 14 部作品" in enrichment
    assert "已检查 14/14" in enrichment
    assert "匹配依据：14 稳定的数据源 ID" in enrichment
    assert "Jikan 搜索暂时不可用。" in enrichment
    page.goto(f"{browser_server}/?view=active_shows")
    playwright_api.expect(page.locator("#release-sync-status")).to_contain_text("仅手动检查")
    playwright_api.expect(page.locator("#active-calendar-summary")).to_contain_text(
        "未来 60 天"
    )
    page.screenshot(path=str(tmp_path / "chinese-active-shows.png"), animations="disabled")
