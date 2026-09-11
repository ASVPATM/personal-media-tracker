from __future__ import annotations

import json

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")

from test_browser_e2e import browser_server as browser_server  # noqa: E402


def test_locale_switches_details_controls_and_custom_period_without_failed_requests(
    browser_server, tmp_path
):
    with playwright_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors, failed = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "response",
            lambda response: (
                failed.append(response.url)
                if response.status >= 400 and "/api/insights" in response.url
                else None
            ),
        )
        page.request.put(
            f"{browser_server}/api/settings/general",
            data={"onboarding_complete": True, "interface_language": "fr"},
        )
        created = page.request.post(
            f"{browser_server}/api/entries/manual",
            data={
                "canonical_title": "Unchanged original",
                "media_type": "movie",
                "provider_genres": ["Drama", "Mystery"],
                "notes": "Private notes stay unchanged",
                "overview": "Original provider text",
                "personal_rating": 9,
            },
        ).json()["entry"]

        def translation(route):
            language = page.locator("html").get_attribute("lang")
            route.fulfill(
                content_type="application/json",
                body=json.dumps(
                    {
                        "status": "translated",
                        "language": language,
                        "title": "Titre traduit" if language == "fr" else "翻译标题",
                        "overview": "Résumé traduit" if language == "fr" else "翻译简介",
                    }
                ),
            )

        page.route("**/localized-metadata", translation)
        page.goto(browser_server)
        playwright_api.expect(page.locator(".entry-card .genre-chip").first).to_contain_text(
            "Drame"
        )
        page.locator(".entry-card [data-details]").first.click()
        playwright_api.expect(page.locator("#entry-dialog-title")).to_contain_text(
            "Titre traduit"
        )
        playwright_api.expect(page.locator("#entry-overview-facts")).to_contain_text(
            "Résumé traduit"
        )
        playwright_api.expect(page.locator("#entry-overview-facts")).to_contain_text("Drame")
        page.locator("#entry-dialog .dialog-close").click()
        page.goto(f"{browser_server}/?view=insights")
        custom = page.locator('[data-insight-period="custom"]')
        playwright_api.expect(custom).to_have_text("Personnalisé")
        for width in (1440, 720, 390):
            page.set_viewport_size({"width": width, "height": 950})
            assert custom.evaluate("el => el.scrollWidth <= el.clientWidth + 1")
            assert custom.bounding_box()["width"] > 80
        custom.click()
        playwright_api.expect(custom).to_have_attribute("aria-pressed", "true")
        playwright_api.expect(page.locator('[data-insight-period="year"]')).to_have_attribute(
            "aria-pressed", "false"
        )
        playwright_api.expect(page.locator("#insights-state")).to_contain_text("Choisissez")
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.screenshot(path=str(tmp_path / "french-insights.png"))
        # Switch without losing the partially selected custom date range.
        page.locator("#open-settings").click()
        assert page.locator("#general-language").count() == 0
        page.locator("#interface-language").select_option("zh-CN")
        with page.expect_navigation(wait_until="domcontentloaded"):
            page.locator("#save-general-settings").click()
        playwright_api.expect(page.locator("html")).to_have_attribute("lang", "zh-CN")
        page.locator("#open-settings").click()
        playwright_api.expect(page.locator("#interface-language")).to_be_enabled()
        help_tip = page.locator("[data-tip]").filter(has_text="?").first
        assert help_tip.count()
        page.screenshot(path=str(tmp_path / "chinese-settings.png"), animations="disabled")
        page.locator("#settings-dialog .dialog-close").click()
        playwright_api.expect(page.locator("#insights-state")).to_contain_text("请选择")
        assert failed == []
        assert errors == []
        assert (
            page.request.get(f"{browser_server}/api/entries/{created['id']}").json()["notes"]
            == "Private notes stay unchanged"
        )
        browser.close()


def test_recommendation_controls_and_local_evaluation_in_chinese(browser_server):
    with playwright_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1300, "height": 1000})
        page.request.put(
            f"{browser_server}/api/settings/general",
            data={"onboarding_complete": True, "interface_language": "zh-CN"},
        )
        page.goto(f"{browser_server}/?view=recommendations")
        playwright_api.expect(page.locator("#generate-recommendations")).to_have_text(
            "生成推荐"
        )
        page.locator("#recommendations-view details").get_by_text("检查推荐质量").click()
        page.locator("#evaluate-recommendations").click()
        playwright_api.expect(page.locator("#recommendation-quality")).to_contain_text(
            "本检查至少需要 8 个"
        )
        page.locator("#recommendation-discovery-settings").click()
        playwright_api.expect(
            page.locator("#recommendation-use-taste-discovery")
        ).to_be_visible()
        page.locator("#recommendation-use-taste-discovery").check()
        page.locator("#recommendation-discovery-language").select_option("zh")
        page.locator("#save-recommendation-sources").click()
        playwright_api.expect(page.locator("#recommendation-source-state")).to_contain_text(
            "下次生成时生效"
        )
        result = page.request.get(f"{browser_server}/api/v1/recommendations/preferences").json()
        assert result["use_taste_discovery"] is True and result["discovery_language"] == "zh"
        browser.close()


@pytest.mark.parametrize("locale", ["fr", "zh-CN"])
def test_translation_fallback_retry_and_responsive_description(
    browser_server, tmp_path, locale
):
    with playwright_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.request.put(
            f"{browser_server}/api/settings/general",
            data={"onboarding_complete": True, "interface_language": locale},
        )
        entry = page.request.post(
            f"{browser_server}/api/entries/manual",
            data={
                "canonical_title": "Synthetic translation example",
                "media_type": "anime",
                "overview": "Saved description",
                "notes": "Unchanged personal notes",
            },
        ).json()["entry"]
        responses = [
            {"language": locale, "status": "unavailable"},
            {
                "language": locale,
                "status": "translated",
                "overview": "Résumé traduit pour cette série."
                if locale == "fr"
                else "这是一部动画系列的中文简介。",
            },
        ]
        page.route(
            f"**/entries/{entry['id']}/localized-metadata",
            lambda route: route.fulfill(json=responses.pop(0)),
        )
        page.goto(browser_server)
        page.locator(f'[data-entry="{entry["id"]}"] [data-details]').click()
        status = page.locator("#entry-translation-status")
        playwright_api.expect(status).to_contain_text("TMDb")
        playwright_api.expect(page.locator(".entry-description p")).to_have_text(
            "Saved description"
        )
        for width in (1440, 390):
            page.set_viewport_size({"width": width, "height": 950})
            assert page.locator("#entry-dialog").evaluate(
                "el => el.scrollWidth <= el.clientWidth + 1"
            )
            page.screenshot(
                path=str(tmp_path / f"translation-{locale}-{width}.png"), animations="disabled"
            )
        page.locator("#entry-translation-retry").click()
        playwright_api.expect(page.locator(".entry-description p")).to_contain_text(
            "Résumé traduit" if locale == "fr" else "中文简介"
        )
        playwright_api.expect(page.locator("#entry-translation-retry")).to_have_count(1)
        assert (
            page.request.get(f"{browser_server}/api/entries/{entry['id']}").json()[
                "catalog_item"
            ]["overview"]
            == "Saved description"
        )
        assert not errors
        browser.close()
