from __future__ import annotations

from uuid import uuid4

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")
from test_browser_e2e import browser_server as browser_server  # noqa: E402


@pytest.fixture
def page(browser_server, request):
    with playwright_api.sync_playwright() as playwright:
        browser = getattr(playwright, getattr(request, "param", "chromium")).launch(
            headless=True
        )
        page = browser.new_page(
            viewport={"width": 1440, "height": 1000}, reduced_motion="reduce"
        )
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.request.put(
            f"{browser_server}/api/settings/general",
            data={
                "onboarding_complete": True,
                "interface_language": "en",
                "media_artwork_tint": False,
                "media_artwork_full_color": False,
                "artwork_reveal": False,
                **{
                    f"{mode}_artwork_{option}": False
                    for mode in ("music", "books")
                    for option in ("tint", "full_color", "reveal")
                },
            },
        )
        page.goto(browser_server, wait_until="networkidle")
        yield page
        browser.close()
        assert errors == []


def open_manual(page):
    page.locator("#quick-add-shortcut").click()
    playwright_api.expect(page.locator("#music-search-dialog")).to_be_visible()
    playwright_api.expect(page.locator("#music-editor")).to_be_hidden()
    playwright_api.expect(page.locator("#music-manual-add")).to_be_hidden()
    page.locator("#music-manual-entry summary").click()
    page.locator("#music-manual-add").click()
    playwright_api.expect(page.locator("#music-editor")).to_be_visible()


def edit_panel(page, panel="notes"):
    if panel == "catalog":
        if not page.locator("#music-more-actions").evaluate("node => node.open"):
            page.locator("#music-more-actions summary").click()
        page.locator("#music-edit-catalog").click()
        return
    page.locator(f'[data-collection-tab="{panel}"]').click()


def edit_tracks(page):
    page.locator("#music-more-actions summary").click()
    page.locator("#music-edit-tracklist").click()


@pytest.mark.parametrize(
    "domain,expected_heading", [("music", "Music library"), ("books", "Book library")]
)
def test_manual_collection_workflow_and_isolation(
    page, browser_server, domain, expected_heading
):
    movie_count = page.request.get(f"{browser_server}/api/entries").json()["total"]
    title = f"Manual {domain} {str(uuid4())[:8]}"
    page.locator(f'button[data-workspace="{domain}"]').click()
    playwright_api.expect(page.locator("#music-heading")).to_have_text(expected_heading)
    playwright_api.expect(
        page.locator('.primary-nav [data-view="active_shows"]')
    ).to_be_hidden()
    playwright_api.expect(page.locator("#open-recommendations")).to_be_visible()
    playwright_api.expect(page.locator("#open-notifications")).to_be_visible()
    open_manual(page)
    edit_panel(page, "catalog")
    page.locator("#music-title").fill(title)
    page.locator('#music-form [name="artist"]').fill("Synthetic Creator")
    edit_panel(page, "details")
    playwright_api.expect(page.locator('#music-form [name="status"]')).to_have_value(
        "plan_to_listen"
    )
    page.locator('#music-form [name="rating"]').fill("8.5")
    if domain == "music":
        edit_tracks(page)
        page.locator("#music-add-track").click()
        page.locator(".track-title").fill("Opening track")
        page.locator(".track-duration").fill("3:15")
    else:
        playwright_api.expect(page.locator(".music-track-table")).to_be_hidden()
        edit_panel(page, "catalog")
        page.locator('#music-form [name="page_count"]').fill("240")
        edit_panel(page, "contents")
        page.locator('#music-form [name="chapters"]').fill("Beginning\nMiddle\nEnd")
        edit_panel(page, "details")
        page.locator('#music-form [name="current_page"]').fill("48")
    page.locator("#music-save").click()
    playwright_api.expect(page.locator("#music-editor")).to_be_hidden()
    card = page.locator(".music-card").filter(has_text=title)
    playwright_api.expect(card).to_be_visible()
    card.locator("[data-open-music]").first.click()
    edit_panel(page)
    playwright_api.expect(page.locator("#music-save")).to_be_disabled()
    page.locator('#music-form [name="notes"]').fill("Saved note")
    page.locator("#music-save").click()
    playwright_api.expect(page.locator("#music-editor")).to_be_hidden()
    page.reload(wait_until="networkidle")
    playwright_api.expect(page.locator("#music-heading")).to_have_text(expected_heading)
    page.locator(".music-card").filter(has_text=title).locator(
        "[data-open-music]"
    ).first.click()
    edit_panel(page)
    playwright_api.expect(page.locator('#music-form [name="notes"]')).to_have_value(
        "Saved note"
    )
    page.locator("#music-editor .dialog-close").click()
    page.locator('button[data-workspace="screen"]').click()
    playwright_api.expect(page.locator("#library-view")).to_be_visible()
    assert page.request.get(f"{browser_server}/api/entries").json()["total"] == movie_count
    other = "music" if domain == "books" else "books"
    page.locator(f'button[data-workspace="{other}"]').click()
    playwright_api.expect(page.locator("#music-content")).not_to_contain_text(title)
    page.go_back()
    playwright_api.expect(page.locator("#library-view")).to_be_visible()
    page.go_back()
    playwright_api.expect(page.locator("#music-heading")).to_have_text(expected_heading)
    playwright_api.expect(page.locator("#music-content")).to_contain_text(title)


def test_unified_settings_exports_and_icon_placement(page):
    assert page.locator("#open-recommendations").inner_text() == ""
    positions = page.evaluate(
        """() => ['open-notifications','open-recommendations','open-settings'].map(id => document.getElementById(id).getBoundingClientRect().x)"""
    )
    assert positions == sorted(positions)
    for minimized in (False, True):
        page.evaluate(
            "value => document.documentElement.dataset.sidebarMode = value",
            "minimized" if minimized else "expanded",
        )
        geometry = page.locator("#workspace-switch button").evaluate_all(
            "buttons => buttons.map(button => { const r = button.getBoundingClientRect(); return {x:r.x, y:r.y, bottom:r.bottom, right:r.right}; })"
        )
        assert geometry[0]["bottom"] <= geometry[1]["y"] < geometry[2]["y"]
        assert geometry[0]["x"] == geometry[2]["x"]
        assert (
            geometry[-1]["bottom"] < page.locator(".sidebar-lower-actions").bounding_box()["y"]
        )
    for mode in ["music", "books"]:
        page.locator(f'button[data-workspace="{mode}"]').click()
        for action in ("recommendations", "notifications", "settings"):
            playwright_api.expect(page.locator(f"#open-{action}")).to_be_visible()
        for action in ("recommendations", "notifications"):
            page.locator(f"#open-{action}").click()
            playwright_api.expect(page.locator("html")).to_have_attribute(
                "data-workspace", mode
            )
            playwright_api.expect(page.locator("#music-content")).to_contain_text(
                "not available yet"
            )
            playwright_api.expect(page.locator(f"#{action}-view")).to_be_hidden()
        page.locator("#open-settings").click()
        page.locator('[data-settings-tab="general"]').click()
        settings_groups = page.locator(".settings-tabs").evaluate(
            """tabs => {
              const system = tabs.querySelector('.settings-tab-group-general');
              const collections = tabs.querySelector('.settings-tab-group-collections');
              return {systemBottom:system.getBoundingClientRect().bottom,
                collectionsTop:collections.getBoundingClientRect().top,
                groupTabs:[...collections.querySelectorAll('[data-settings-tab]')].map(node => node.dataset.settingsTab)};
            }"""
        )
        assert settings_groups["collectionsTop"] >= settings_groups["systemBottom"] + 12
        assert settings_groups["groupTabs"] == ["screen", "music", "books"]
        playwright_api.expect(page.locator(".general-advanced-ratings")).to_be_hidden()
        playwright_api.expect(page.locator("#show-episode-progress")).to_be_hidden()
        for section in ("screen", "music", "books", "access", "shortcuts", "about"):
            playwright_api.expect(
                page.locator(f'[data-settings-tab="{section}"]')
            ).to_be_visible()
        page.locator(f'[data-settings-tab="{mode}"]').click()
        playwright_api.expect(page.locator("#tmdb-token")).to_be_hidden()
        playwright_api.expect(page.locator(f"#{mode}-artwork-tint")).to_be_visible()
        playwright_api.expect(page.locator("html")).to_have_attribute("data-workspace", mode)
        page.locator('[data-settings-tab="screen"]').click()
        page.locator('[data-screen-settings-tab="appearance"]').click()
        playwright_api.expect(page.locator(".general-advanced-ratings")).to_be_visible()
        playwright_api.expect(page.locator("html")).to_have_attribute("data-workspace", mode)
        page.locator('[data-settings-tab="data"]').click()
        page.locator("#collection-export-scope").select_option(mode)
        playwright_api.expect(page.locator("#collection-export")).to_have_attribute(
            "href", f"/api/exports/{'book' if mode == 'books' else 'music'}-collection.json"
        )
        page.locator("#settings-dialog .dialog-close").click()
    page.locator('button[data-workspace="screen"]').click()
    page.locator("#open-settings").click()
    page.locator('[data-settings-tab="screen"]').click()
    page.locator('[data-screen-settings-tab="appearance"]').click()
    playwright_api.expect(page.locator(".general-advanced-ratings")).to_be_visible()


@pytest.mark.parametrize("mode,width", [("music", 390), ("books", 390), ("books", 1024)])
def test_responsive_collection_navigation(page, mode, width, tmp_path):
    page.set_viewport_size({"width": width, "height": 844})
    page.locator(f'button[data-workspace="{mode}"]').click()
    open_manual(page)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    box = page.locator("#music-editor").bounding_box()
    assert box["x"] >= 0 and box["x"] + box["width"] <= width + 1
    page.screenshot(path=str(tmp_path / f"{mode}-{width}.png"), full_page=True)


def test_music_metadata_preview_is_explicit_and_retains_notes(page):
    identifier = str(uuid4())
    metadata = {
        "title": "Provider album",
        "artist": "Provider Artist",
        "year": 2022,
        "release_type": "album",
        "provider_id": identifier,
        "genres": ["Ambient"],
        "tracks": [
            {
                "id": str(uuid4()),
                "disc": 1,
                "position": 1,
                "title": "Intro",
                "artist": "",
                "duration_ms": 100000,
                "recording_id": None,
            }
        ],
    }
    page.route(
        "**/api/music/search?*",
        lambda route: route.fulfill(
            json={
                "results": [
                    {
                        "provider_id": identifier,
                        "title": "Provider album",
                        "artist": "Provider Artist",
                        "track_count": 1,
                    }
                ]
            }
        ),
    )
    page.route(
        f"**/api/music/metadata/{identifier}", lambda route: route.fulfill(json=metadata)
    )
    page.locator('button[data-workspace="music"]').click()
    open_manual(page)
    edit_panel(page)
    page.locator('#music-form [name="notes"]').fill("Keep this private note")
    edit_panel(page, "metadata")
    page.locator("#music-find-metadata").click()
    page.locator('#music-search-form [name="query"]').fill("Provider album")
    page.locator('#music-search-form button[type="submit"]').click()
    page.locator("[data-music-result]").click()
    playwright_api.expect(page.locator("#music-search-dialog")).to_be_hidden()
    playwright_api.expect(page.locator("#music-title")).to_have_value("Provider album")
    playwright_api.expect(page.locator('#music-form [name="notes"]')).to_have_value(
        "Keep this private note"
    )
    playwright_api.expect(page.locator(".track-title")).to_have_value("Intro")
    page.locator("#music-save").click()
    playwright_api.expect(page.locator("#music-editor")).to_be_hidden()


@pytest.mark.parametrize("mode", ["music", "books"])
def test_collection_lists_ratings_favorites_and_insights(page, browser_server, mode):
    endpoint = "albums" if mode == "music" else "entries"
    creator = "artist" if mode == "music" else "author"
    title = f"Collection tools {uuid4()}"
    row = page.request.post(
        f"{browser_server}/api/{mode}/{endpoint}",
        data={
            "title": title,
            creator: "Synthetic Creator",
            "rating": 9,
            "genres": ["Synthetic"],
        },
    ).json()
    empty_list = page.request.post(
        f"{browser_server}/api/{mode}/lists", data={"name": "Empty layout fixture"}
    )
    assert empty_list.ok
    page.locator(f'button[data-workspace="{mode}"]').click()
    card = page.locator(f'[data-music-id="{row["id"]}"]')
    card.locator("[data-favorite-music]").click()
    playwright_api.expect(card.locator("[data-favorite-music]")).to_have_attribute(
        "aria-pressed", "true"
    )
    page.locator('.music-nav[data-view="music_rankings"]').click()
    playwright_api.expect(page.locator("#music-content")).to_contain_text(title)
    page.locator('.music-nav[data-view="music_lists"]').click()
    playwright_api.expect(
        page.locator(".music-toolbar #music-list-tools #music-list-sort")
    ).to_be_visible()
    page.locator('#music-create-list [name="name"]').fill("New test list")
    page.locator("#music-create-list button").click()
    listing = page.locator(".music-list-card").filter(has_text="New test list")
    playwright_api.expect(listing).to_be_visible()
    for width in (1440, 900):
        page.set_viewport_size({"width": width, "height": 1000})
        rectangles = page.locator(".music-list-card").evaluate_all(
            "nodes => nodes.map(node => node.getBoundingClientRect().toJSON())"
        )
        assert len(rectangles) >= 2
        assert (
            max(rect["left"] for rect in rectangles) - min(rect["left"] for rect in rectangles)
            <= 1
        )
        assert (
            max(rect["right"] for rect in rectangles)
            - min(rect["right"] for rect in rectangles)
            <= 1
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    page.set_viewport_size({"width": 1440, "height": 1000})
    playwright_api.expect(listing.locator("details, summary")).to_have_count(0)
    listing.locator("[data-open-music-list]").click()
    page.locator(".music-toolbar #music-list-rename").click()
    page.locator(".music-toolbar .music-rename-form input").fill("Renamed test list")
    page.locator('.music-toolbar .music-rename-form [type="submit"]').click()
    playwright_api.expect(page.locator("#music-heading")).to_have_text("Renamed test list")
    page.locator('.music-nav[data-view="music_library"]').click()
    page.locator(f'[data-music-id="{row["id"]}"] [data-open-music]').first.click()
    edit_panel(page, "notes")
    page.locator("#music-membership summary").click()
    page.locator("#music-list-picker label").filter(has_text="Renamed test list").locator(
        "input"
    ).check()
    playwright_api.expect(page.locator("#music-list-picker input").first).to_be_enabled()
    page.locator("#music-editor .dialog-close").click()
    page.locator('.music-nav[data-view="music_lists"]').click()
    page.locator("#music-list-sort").select_option("count")
    if page.locator("#music-list-direction").inner_text() == "↑":
        page.locator("#music-list-direction").click()
    page.locator(".music-list-card").filter(has_text="Renamed test list").locator(
        "[data-open-music-list]"
    ).click()
    playwright_api.expect(page.locator("#music-heading")).to_have_text("Renamed test list")
    playwright_api.expect(page.locator("#music-filters")).to_be_visible()
    playwright_api.expect(page.locator("#music-content")).to_contain_text(title)
    page.locator("#music-list-delete").click()
    playwright_api.expect(page.locator("#confirm-dialog")).to_contain_text(
        "Only the list is removed."
    )
    page.locator('#confirm-dialog .confirm-actions [value="cancel"]').click()
    playwright_api.expect(page.locator("#music-heading")).to_have_text("Renamed test list")
    page.locator(".music-toolbar #music-back-lists").click()
    playwright_api.expect(page.locator(".music-toolbar #music-list-tools")).to_be_visible()
    page.locator(".music-list-card").filter(has_text="Renamed test list").locator(
        "[data-open-music-list]"
    ).click()
    page.locator("#music-list-delete").click()
    page.locator("#confirm-submit").click()
    playwright_api.expect(page.locator(".music-toolbar #music-list-tools")).to_be_visible()
    playwright_api.expect(
        page.locator(".music-list-card").filter(has_text="Renamed test list")
    ).to_have_count(0)
    assert page.request.get(f"{browser_server}/api/{mode}/{endpoint}/{row['id']}").ok
    playwright_api.expect(
        page.locator(".music-list-card").filter(has_text="Empty layout fixture")
    ).to_be_visible()
    page.locator('.music-nav[data-view="music_insights"]').click()
    playwright_api.expect(page.locator(".music-chart-grid")).to_contain_text("Synthetic")


@pytest.mark.parametrize(
    "locale,heading,creator",
    [("fr", "Bibliothèque de livres", "Auteur"), ("zh-CN", "图书资料库", "作者")],
)
def test_books_localization_and_switching_back_to_music(
    page, browser_server, locale, heading, creator
):
    page.request.put(
        f"{browser_server}/api/settings/general", data={"interface_language": locale}
    )
    page.goto(f"{browser_server}/?view=book_library&mode=books", wait_until="networkidle")
    playwright_api.expect(page.locator("#music-heading")).to_have_text(heading)
    open_manual(page)
    edit_panel(page, "metadata")
    playwright_api.expect(
        page.locator('#music-form [name="artist"]').locator("..")
    ).to_contain_text(creator)
    page.locator("#music-editor .dialog-close").click()
    page.locator('button[data-workspace="music"]').click()
    playwright_api.expect(page.locator("#music-heading")).to_have_text(
        "Bibliothèque musicale" if locale == "fr" else "音乐资料库"
    )


def test_book_metadata_cover_and_private_progress_are_preserved(page):
    metadata = {
        "title": "Selected edition",
        "author": "Provider Author",
        "year": 2019,
        "book_format": "paperback",
        "provider_id": "OL123M",
        "page_count": 300,
        "genres": ["Fiction"],
        "artwork_url": "https://covers.openlibrary.org/b/id/42-L.jpg",
        "chapters": ["Opening"],
    }
    page.route(
        "**/api/books/search?*", lambda route: route.fulfill(json={"results": [metadata]})
    )
    page.route("**/api/books/metadata/OL123M", lambda route: route.fulfill(json=metadata))
    page.locator('button[data-workspace="books"]').click()
    open_manual(page)
    edit_panel(page)
    page.locator('#music-form [name="notes"]').fill("My private note")
    edit_panel(page, "details")
    page.locator('#music-form [name="current_page"]').fill("10")
    edit_panel(page, "metadata")
    page.locator("#music-find-metadata").click()
    page.locator('#music-search-form [name="query"]').fill("Selected edition")
    page.locator('#music-search-form button[type="submit"]').click()
    page.locator("[data-music-result]").click()
    playwright_api.expect(page.locator("#music-title")).to_have_value("Selected edition")
    playwright_api.expect(page.locator('#music-form [name="current_page"]')).to_have_value("10")
    playwright_api.expect(page.locator('#music-form [name="notes"]')).to_have_value(
        "My private note"
    )
    page.locator("#music-save").click()
    playwright_api.expect(page.locator("#music-editor")).to_be_hidden()
    playwright_api.expect(page.locator("#music-content")).to_contain_text("10/300")
