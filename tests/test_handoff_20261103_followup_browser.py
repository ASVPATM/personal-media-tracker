"""Exercise the actual pointer, keyboard, navigation and editing regressions."""

from uuid import uuid4

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect
from test_collection_design import _card, _seed, _switch
from test_collections_browser import browser_server as browser_server
from test_collections_browser import edit_panel
from test_collections_browser import page as page

pytestmark = pytest.mark.parametrize("page", ["chromium", "webkit"], indirect=True)


def settled(dialog):
    dialog.evaluate(
        "async e => { await new Promise(requestAnimationFrame); await Promise.allSettled(e.getAnimations().map(a => a.finished)); }"
    )


@pytest.mark.parametrize("domain", ["music", "books"])
def test_slow_search_keeps_focus_caret_and_all_characters(page, browser_server, domain):
    title = f"Search typing {uuid4()}"
    _seed(page, browser_server, domain, title=title)
    _switch(page, domain)
    search = page.locator("#music-query")
    search.click()
    for index, character in enumerate("Search typing", 1):
        # Deliberately pause long enough for each debounced response to render.
        with page.expect_response(lambda r: f"/api/{domain}/" in r.url and "q=" in r.url):
            search.press_sequentially(character)
        expect(page.locator("#music-content")).to_have_attribute("aria-busy", "false")
        expect(search).to_be_focused()
        expect(search).to_have_value("Search typing"[:index])
        assert search.evaluate("e => e.selectionStart") == index
    expect(page.locator("#music-content")).to_contain_text(title)


def test_settings_is_a_real_page_and_remembers_workspace_and_subpage(page):
    _switch(page, "books")
    page.locator("#open-settings").click()
    settings = page.locator("#settings-view")
    expect(settings).to_be_visible()
    assert settings.evaluate("e => e.tagName === 'SECTION' && e.parentElement.id === 'main'")
    expect(page.locator("dialog[open]")).to_have_count(0)
    expect(page.locator("#open-settings")).to_have_attribute("aria-current", "page")
    page.locator('[data-settings-tab="data"]').click()
    assert (
        "mode=books" in page.url
        and "view=settings" in page.url
        and "settings_tab=data" in page.url
    )
    page.reload(wait_until="networkidle")
    expect(page.locator('[data-settings-panel="data"]')).to_be_visible()
    expect(page.locator("html")).to_have_attribute("data-workspace", "books")
    page.locator('[data-settings-tab="general"]').click()
    page.go_back(wait_until="networkidle")
    expect(page.locator('[data-settings-panel="data"]')).to_be_visible()
    page.locator('.primary-nav [data-view="music_library"]').click()
    expect(settings).to_be_hidden()
    expect(page.locator("#music-heading")).to_have_text("Book library")


@pytest.mark.parametrize("width", [1440, 900, 390])
def test_settings_appearance_labels_and_range_stay_inside_one_box(page, width):
    page.set_viewport_size({"width": width, "height": 1000})
    page.locator("#open-settings").click()
    expect(page.locator("#general-timezone")).to_be_enabled()
    expect(page.locator(".navigation-setting legend")).to_have_count(0)
    box = page.locator(".appearance-colors").bounding_box()
    for selector in (
        ".accent-setting h4",
        ".background-setting h4",
        ".background-image-setting h4",
        "#background-strength",
        "#background-mode",
    ):
        rect = page.locator(selector).bounding_box()
        assert rect["x"] >= box["x"] and rect["y"] >= box["y"]
        assert rect["x"] + rect["width"] <= box["x"] + box["width"] + 1
        assert rect["y"] + rect["height"] <= box["y"] + box["height"] + 1
    assert page.locator("#background-strength").bounding_box()["width"] > box["width"] * 0.4
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")


@pytest.mark.parametrize("width", [1440, 1000, 900])
def test_album_has_separate_content_sized_box_to_the_right(page, browser_server, width):
    row = _seed(
        page, browser_server, "music", tracks=[{"title": "One track", "disc": 1, "position": 1}]
    )
    page.set_viewport_size({"width": width, "height": 950})
    _switch(page, "music")
    _card(page, row).locator("[data-open-music]").click()
    expect(page.locator("#music-track-preview")).to_contain_text("One track")
    settled(page.locator("#music-editor"))
    main, side = (
        page.locator("#music-editor .detail-main"),
        page.locator("#music-track-sidecar"),
    )
    expect(main).to_be_visible()
    assert side.evaluate("e => e.closest('.detail-main') === null")
    assert (
        page.locator("#music-editor").evaluate("e => getComputedStyle(e).backgroundColor")
        == "rgba(0, 0, 0, 0)"
    )
    bounds, sidebar = main.bounding_box(), side.bounding_box()
    assert sidebar["x"] >= bounds["x"] + bounds["width"] + 8
    assert abs(sidebar["y"] - bounds["y"]) < 2
    assert sidebar["height"] < bounds["height"] / 2
    assert bounds["height"] <= 640
    for tab in ("notes", "genres", "metadata", "details"):
        edit_panel(page, tab)
        assert main.bounding_box() == bounds
    assert page.locator("#music-editor").bounding_box()["width"] <= width - 16


def test_follow_series_populates_the_separate_right_box(page, browser_server):
    identifier = str(uuid4())
    response = page.request.post(
        browser_server + "/api/entries/manual",
        data={
            "canonical_title": "Follow test " + identifier,
            "media_type": "tv",
            "status": "watching",
            "provider_source": "tmdb_tv",
            "provider_id": identifier,
            "tmdb_tv_id": identifier,
        },
    )
    assert response.ok
    entry = response.json()["entry"]
    page.set_viewport_size({"width": 1000, "height": 900})
    page.reload(wait_until="networkidle")
    page.locator(f'[data-entry="{entry["id"]}"] [data-details]').click()
    expect(page.locator("#follow-series")).to_be_visible()
    settled(page.locator("#entry-dialog"))
    main = page.locator("#entry-dialog .detail-main").bounding_box()
    side = page.locator("#entry-episodes-sidecar").bounding_box()
    assert side["x"] > main["x"] + main["width"] and abs(side["y"] - main["y"]) < 2
    expect(page.locator("#series-release-panel .season-card")).to_have_count(0)
    page.locator("#follow-series").click()
    expect(page.locator("#series-release-panel")).to_contain_text("Season 1")
    assert page.locator("#entry-dialog .detail-main").bounding_box() == main
    page.locator('[data-entry-tab="notes"]').click()
    expect(page.locator("#series-release-panel")).to_contain_text("Season 1")


def test_more_actions_are_inline_and_leave_closes_after_pointer_click(page, browser_server):
    row = _seed(page, browser_server, "music")
    _switch(page, "music")
    _card(page, row).locator("[data-open-music]").click()
    menu = page.locator("#music-more-actions")
    summary = menu.locator("summary")
    summary.hover()
    expect(menu.locator("div")).to_be_visible()
    a, b = summary.bounding_box(), menu.locator("div").bounding_box()
    footer = page.locator("#music-editor .dialog-footer").bounding_box()
    save = page.locator("#music-save").bounding_box()
    assert b["x"] >= a["x"] + a["width"]
    assert b["y"] >= footer["y"] and b["y"] + b["height"] <= footer["y"] + footer["height"]
    assert b["x"] + b["width"] <= save["x"]
    styles = menu.locator("button:visible").evaluate_all(
        "nodes=>nodes.map(e=>{const s=getComputedStyle(e);return [s.borderRadius,s.fontSize,s.padding]})"
    )
    assert all(style == styles[0] for style in styles)
    summary.click()  # Pointer focus must not make the disclosure persistent.
    page.locator("#music-editor-title").hover()
    expect(menu).not_to_have_attribute("open", "")
    summary.focus()
    summary.press("Enter")
    expect(menu.locator("div")).to_be_visible()
    # Arrow navigation also works with macOS's default limited Tab navigation.
    summary.press("ArrowDown")
    expect(menu.locator("button").first).to_be_focused()
    menu.locator("button").first.press("Escape")
    expect(menu).not_to_have_attribute("open", "")
    expect(summary).to_be_focused()


@pytest.mark.parametrize("domain", ["music", "books"])
def test_rating_hover_and_artwork_heart_have_precise_targets(page, browser_server, domain):
    row = _seed(page, browser_server, domain, rating=7, favorite=False)
    _switch(page, domain)
    _card(page, row).locator("[data-open-music]").click()
    rating = page.locator("#music-personal-rating")
    bar = rating.locator("..")
    rating.hover()
    colors = bar.locator("button, input").evaluate_all(
        "nodes=>nodes.map(e=>getComputedStyle(e).backgroundColor)"
    )
    assert len(set(colors)) == 1 and colors[0] == "rgba(0, 0, 0, 0)"
    assert bar.evaluate("e=>getComputedStyle(e).boxShadow") != "none"
    page.locator('label[for="music-personal-rating"]').click(position={"x": 5, "y": 5})
    expect(rating).to_be_focused()
    expect(rating).to_have_value("7")
    heart = page.locator("#music-detail-favorite")
    expect(page.locator('.entry-detail-controls input[name="favorite"]')).to_have_count(0)
    assert heart.evaluate("e=>!!e.closest('.detail-art-meta')")
    page.locator("#music-detail-creator").click()
    expect(heart).to_have_attribute("aria-pressed", "false")
    heart.click()
    expect(heart).to_have_attribute("aria-pressed", "true")
    edit_panel(page, "notes")
    page.locator('#music-form [name="notes"]').fill("Keep my pending note")
    page.locator("#music-save").click()
    expect(page.locator("#music-editor")).to_be_hidden()
    route = "albums" if domain == "music" else "entries"
    saved = page.request.get(f"{browser_server}/api/{domain}/{route}/{row['id']}").json()
    assert (
        saved["favorite"] is True
        and saved["notes"] == "Keep my pending note"
        and saved["rating"] == 7
    )


@pytest.mark.parametrize("domain", ["music", "books"])
def test_active_collection_count_is_inside_toolbar(page, domain):
    _switch(page, domain)
    page.locator('.primary-nav [data-view="music_listening"]').click()
    expect(page.locator("#music-content")).to_have_attribute("aria-busy", "false")
    assert page.locator("#music-count").evaluate("e=>!!e.closest('.music-toolbar')")


def test_every_sidebar_utility_uses_the_same_hover_effect(page):
    samples = []
    for selector in ("#open-notifications", "#open-recommendations", "#open-settings"):
        control = page.locator(selector)
        control.hover()
        settled(control)
        samples.append(
            control.evaluate(
                "e=>{const s=getComputedStyle(e);return [s.boxShadow,s.borderColor,s.backgroundColor,s.transform]}"
            )
        )
    assert all(sample == samples[0] for sample in samples)
    assert samples[0][0] != "none"
