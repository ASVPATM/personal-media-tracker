"""Tile state, ranking layout, narrow counters, and reveal regressions."""

from __future__ import annotations

import pytest
from test_media_tiles_browser import browser_server as browser_server
from test_media_tiles_browser import (
    enable_gallery,
    open_screen_appearance,
    playwright_api,
    show_recommendation_fixture,
    start_gallery_page,
)
from test_media_tiles_browser import (
    tile_preview as tile_preview,
)


def tracking_snapshot(page, host="#library"):
    return page.locator(f"{host} .entry-card[data-entry]").evaluate_all("""cards => cards.map(card => ({
        id: card.dataset.entry,
        title: card.querySelector('h3').textContent,
        status: card.querySelector('.status-chip').textContent,
        genres: [...card.querySelectorAll('.genre-chip')].map(chip => chip.textContent),
        views: card.querySelector('.view-chip').dataset.viewCount,
        favorite: card.querySelector('[data-favorite-toggle]').getAttribute('aria-pressed')
    }))""")


@pytest.mark.parametrize(
    "width,language,technical",
    [
        (1440, "en", False),
        (1440, "fr", True),
        (1024, "en", False),
        (720, "fr", False),
        (390, "zh-CN", False),
        (390, "zh-CN", True),
        (320, "fr", True),
    ],
)
def test_rankings_give_posters_space_and_right_align_details(
    tile_preview, tmp_path, width, language, technical
):
    with playwright_api.sync_playwright() as runtime:
        browser, page = start_gallery_page(runtime, tile_preview, width, width <= 390)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        assert page.request.put(
            f"{tile_preview}/api/settings/general",
            data={"advanced_ratings_enabled": technical},
        ).ok
        payload = page.request.get(
            f"{tile_preview}/api/rankings?mode=personal&show_all=true"
        ).json()
        row = payload["items"][0]
        row["entry"]["catalog_item"]["canonical_title"] = (
            "A Very Long Title: The Extraordinary Adventures Beyond the Last Horizon"
        )
        row["personal_rating"] = 10
        row["technical_score"] = 9.25 if technical else None
        row["comparison_count"] = 128 if technical else 0
        page.route("**/api/rankings?*", lambda route: route.fulfill(json=payload))
        page.evaluate("language => applyInterfaceLanguage(language)", language)
        if technical:
            page.evaluate("state.rankingMode = 'technical'")
        page.locator('[data-view="rankings"]').click()
        tile = page.locator("#rankings-list .ranking-tile").first
        playwright_api.expect(tile).to_be_visible()
        geometry = tile.evaluate("""tile => {
            const rect = selector => tile.querySelector(selector).getBoundingClientRect().toJSON();
            return {card: tile.getBoundingClientRect().toJSON(), poster: rect('.poster'),
                copy: rect('.ranking-copy'), scores: rect('.ranking-scores'), footer: rect('.ranking-footer')};
        }""")
        poster = geometry["poster"]
        assert poster["width"] >= (110 if width <= 720 else 136)
        assert poster["width"] >= geometry["card"]["width"] * 0.37
        assert poster["height"] == pytest.approx(poster["width"] * 1.5, abs=1)
        for section in ("copy", "scores", "footer"):
            assert geometry[section]["left"] > poster["right"]
            assert geometry[section]["right"] == pytest.approx(geometry["copy"]["right"], abs=1)
        for selector in (
            ".ranking-copy",
            ".ranking-copy h3",
            ".ranking-copy .entry-meta",
            ".ranking-scores",
        ):
            playwright_api.expect(tile.locator(selector)).to_have_css("text-align", "right")
        assert tile.evaluate("el => el.scrollWidth <= el.clientWidth + 1")
        page.screenshot(path=str(tmp_path / f"rankings-page-{width}.png"))
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
            page.evaluate("""() => [...document.querySelectorAll('#rankings-view *')]
            .filter(el => el.getBoundingClientRect().right > innerWidth + 1)
            .slice(0, 12).map(el => ({tag:el.tagName,id:el.id,cls:el.className,right:el.getBoundingClientRect().right}))""")
        )
        assert tile.locator(
            ".ranking-scores > span"
        ).evaluate_all("""nodes => nodes.every(node =>
            node.scrollWidth <= node.clientWidth + 1 && node.querySelector('small').scrollWidth <= node.querySelector('small').clientWidth + 1)""")
        playwright_api.expect(tile.locator(".technical-score")).to_have_count(
            1 if technical else 0
        )
        ranks = page.locator(".ranking-position").all_text_contents()
        # Reveal mode must not transform Rankings, even after changing appearance.
        open_screen_appearance(page)
        playwright_api.expect(page.locator("#interface-language")).to_be_enabled()
        page.locator("#artwork-reveal").check()
        page.locator("#settings-dialog .dialog-close").click()
        playwright_api.expect(tile.locator(".pmt-artwork-trigger")).to_have_count(0)
        assert page.locator(".ranking-position").all_text_contents() == ranks
        tile.screenshot(path=str(tmp_path / f"rankings-{width}-{language}-{technical}.png"))
        tile.locator("[data-ranking-details]").click()
        playwright_api.expect(page.locator("#entry-dialog")).to_be_visible()
        browser.close()
        assert errors == []


@pytest.mark.parametrize(
    "tint,blend,language",
    [
        (False, False, "en"),
        (True, False, "en"),
        (False, True, "en"),
        (True, True, "en"),
        (True, True, "fr"),
        (True, True, "zh-CN"),
    ],
)
def test_artwork_reveal_suspends_treatments_and_uses_selected_heart_accent(
    tile_preview, tint, blend, language
):
    with playwright_api.sync_playwright() as runtime:
        browser, page = start_gallery_page(runtime, tile_preview)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        saved = page.request.put(
            f"{tile_preview}/api/settings/general",
            data={
                "artwork_reveal": True,
                "media_artwork_tint": tint,
                "media_artwork_full_color": blend,
                "interface_language": language,
                "theme": "dark",
                "accent_color": "#24cd09",
            },
        )
        assert saved.ok
        page.reload(wait_until="networkidle")
        card = page.locator("#library > .media-anime")
        for _ in range(2):
            # Existing saved combinations and later preference renders must both
            # preserve the absolute overlay layout, not merely its open class.
            assert page.locator("html").get_attribute("data-media-artwork-tint") is None
            assert page.locator("html").get_attribute("data-media-artwork-full-color") is None
            card.locator(".pmt-artwork-trigger").hover(position={"x": 16, "y": 16})
            panel = card.locator(".pmt-artwork-panel")
            playwright_api.expect(panel).to_have_css("position", "absolute")
            playwright_api.expect(panel).to_have_css("transform", "none")
            playwright_api.expect(panel).to_have_css("pointer-events", "auto")
            favorite = card.locator("[data-favorite-toggle]")
            if favorite.get_attribute("aria-pressed") != "true":
                favorite.click()
            playwright_api.expect(favorite).to_have_attribute("aria-pressed", "true")
            playwright_api.expect(favorite).to_have_css("color", "rgb(36, 205, 9)")
            playwright_api.expect(favorite.locator("svg")).to_have_css(
                "fill", "rgb(36, 205, 9)"
            )
            open_screen_appearance(page)
            playwright_api.expect(page.locator("#interface-language")).to_be_enabled()
            for selector, chosen in [
                ("#media-artwork-tint", tint),
                ("#media-artwork-full-color", blend),
            ]:
                control = page.locator(selector)
                playwright_api.expect(control).to_be_disabled()
                assert control.is_checked() is chosen
                reason = control.get_attribute("aria-description")
                assert (
                    reason
                    and {"en": "choices are kept", "fr": "conservés", "zh-CN": "保留"}[language]
                    in reason
                )
            # Turning reveal off restores the exact two independent choices.
            page.locator("#artwork-reveal").uncheck()
            for selector, chosen, attribute in [
                ("#media-artwork-tint", tint, "data-media-artwork-tint"),
                ("#media-artwork-full-color", blend, "data-media-artwork-full-color"),
            ]:
                control = page.locator(selector)
                playwright_api.expect(control).to_be_enabled()
                assert control.is_checked() is chosen
                assert page.locator("html").get_attribute(attribute) == (
                    "true" if chosen else None
                )
            page.locator("#artwork-reveal").check()
            page.evaluate("async () => await state.appearanceSave")
            page.locator("#settings-dialog .dialog-close").click()
            page.reload(wait_until="networkidle")
        browser.close()
        assert errors == []


@pytest.mark.parametrize(
    "width,artwork", [(1440, False), (1440, True), (390, False), (390, True)]
)
def test_finished_preference_save_preserves_complete_tile_information(
    tile_preview, width, artwork
):
    with playwright_api.sync_playwright() as runtime:
        browser, page = start_gallery_page(runtime, tile_preview, width, width == 390)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        if artwork:
            enable_gallery(page)
        before = tracking_snapshot(page)
        assert all(row["status"] and row["genres"] for row in before)
        for shown in [False, True, False, True]:
            # Await the *whole* handler, including the queued appearance write.
            # Immediate visibility alone missed the later destructive re-render.
            page.evaluate("async shown => await saveEpisodeProgressPreference(shown)", shown)
            assert tracking_snapshot(page) == before
            counters = page.locator("#library .card-episode-progress")
            if shown:
                assert counters.count() > 0
            else:
                playwright_api.expect(counters).to_have_count(0)
        page.evaluate("""async () => await Promise.all([
            saveEpisodeProgressPreference(false), saveEpisodeProgressPreference(true),
            saveEpisodeProgressPreference(false), saveEpisodeProgressPreference(true)
        ])""")
        assert tracking_snapshot(page) == before
        assert page.locator("#library .card-episode-progress").count() > 0
        assert not any(row["views"] == "undefined" for row in tracking_snapshot(page))
        assert set(page.evaluate("Object.keys(displayEntries.values().next().value)")) == {
            "id",
            "catalog_item",
        }
        browser.close()
        assert errors == []


@pytest.mark.parametrize("width,artwork", [(1440, False), (1440, True), (390, True)])
def test_vertical_episode_counter_beside_favorite_and_info(tile_preview, width, artwork):
    with playwright_api.sync_playwright() as runtime:
        browser, page = start_gallery_page(runtime, tile_preview, width, width == 390)
        if artwork:
            enable_gallery(page)
        card = page.locator("#library > .media-anime")
        if artwork:
            if width == 390:
                card.locator(".pmt-artwork-trigger").tap()
            else:
                card.locator(".pmt-artwork-trigger").hover(position={"x": 16, "y": 16})
            playwright_api.expect(card.locator(".pmt-artwork-panel")).to_have_css(
                "transform", "none"
            )
        boxes = card.evaluate("""card => Object.fromEntries(Object.entries({
            heart:'[data-favorite-toggle]', info:'[data-details]', counter:'.card-episode-progress',
            count:'[data-episode-toggle]'
        }).map(([key, selector]) => [key, card.querySelector(selector).getBoundingClientRect().toJSON()]))""")
        fraction = card.locator(".episode-counts").evaluate("""el => {
            const rect = node => node.getBoundingClientRect().toJSON();
            return {done: rect(el.querySelector('strong')),
                    bar: rect(el.querySelector('.episode-count-divider')),
                    total: rect(el.querySelector('.episode-total')),
                    border: getComputedStyle(el.querySelector('.episode-count-divider')).borderTopStyle};
        }""")
        assert boxes["counter"]["width"] <= 28
        assert boxes["counter"]["height"] <= boxes["heart"]["height"]
        assert fraction["done"]["bottom"] <= fraction["bar"]["top"]
        assert fraction["bar"]["bottom"] <= fraction["total"]["top"]
        assert fraction["bar"]["height"] <= 1
        assert fraction["border"] == "solid"
        assert fraction["done"]["x"] == pytest.approx(fraction["total"]["x"], abs=1)
        assert "/" not in card.locator(".episode-counts").inner_text()
        assert boxes["counter"]["right"] < boxes["info"]["left"]
        assert boxes["heart"]["bottom"] <= boxes["info"]["top"]
        assert boxes["counter"]["bottom"] == pytest.approx(boxes["info"]["bottom"], abs=1)
        counter = card.locator(".card-episode-progress")
        playwright_api.expect(counter.locator("[data-episode-menu]")).to_be_hidden()
        counter.locator("[data-episode-toggle]").click()
        playwright_api.expect(counter.locator("[data-episode-menu]")).to_be_visible()
        watched = int(counter.get_attribute("data-watched"))
        counter.locator('[data-episode-step="-1"]').click()
        playwright_api.expect(counter).to_have_attribute("data-watched", str(watched - 1))
        counter.locator('[data-episode-step="1"]').click()
        playwright_api.expect(counter).to_have_attribute("data-watched", str(watched))
        page.keyboard.press("Escape")
        playwright_api.expect(counter.locator("[data-episode-menu]")).to_be_hidden()
        playwright_api.expect(counter.locator("[data-episode-toggle]")).to_be_focused()
        card.locator("[data-details]").click()
        playwright_api.expect(page.locator("#entry-dialog")).to_be_visible()
        browser.close()


@pytest.mark.parametrize("recommendations", [False, True])
@pytest.mark.parametrize("delta", [150, -100])
def test_reveal_close_is_centered_and_wheel_scrolls_page(tile_preview, recommendations, delta):
    with playwright_api.sync_playwright() as runtime:
        browser, page = start_gallery_page(runtime, tile_preview)
        enable_gallery(page)
        page.evaluate("async () => await state.appearanceSave")
        if recommendations:
            show_recommendation_fixture(page)
            host = page.locator("#recommendation-results")
        else:
            host = page.locator("#library")
        # This checks wheel routing, not the number of rows in a fixture. Give
        # it explicit scroll space above/below, independent of font/column count.
        host.evaluate("el => el.style.paddingBlock = '100vh'")
        card = host.locator(".media-artwork-card").nth(5)
        playwright_api.expect(card).to_be_visible()
        card.evaluate("el => el.scrollIntoView({block:'center', behavior:'instant'})")
        card.locator(".pmt-artwork-trigger").hover(position={"x": 16, "y": 16})
        panel = card.locator(".pmt-artwork-panel")
        playwright_api.expect(panel).to_have_css("transform", "none")
        center = panel.locator(".pmt-artwork-close").evaluate("""button => {
            const box = button.getBoundingClientRect(), icon = button.querySelector('svg').getBoundingClientRect();
            return [box.x + box.width / 2 - icon.x - icon.width / 2, box.y + box.height / 2 - icon.y - icon.height / 2];
        }""")
        assert center == pytest.approx([0, 0], abs=0.5)
        # Add deterministic overflow so this also covers long recommendations.
        panel.evaluate("el => { el.style.maxHeight='130px'; el.scrollTop=0; }")
        assert panel.evaluate("el => el.scrollHeight > el.clientHeight")
        panel.locator(".entry-copy, .recommendation-score").hover(position={"x": 16, "y": 16})
        panel.evaluate("el => el.scrollTop=0")
        playwright_api.expect(panel).to_have_attribute("aria-hidden", "false")
        before = page.evaluate("scrollY")
        assert before >= abs(delta)
        assert page.evaluate(
            "document.scrollingElement.scrollHeight - innerHeight - scrollY"
        ) >= abs(delta)
        page.evaluate("""() => {
            document.addEventListener('wheel', () => {
                window.revealWheelStart = scrollY;
            }, {capture: true, once: true});
            document.addEventListener('wheel', event => {
                window.observedRevealWheel = {
                    panel: Boolean(event.target.closest('.pmt-artwork-panel')),
                    prevented: event.defaultPrevented, delta: event.deltaY,
                    trusted: event.isTrusted, movement: scrollY - window.revealWheelStart
                };
            }, {once: true});
        }""")
        # Each direction starts independently: re-hovering after a previous
        # gesture can itself scroll the page and invalidate its starting point.
        page.mouse.wheel(0, delta)
        page.wait_for_function("() => window.observedRevealWheel !== undefined")
        assert page.evaluate("window.observedRevealWheel") == {
            "panel": True,
            "prevented": True,
            "delta": delta,
            "trusted": True,
            "movement": pytest.approx(delta, abs=1),
        }
        # The handler scrolls instantly. Compare within the actual event so a
        # later async layout/scroll-anchor update cannot falsify its displacement.
        assert panel.evaluate("el => el.scrollTop") == 0
        # Browser zoom gestures must retain their native default behavior.
        allowed = panel.evaluate(
            "el => el.dispatchEvent(new WheelEvent('wheel', {bubbles:true,cancelable:true,ctrlKey:true,deltaY:20}))"
        )
        assert allowed
        browser.close()
