"""Production media tiles: real application assets, isolated synthetic data."""

from __future__ import annotations

import httpx
import pytest

playwright_api = pytest.importorskip("playwright.sync_api")

from test_browser_e2e import browser_server as browser_server  # noqa: E402


@pytest.fixture(scope="module")
def tile_preview(browser_server):
    with httpx.Client(base_url=browser_server) as client:
        for i in range(24):
            item = {
                "canonical_title": f"Tile Fixture {i}",
                "media_type": "movie",
                "release_year": 2020,
                "personal_rating": 8,
                "provider_genres": ["Drama", "Adventure"],
                "view_count": 2,
                "overview": "A deterministic provider description about this title. " * 40,
            }
            if i == 22:
                item.update(
                    canonical_title="The Tile Television",
                    media_type="tv",
                    release_year=2016,
                    status="watching",
                    episode_count=12,
                )
            if i == 23:
                item.update(
                    canonical_title="The Tile Series",
                    media_type="anime",
                    release_year=2016,
                    episode_count=22,
                    provider_format="TV",
                    provider_source="kitsu",
                    provider_id="100",
                )
            response = client.post("/api/entries/manual", json=item)
            assert response.status_code == 201, response.text
    return browser_server


def show_recommendation_fixture(page):
    # switchView starts loading but does not return that asynchronous work.
    # Let readiness finish before inserting fixture cards or measuring scrolling;
    # its late header changes can otherwise move the document's scroll anchor.
    page.evaluate("state.recommendationsLoaded = false; switchView('recommendations')")
    page.wait_for_function("() => state.recommendationsLoaded")
    playwright_api.expect(page.locator("#recommendations-state")).to_be_empty()
    page.locator("#recommendations-view").evaluate(
        "el => Promise.all(el.getAnimations().map(animation => animation.finished))"
    )
    page.evaluate("""() => {
        const rows = Array.from({length: 20}, (_, i) => ({
            id: 'synthetic-' + i, catalog_id: 'synthetic-catalog-' + i,
            title: 'Synthetic recommendation ' + i, rank: i + 1,
            media_type: 'movie', year: 2024, match: 0.8,
            overview: 'A synthetic description for deterministic card layout testing. '.repeat(4),
            genres: ['Drama'], reason_codes: ['genre_affinity'], confidence: 0.8
        }));
        renderRecommendationResults({results: rows, personalized: true});
    }""")


@pytest.mark.parametrize(
    "width,language,touch", [(1440, "en", False), (720, "fr", False), (390, "zh-CN", True)]
)
def test_regular_tiles_are_compact_and_controls_work(
    tile_preview, tmp_path, width, language, touch
):
    with playwright_api.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": 1000}, has_touch=touch)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route(
            "**/api/entries/*/localized-metadata*",
            lambda route: route.fulfill(json={"status": "original", "language": language}),
        )
        settings = page.request.put(
            f"{tile_preview}/api/settings/general",
            data={
                "onboarding_complete": True,
                "interface_language": "en",
                "show_episode_progress": True,
                "artwork_reveal": False,
                "show_tile_view_counts": False,
            },
        )
        assert settings.ok
        page.goto(f"{tile_preview}/?view=library", wait_until="networkidle")
        page.locator("#open-settings").click()
        playwright_api.expect(page.locator("#interface-language")).to_be_enabled()
        playwright_api.expect(page.locator("#tile-view-counts")).not_to_be_checked()
        page.locator("#tile-view-counts").check()
        page.locator("#settings-dialog .dialog-close").click()
        page.evaluate("language => applyInterfaceLanguage(language)", language)
        card = page.locator("#library > .media-anime")
        playwright_api.expect(card).to_have_count(1)
        playwright_api.expect(card.locator(".poster")).to_be_visible()
        # Resolve all nodes and measure in one frame, even if a remote poster
        # changes to its fallback during translation/image loading.
        boxes = page.evaluate("""() => {
          const card = document.querySelector('#library > .media-anime');
          return Object.fromEntries(Object.entries({poster:'.poster', copy:'.entry-copy', signals:'.entry-signals',
            progress:'.card-episode-progress', info:'[data-details]', views:'.view-chip', heart:'[data-favorite-toggle]'
          }).map(([key, selector]) => [key, card.querySelector(selector).getBoundingClientRect().toJSON()]));
        }""")
        poster, copy, signals = boxes["poster"], boxes["copy"], boxes["signals"]
        counter = card.locator(".card-episode-progress")
        progress_box, info_box = boxes["progress"], boxes["info"]
        views_box, heart_box = boxes["views"], boxes["heart"]
        assert heart_box["y"] + heart_box["height"] <= info_box["y"]
        assert heart_box["x"] + heart_box["width"] == pytest.approx(
            info_box["x"] + info_box["width"], abs=1
        )
        assert views_box["y"] + views_box["height"] <= progress_box["y"]
        assert progress_box["x"] + progress_box["width"] < info_box["x"]
        assert progress_box["y"] + progress_box["height"] == pytest.approx(
            info_box["y"] + info_box["height"], abs=1
        )
        assert poster["width"] == (124 if width <= 720 else 144)
        assert poster["height"] == (183 if width <= 720 else 212)
        assert signals["x"] == pytest.approx(copy["x"], abs=1)
        assert signals["x"] > poster["x"] + poster["width"]
        assert signals["y"] >= copy["y"] + copy["height"]
        assert signals["y"] < poster["y"] + poster["height"]
        assert card.locator(".entry-actions").evaluate(
            "el => el.scrollWidth <= el.clientWidth + 1"
        )
        assert card.evaluate("el => el.scrollWidth <= el.clientWidth + 1")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        neighbor = page.locator("#library > .entry-card:not(.media-anime)").first
        assert neighbor.locator(".poster").bounding_box()["width"] == (
            124 if width <= 720 else 144
        )
        assert (
            neighbor.locator(".entry-signals").evaluate(
                "el => getComputedStyle(el).gridColumnStart"
            )
            == "2"
        )
        # No provider-format suffix, no reserved second line below a short title.
        page.evaluate("applyInterfaceLanguage('en')")
        good_place = page.locator("#library > .entry-card").filter(
            has=page.get_by_role("heading", name="The Tile Television", exact=True)
        )
        playwright_api.expect(good_place.locator(".entry-meta")).to_have_text(
            "2016 · TV series"
        )
        title_box = good_place.locator("h3").bounding_box()
        meta_box = good_place.locator(".entry-meta").bounding_box()
        assert meta_box["y"] - title_box["y"] - title_box["height"] < 5

        watched = int(counter.get_attribute("data-watched"))
        total = int(counter.get_attribute("data-total"))
        step = -1 if watched else 1
        counter.locator("[data-episode-toggle]").click()
        card.locator(f'[data-episode-step="{step}"]').click()
        playwright_api.expect(counter).to_have_attribute("data-watched", str(watched + step))
        card.locator(f'[data-episode-step="{-step}"]').click()
        playwright_api.expect(counter).to_have_attribute("data-watched", str(watched))
        assert counter.get_attribute("aria-label")
        favorite = card.locator("[data-favorite-toggle]")
        original_favorite = favorite.get_attribute("aria-pressed")
        favorite.click()
        playwright_api.expect(favorite).to_have_attribute(
            "aria-pressed", "false" if original_favorite == "true" else "true"
        )
        favorite.click()
        playwright_api.expect(favorite).to_have_attribute("aria-pressed", original_favorite)
        card.locator("[data-details]").click()
        playwright_api.expect(page.locator("#entry-dialog")).to_be_visible()
        page.locator("#entry-dialog .dialog-close").click()
        playwright_api.expect(page.locator("#entry-dialog")).not_to_be_visible()
        assert counter.get_attribute("data-total") == str(total)
        card.screenshot(
            path=str(tmp_path / f"tile-{width}-{language}.png"), animations="disabled"
        )
        browser.close()
        assert errors == []


@pytest.mark.parametrize("artwork", [False, True])
def test_view_counts_are_optional_without_losing_history(tile_preview, artwork):
    with playwright_api.sync_playwright() as runtime:
        browser, page = start_gallery_page(runtime, tile_preview, 390, True)
        if artwork:
            enable_gallery(page)
        card = page.locator("#library > .media-anime")
        entry_id = card.get_attribute("data-entry")
        saved_count = page.request.get(f"{tile_preview}/api/entries/{entry_id}").json()[
            "view_count"
        ]
        playwright_api.expect(card.locator(".view-chip")).to_be_hidden()
        page.locator("#open-settings").click()
        playwright_api.expect(page.locator("#interface-language")).to_be_enabled()
        preference = page.locator("#tile-view-counts")
        playwright_api.expect(preference).not_to_be_checked()
        preference.check()
        page.locator("#settings-dialog .dialog-close").click()
        if artwork:
            card.locator(".pmt-artwork-trigger").tap()
        playwright_api.expect(card.locator(".view-chip")).to_be_visible()
        page.reload(wait_until="networkidle")
        playwright_api.expect(preference).to_be_checked()
        if artwork:
            card.locator(".pmt-artwork-trigger").tap()
        playwright_api.expect(card.locator(".view-chip")).to_be_visible()
        page.locator("#open-settings").click()
        playwright_api.expect(page.locator("#interface-language")).to_be_enabled()
        preference.uncheck()
        page.locator("#show-episode-progress").uncheck()
        page.locator("#settings-dialog .dialog-close").click()
        playwright_api.expect(card.locator("[data-episode-progress]")).to_have_count(0)
        if artwork:
            card.locator(".pmt-artwork-trigger").tap()
        playwright_api.expect(card.locator(".view-chip")).to_be_hidden()
        playwright_api.expect(card.locator(".entry-actions button:visible")).to_have_count(2)
        card.locator("[data-details]").click()
        playwright_api.expect(page.locator("#entry-count")).to_have_value(str(saved_count))
        assert (
            page.request.get(f"{tile_preview}/api/entries/{entry_id}").json()["view_count"]
            == saved_count
        )
        page.locator("#entry-dialog .dialog-close").click()
        page.locator("#open-settings").click()
        playwright_api.expect(page.locator("#interface-language")).to_be_enabled()
        page.locator("#show-episode-progress").check()
        page.locator("#settings-dialog .dialog-close").click()
        page.reload(wait_until="networkidle")
        playwright_api.expect(preference).not_to_be_checked()
        playwright_api.expect(card.locator(".view-chip")).to_be_hidden()
        browser.close()


@pytest.mark.parametrize("width", [1440, 390])
def test_reveal_all_tile_pages_except_rankings(tile_preview, tmp_path, width):
    with playwright_api.sync_playwright() as runtime:
        browser, page = start_gallery_page(runtime, tile_preview, width, width == 390)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        entry_id = page.locator("#library > .entry-card").first.get_attribute("data-entry")
        entry = page.request.get(f"{tile_preview}/api/entries/{entry_id}").json()
        enable_gallery(page)
        for view, host in [
            ("currently_watching", "#currently-watching-library"),
            ("active_shows", "#active-shows-library"),
        ]:
            # Stable active-release fixture: no live schedule/provider dependency.
            if view == "active_shows":
                page.route(
                    "**/api/releases/active-shows?*",
                    lambda route: route.fulfill(json={"items": [entry]}),
                )
            page.locator(f'.primary-nav [data-view="{view}"]').click()
            card = page.locator(f"{host} .media-artwork-card").first
            playwright_api.expect(card).to_be_visible()
            trigger = card.locator(".pmt-artwork-trigger")
            if width == 390:
                trigger.tap()
            else:
                trigger.hover(position={"x": 16, "y": 16})
            assert_panel_bounds(page, card.locator(".pmt-artwork-panel"))
            page.keyboard.press("Escape")
        created = page.request.post(
            f"{tile_preview}/api/lists", data={"name": f"Reveal test {width}"}
        ).json()
        assert page.request.post(
            f"{tile_preview}/api/lists/{created['id']}/entries/{entry_id}"
        ).ok
        page.locator('[data-view="lists"]').click()
        page.locator(f'[data-open-list="{created["id"]}"]').click()
        list_card = page.locator("#list-detail-library .media-artwork-card").first
        playwright_api.expect(list_card).to_be_visible()
        list_card.locator(".pmt-artwork-trigger").click()
        # On a mouse, entering first opens the panel and clicking toggles it shut.
        if list_card.locator(".pmt-artwork-trigger").get_attribute("aria-expanded") != "true":
            list_card.locator(".pmt-artwork-trigger").press("Enter")
        heart = list_card.locator("[data-favorite-toggle]")
        original = heart.get_attribute("aria-pressed")
        heart.click()
        playwright_api.expect(heart).to_have_attribute(
            "aria-pressed", "false" if original == "true" else "true"
        )
        heart.click()
        playwright_api.expect(heart).to_have_attribute("aria-pressed", original)
        page.locator('[data-view="rankings"]').click()
        playwright_api.expect(page.locator("#rankings-view")).to_be_visible()
        playwright_api.expect(
            page.locator("#rankings-view .ranking-tile").first
        ).to_be_visible()
        playwright_api.expect(
            page.locator(
                "#rankings-view .pmt-artwork-trigger, #rankings-view .pmt-artwork-grid"
            )
        ).to_have_count(0)
        assert page.locator("#rankings-view .ranking-tile").first.locator("h3").is_visible()
        show_recommendation_fixture(page)
        card = page.locator("#recommendation-results .media-artwork-card").first
        playwright_api.expect(card).to_be_visible()
        card.evaluate("el => el.scrollIntoView({block: 'center'})")
        if width == 390:
            card.locator(".pmt-artwork-trigger").tap()
        else:
            card.locator(".pmt-artwork-trigger").hover(position={"x": 16, "y": 16})
        panel = card.locator(".pmt-artwork-panel")
        assert_panel_bounds(page, panel)
        playwright_api.expect(panel.locator(".recommendation-score")).to_be_visible()
        assert panel.locator(".recommendation-result-actions button").count() > 0
        page.screenshot(
            path=str(tmp_path / f"recommendation-reveal-{width}.png"), animations="disabled"
        )
        page.locator("#open-settings").click()
        playwright_api.expect(page.locator("#interface-language")).to_be_enabled()
        page.locator("#artwork-reveal").uncheck()
        page.locator("#settings-dialog .dialog-close").click()
        playwright_api.expect(page.locator(".pmt-artwork-panel")).to_have_count(0)
        playwright_api.expect(
            page.locator(
                "#recommendation-results > .recommendation-result > .recommendation-copy"
            ).first
        ).to_be_visible()
        assert page.request.delete(f"{tile_preview}/api/lists/{created['id']}").ok
        browser.close()
        assert errors == []


@pytest.mark.parametrize("width,language", [(1440, "en"), (720, "fr"), (390, "zh-CN")])
def test_details_counter_description_and_unsaved_fields(
    tile_preview, tmp_path, width, language
):
    with playwright_api.sync_playwright() as runtime:
        browser, page = start_gallery_page(runtime, tile_preview, width, width == 390)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        # Deliberately exercise long provider text deterministically in every language.
        long_text = "A long provider description about this title and its characters. " * 35
        page.route(
            "**/api/entries/*/localized-metadata*",
            lambda route: route.fulfill(
                json={"status": "original", "language": language, "overview": long_text}
            ),
        )
        page.evaluate("language => applyInterfaceLanguage(language)", language)
        card = page.locator("#library > .media-anime")
        entry_id = card.get_attribute("data-entry")
        card.locator("[data-details]").click()
        dialog = page.locator("#entry-dialog")
        playwright_api.expect(dialog).to_be_visible()
        playwright_api.expect(dialog).to_have_css("transform", "none")
        playwright_api.expect(page.locator("#entry-dialog-art .status-chip")).to_have_count(0)
        playwright_api.expect(page.locator("#entry-status")).to_be_visible()
        poster = page.locator("#entry-dialog-art .poster").bounding_box()
        assert poster["width"] >= (112 if width <= 720 else 245)
        counter = page.locator("#entry-dialog-art [data-episode-progress]")
        playwright_api.expect(counter).to_be_visible()
        # Expanded details keep the original horizontal − watched / total +.
        playwright_api.expect(counter.locator(".episode-count-slash")).to_have_text("/")
        playwright_api.expect(counter.locator(".episode-count-divider")).to_have_count(0)
        numbers = counter.locator(".episode-counts").evaluate("""el => ({
            done: el.querySelector('strong').getBoundingClientRect().toJSON(),
            total: el.querySelector('.episode-total').getBoundingClientRect().toJSON()
        })""")
        assert numbers["done"]["right"] < numbers["total"]["left"]
        assert numbers["done"]["bottom"] == pytest.approx(numbers["total"]["bottom"], abs=2)
        meta = page.locator("#entry-dialog-art > div > p").bounding_box()
        assert counter.bounding_box()["y"] > meta["y"] + meta["height"]
        paragraph = page.locator(".entry-description > p")
        if language != "en":
            playwright_api.expect(paragraph).to_have_text(long_text.strip())
        else:
            # English correctly uses the saved provider description, no API call.
            assert len(paragraph.inner_text()) > 800
        toggle = page.locator(".pmt-description-toggle")
        playwright_api.expect(toggle).to_have_attribute("aria-expanded", "false")
        collapsed = paragraph.bounding_box()["height"]
        assert collapsed < 130
        toggle.click()
        playwright_api.expect(toggle).to_have_attribute("aria-expanded", "true")
        assert paragraph.bounding_box()["height"] > collapsed
        toggle.click()
        playwright_api.expect(toggle).to_have_attribute("aria-expanded", "false")
        page.locator("#entry-rating").fill("8.5")
        count = int(counter.get_attribute("data-watched"))
        counter.locator('[data-episode-step="-1"]').click()
        playwright_api.expect(counter).to_have_attribute("data-watched", str(count - 1))
        playwright_api.expect(page.locator("#entry-rating")).to_have_value("8.5")
        counter.locator('[data-episode-step="1"]').click()
        playwright_api.expect(counter).to_have_attribute("data-watched", str(count))
        assert (
            page.request.get(f"{tile_preview}/api/entries/{entry_id}").json()[
                "episode_progress"
            ]["watched"]
            == count
        )
        # Failed updates restore usable controls and leave saved values intact.
        page.route(
            f"**/api/entries/{entry_id}",
            lambda route: (
                route.fulfill(status=503, json={"error": {"message": "Preview failure"}})
                if route.request.method == "PATCH"
                else route.continue_()
            ),
        )
        counter.locator('[data-episode-step="-1"]').click()
        playwright_api.expect(counter.locator('[data-episode-step="-1"]')).to_be_enabled()
        playwright_api.expect(counter).to_have_attribute("data-watched", str(count))
        page.unroute(f"**/api/entries/{entry_id}")
        dialog.screenshot(
            path=str(tmp_path / f"details-{width}-{language}.png"), animations="disabled"
        )
        page.locator("#entry-dialog .dialog-close").click()
        # Turning counters off removes only progress, not the view count or history.
        page.locator("#open-settings").click()
        playwright_api.expect(page.locator("#interface-language")).to_be_enabled()
        page.locator("#show-episode-progress").uncheck()
        page.locator("#settings-dialog .dialog-close").click()
        playwright_api.expect(card.locator("[data-episode-progress]")).to_have_count(0)
        playwright_api.expect(card.locator(".view-chip")).to_have_count(1)
        card.locator("[data-details]").click()
        playwright_api.expect(
            page.locator("#entry-dialog-art [data-episode-progress]")
        ).to_have_count(0)
        page.locator("#entry-dialog .dialog-close").click()
        page.locator("#open-settings").click()
        page.locator("#show-episode-progress").check()
        page.locator("#settings-dialog .dialog-close").click()
        browser.close()
        assert errors == []


def start_gallery_page(runtime, base, width=1440, touch=False, reduced_motion="no-preference"):
    browser = runtime.chromium.launch(headless=True)
    page = browser.new_page(
        viewport={"width": width, "height": 900}, has_touch=touch, reduced_motion=reduced_motion
    )
    page.set_default_timeout(8000)
    page.request.put(
        f"{base}/api/settings/general",
        data={
            "onboarding_complete": True,
            "interface_language": "en",
            "show_episode_progress": True,
            "artwork_reveal": False,
            "show_tile_view_counts": False,
            "media_artwork_tint": False,
            "media_artwork_full_color": False,
        },
    )
    page.goto(f"{base}/?view=library", wait_until="networkidle")
    return browser, page


def enable_gallery(page):
    page.locator("#open-settings").click()
    playwright_api.expect(page.locator("#interface-language")).to_be_enabled()
    setting = page.locator("#artwork-reveal")
    playwright_api.expect(setting).not_to_be_checked()
    setting.check()
    page.locator("#settings-dialog .dialog-close").click()
    playwright_api.expect(page.locator("#library > .media-artwork-card")).to_have_count(24)


def assert_panel_bounds(page, panel):
    playwright_api.expect(panel).to_have_css("transform", "none")
    # Read both boxes in the same frame, including during smooth page scrolling.
    geometry = panel.evaluate("""el => ({
        panel: el.getBoundingClientRect().toJSON(),
        poster: el.parentElement.getBoundingClientRect().toJSON()
    })""")
    bounds = geometry["panel"]
    assert bounds["x"] >= 7
    assert bounds["x"] + bounds["width"] <= page.viewport_size["width"] - 7
    poster = geometry["poster"]
    assert bounds["x"] >= poster["x"]
    assert bounds["x"] + bounds["width"] <= poster["x"] + poster["width"]
    assert bounds["y"] >= poster["y"] + poster["height"] * 0.21
    assert bounds["y"] + bounds["height"] == pytest.approx(
        poster["y"] + poster["height"] - 1, abs=1
    )
    assert panel.evaluate("el => getComputedStyle(el).backgroundColor.endsWith('0.8)')")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert panel.evaluate("el => el.scrollWidth <= el.clientWidth + 1"), panel.evaluate(
        "el => ({width: el.clientWidth, scroll: el.scrollWidth, children: [...el.children].map(c => [c.className, c.clientWidth, c.scrollWidth])})"
    )


def test_artwork_hover_overlay_is_stable_and_keeps_live_controls(tile_preview, tmp_path):
    with playwright_api.sync_playwright() as runtime:
        browser, page = start_gallery_page(runtime, tile_preview)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        enable_gallery(page)
        card = page.locator("#library > .media-anime")
        panel = card.locator(".pmt-artwork-panel")
        trigger = card.locator(".pmt-artwork-trigger")
        playwright_api.expect(trigger).to_have_attribute("aria-expanded", "false")
        assert panel.evaluate("el => el.inert")
        before = page.locator("#library > .entry-card").evaluate_all(
            "els => els.map(el => { const r = el.getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; })"
        )
        trigger.hover(position={"x": 16, "y": 16})
        playwright_api.expect(trigger).to_have_attribute("aria-expanded", "true")
        playwright_api.expect(panel).to_be_visible()
        playwright_api.expect(panel).to_have_css("transform", "none")
        assert not panel.evaluate("el => el.inert")
        after = page.locator("#library > .entry-card").evaluate_all(
            "els => els.map(el => { const r = el.getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; })"
        )
        assert before == after
        assert_panel_bounds(page, panel)
        assert card.locator(".poster").bounding_box()["width"] > 200
        counter = panel.locator(".card-episode-progress")
        watched = int(counter.get_attribute("data-watched"))
        original_panel_bounds = panel.bounding_box()
        original_card_bounds = card.bounding_box()
        counter.locator("[data-episode-toggle]").click()
        counter.locator('[data-episode-step="-1"]').click()
        playwright_api.expect(counter).to_have_attribute("data-watched", str(watched - 1))
        assert panel.bounding_box() == pytest.approx(original_panel_bounds, abs=1)
        assert card.bounding_box() == pytest.approx(original_card_bounds, abs=1)
        playwright_api.expect(panel).to_be_visible()
        counter.locator('[data-episode-step="1"]').click()
        playwright_api.expect(counter).to_have_attribute("data-watched", str(watched))
        heart = panel.locator("[data-favorite-toggle]")
        original = heart.get_attribute("aria-pressed")
        heart.click()
        playwright_api.expect(heart).to_have_attribute(
            "aria-pressed", "false" if original == "true" else "true"
        )
        heart.click()
        playwright_api.expect(heart).to_have_attribute("aria-pressed", original)
        # Leaving after clicking a control must not leave the hover panel stuck.
        page.mouse.move(180, 60)
        playwright_api.expect(trigger).to_have_attribute("aria-expanded", "false")
        assert panel.evaluate("el => el.inert")
        # Even at the edge, every panel stays within its own poster.
        last_in_row = page.locator("#library > .entry-card").nth(4)
        last_in_row.locator(".pmt-artwork-trigger").hover(position={"x": 16, "y": 16})
        assert_panel_bounds(page, last_in_row.locator(".pmt-artwork-panel"))
        page.screenshot(path=str(tmp_path / "gallery-right-edge.png"), animations="disabled")
        page.mouse.move(180, 60)
        # This setting survives reload without changing saved media data.
        page.reload(wait_until="networkidle")
        playwright_api.expect(page.locator("#artwork-reveal")).to_be_checked()
        card.locator(".pmt-artwork-trigger").hover(position={"x": 16, "y": 16})
        panel.locator("[data-details]").click()
        playwright_api.expect(page.locator("#entry-dialog")).to_be_visible()
        page.locator("#entry-dialog .dialog-close").click()
        page.locator("#open-settings").click()
        page.locator("#artwork-reveal").uncheck()
        page.locator("#settings-dialog .dialog-close").click()
        playwright_api.expect(page.locator(".pmt-artwork-panel")).to_have_count(0)
        assert card.locator(".poster").bounding_box()["width"] == 144
        assert (
            page.locator("#library > .entry-card:not(.media-anime)")
            .first.locator(".poster")
            .bounding_box()["width"]
            == 144
        )
        browser.close()
        assert errors == []


@pytest.mark.parametrize("width,touch", [(390, True), (720, True), (1440, False)])
def test_artwork_keyboard_tap_and_reduced_motion(tile_preview, tmp_path, width, touch):
    with playwright_api.sync_playwright() as runtime:
        browser, page = start_gallery_page(runtime, tile_preview, width, touch, "reduce")
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        enable_gallery(page)
        card = page.locator("#library > .entry-card").first
        trigger = card.locator(".pmt-artwork-trigger")
        panel = card.locator(".pmt-artwork-panel")
        if touch:
            trigger.tap()
        else:
            page.keyboard.press("Tab")
            trigger.focus()
        playwright_api.expect(trigger).to_have_attribute("aria-expanded", "true")
        assert_panel_bounds(page, panel)
        assert (
            panel.evaluate("el => parseFloat(getComputedStyle(el).transitionDuration)") <= 0.001
        )
        page.screenshot(
            path=str(tmp_path / f"gallery-{width}-touch-{touch}.png"), animations="disabled"
        )
        panel.locator(".pmt-artwork-close").click()
        playwright_api.expect(trigger).to_have_attribute("aria-expanded", "false")
        playwright_api.expect(page.locator(".pmt-reveal-open")).to_have_count(0)
        playwright_api.expect(trigger).to_be_focused()
        page.keyboard.press("Enter")
        playwright_api.expect(trigger).to_have_attribute("aria-expanded", "true")
        page.keyboard.press("Escape")
        playwright_api.expect(trigger).to_have_attribute("aria-expanded", "false")
        playwright_api.expect(page.locator(".pmt-reveal-open")).to_have_count(0)
        playwright_api.expect(trigger).to_be_focused()
        assert panel.evaluate("el => el.inert")
        # Reopening with the keyboard preserves full access to the controls.
        page.keyboard.press("Enter")
        page.keyboard.press("Tab")
        assert panel.evaluate("el => el.contains(document.activeElement)")
        page.keyboard.press("Escape")
        page.locator("#open-settings").click()
        playwright_api.expect(page.locator("#interface-language")).to_be_enabled()
        page.evaluate("applyInterfaceLanguage('fr')")
        playwright_api.expect(page.locator(".pmt-artwork-reveal-setting strong")).to_have_text(
            "Volet sur l’affiche"
        )
        page.evaluate("applyInterfaceLanguage('zh-CN')")
        playwright_api.expect(page.locator(".pmt-artwork-reveal-setting strong")).to_have_text(
            "海报详情浮层"
        )
        browser.close()
        assert errors == []
