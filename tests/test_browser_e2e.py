from __future__ import annotations

import re
from datetime import date, timedelta

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")

from watchtracker import __version__  # noqa: E402
from watchtracker.app import create_app  # noqa: E402
from watchtracker.config import Settings  # noqa: E402
from watchtracker.launcher import ServerController  # noqa: E402
from watchtracker.schemas import CatalogData, SearchResponse, SearchResult  # noqa: E402
from watchtracker.services.secrets import SecretStore  # noqa: E402


class BrowserKeyring:
    value = None

    def get_password(self, _service_name, _username):
        return self.value

    def set_password(self, _service_name, _username, password):
        self.value = password

    def delete_password(self, _service_name, _username):
        self.value = None


class BrowserMetadata:
    result = SearchResult(
        provider="tmdb_movie",
        provider_id="browser-101",
        title="The Browser Film",
        year=2024,
        media_type="movie",
        poster_url="https://images.invalid/browser-poster.jpg",
        overview="Synthetic metadata for an offline browser test.",
    )

    async def search(self, query: str, media_type: str | None = None) -> SearchResponse:
        results = [self.result] if not media_type or media_type == "movie" else []
        return SearchResponse(results=results)

    async def detail(self, result: SearchResult) -> CatalogData:
        return CatalogData(
            canonical_title=result.title,
            release_year=result.year,
            media_type=result.media_type,
            provider_source=result.provider,
            provider_id=result.provider_id,
            tmdb_movie_id=result.provider_id,
            provider_genres=["Drama", "Mystery"],
            keywords=["synthetic fixture"],
            poster_url=result.poster_url,
            overview=result.overview,
        )

    async def close(self) -> None:
        return None

    def configure_tmdb(self, _token: str | None) -> None:
        return None

    def provider_catalog(self):
        return []

    def preferred_identity(
        self,
        external_ids: dict[str, str],
        *,
        capability: str,
        primary: tuple[str | None, str | None] = (None, None),
    ):
        del external_ids, capability
        return primary if all(primary) else None

    async def series_schedule(
        self, provider: str, provider_id: str | None = None, *, refresh: bool = False
    ):
        del refresh
        if provider_id is None:
            provider_id = provider
            provider = "tmdb_tv"
        tomorrow = date.today() + timedelta(days=1)
        return {
            "provider_source": provider,
            "provider_series_id": provider_id,
            "status": "Returning Series",
            "seasons": [
                {
                    "provider_season_id": "browser-season-1",
                    "season_number": 1,
                    "title": "Season 1",
                    "air_date": "2024-01-01",
                    "episode_count": 2,
                    "episodes": [
                        {
                            "provider_episode_id": "browser-episode-1",
                            "episode_number": 1,
                            "title": "Released Browser Episode",
                            "air_date": "2024-01-01",
                        },
                        {
                            "provider_episode_id": "browser-episode-2",
                            "episode_number": 2,
                            "title": "Upcoming Browser Episode",
                            "air_date": tomorrow.isoformat(),
                        },
                    ],
                }
            ],
        }


@pytest.fixture(scope="module")
def browser_server(tmp_path_factory):
    root = tmp_path_factory.mktemp("browser-e2e")
    settings = Settings(
        _env_file=None,
        data_dir=root / "data",
        config_dir=root / "config",
        log_dir=root / "logs",
        backups_dir=root / "backups",
        database_path=root / "watchtracker.sqlite3",
        cache_dir=root / "cache",
        env_path=root / ".env",
        timezone="UTC",
        release_mode=True,
        access_mode="local",
        database_url_override=None,
    )
    controller = ServerController(
        create_app(
            settings,
            metadata_service=BrowserMetadata(),
            secret_store=SecretStore(settings, keyring_backend=BrowserKeyring()),
        ),
        "127.0.0.1",
        0,
    )
    controller.start()
    yield controller.url
    controller.stop()


@pytest.fixture(scope="module")
def browser_page(browser_server):
    with playwright_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        page.goto(browser_server)
        yield page
        context.close()
        browser.close()


def _close_dialog(page, selector: str) -> None:
    dialog = page.locator(selector)
    if dialog.get_attribute("open") is not None:
        dialog.locator(".dialog-close").click()


def test_complete_private_diary_browser_flow(browser_page, browser_server, tmp_path):
    page = browser_page

    # First-run onboarding can be completed without a provider credential.
    onboarding = page.locator("#onboarding-dialog")
    playwright_api.expect(onboarding).to_be_visible()
    onboarding.get_by_role("button", name="Get started").click()
    onboarding.get_by_role("button", name="Skip for now").click()
    onboarding.get_by_role("button", name="Search for a title").click()
    playwright_api.expect(page.locator("#search-input")).to_be_focused()
    playwright_api.expect(page.locator("#open-notifications")).to_be_visible()

    # One-character search, add, and explicit duplicate behavior.
    page.locator("#search-input").fill("B")
    playwright_api.expect(page.locator(".search-result")).to_be_visible()
    page.locator(".search-result").click()
    quick_details = page.locator("#quick-add-details-dialog")
    playwright_api.expect(quick_details).to_be_visible()
    quick_details.locator("#quick-rating").fill("8.5")
    quick_details.get_by_role("button", name="Add to library", exact=True).click()
    playwright_api.expect(
        page.locator(".entry-card", has_text="The Browser Film")
    ).to_be_visible()
    page.locator("#quick-add-shortcut").click()
    page.locator("#search-input").fill("B")
    playwright_api.expect(page.locator(".search-result")).to_be_visible()
    page.locator(".search-result").click()
    playwright_api.expect(quick_details).to_be_visible()
    quick_details.get_by_role("button", name="Add to library", exact=True).click()
    duplicate = page.locator("#duplicate-actions")
    playwright_api.expect(duplicate).to_contain_text("already in your library")
    duplicate.get_by_role("button", name="Add rewatch today").click()
    playwright_api.expect(page.locator(".entry-card", has_text="2 views")).to_be_visible()

    # Compact, information-button-only tiles plus full detail editing.
    assert page.get_by_role("button", name="List layout").count() == 0
    card = page.locator(".entry-card", has_text="The Browser Film")
    entry_dialog = page.locator("#entry-dialog")
    assert card.locator("[data-inline]").count() == 0
    assert card.locator(".rating-badge").count() == 0
    card.locator("h3").click()
    playwright_api.expect(entry_dialog).to_be_hidden()
    card.get_by_role("button", name="Information about The Browser Film").click()
    playwright_api.expect(entry_dialog).to_be_visible()
    community_help = entry_dialog.get_by_label("Community score help")
    community_help.hover()
    dialog_tooltip = entry_dialog.locator("#floating-help-tooltip")
    playwright_api.expect(dialog_tooltip).to_be_visible()
    playwright_api.expect(dialog_tooltip).to_contain_text("provider community average")
    entry_dialog.locator("#entry-rating").hover()
    playwright_api.expect(dialog_tooltip).to_be_hidden()
    entry_dialog.get_by_role("tab", name="Notes & tags").click()
    page.locator("#entry-notes").fill("<img src=x onerror=alert(1)> synthetic note")
    page.locator("#entry-tags").fill("browser, synthetic")
    entry_dialog.get_by_role("tab", name="Metadata").click()
    playwright_api.expect(page.locator("#entry-metadata-state")).to_contain_text("verified")
    entry_dialog.get_by_role("tab", name="Details").click()
    page.locator("#entry-rating").fill("9.1")
    entry_dialog.locator('[data-step-for="entry-count"][data-step-direction="1"]').click()
    assert page.locator("#entry-count").input_value() == "3"
    entry_dialog.get_by_role("button", name="Save changes").click()
    playwright_api.expect(card).not_to_contain_text("9.1/10")
    card.get_by_role("button", name="Information about The Browser Film").click()
    assert page.locator("#entry-rating").input_value() == "9.1"
    assert page.locator("#entry-count").input_value() == "3"
    entry_dialog.get_by_role("tab", name="Details").click()
    playwright_api.expect(page.locator("#entry-started")).to_be_visible()
    started_box = page.locator("#entry-started").bounding_box()
    watched_box = page.locator("#entry-watched").bounding_box()
    finished_box = page.locator("#entry-finished").bounding_box()
    status_box = page.locator("#entry-status").bounding_box()
    rating_box = page.locator("#entry-rating").bounding_box()
    count_box = page.locator("#entry-count").bounding_box()
    assert (
        started_box and watched_box and finished_box and status_box and rating_box and count_box
    )
    # Chromium can round date-control subpixels differently across Linux runners.
    same_row_tolerance = 4
    assert abs(status_box["y"] - rating_box["y"]) < same_row_tolerance
    assert abs(status_box["y"] - count_box["y"]) < same_row_tolerance
    assert abs(started_box["y"] - watched_box["y"]) < same_row_tolerance
    assert abs(started_box["y"] - finished_box["y"]) < same_row_tolerance
    assert started_box["y"] > status_box["y"] + status_box["height"]
    assert (
        page.locator("#entry-rating").evaluate(
            "element => getComputedStyle(element).appearance"
        )
        == "textfield"
    )
    assert (
        page.locator("#entry-count").evaluate("element => getComputedStyle(element).appearance")
        == "textfield"
    )
    normal_viewport = page.viewport_size
    page.set_viewport_size({"width": 390, "height": 844})
    narrow_date_stack_box = page.locator(".entry-date-stack").bounding_box()
    narrow_status_box = page.locator("#entry-status").bounding_box()
    narrow_started_box = page.locator("#entry-started").bounding_box()
    narrow_finished_box = page.locator("#entry-finished").bounding_box()
    narrow_rating_box = page.locator("#entry-rating").bounding_box()
    assert (
        narrow_date_stack_box
        and narrow_status_box
        and narrow_started_box
        and narrow_finished_box
        and narrow_rating_box
    )
    assert narrow_status_box["y"] < narrow_rating_box["y"] < narrow_started_box["y"]
    assert narrow_started_box["y"] < narrow_finished_box["y"]
    page.set_viewport_size(normal_viewport)
    entry_dialog.get_by_role("tab", name="History").click()
    history_delete = page.locator("#viewing-history [data-event]").last
    history_delete.click()
    page.locator("#confirm-submit").click()
    playwright_api.expect(page.locator("#viewing-history [data-event]")).to_have_count(1)
    more_actions = entry_dialog.locator(".more-actions")
    more_actions.locator("summary").click()
    playwright_api.expect(more_actions).to_have_attribute("open", "")
    _close_dialog(page, "#entry-dialog")
    card.get_by_role("button", name="Information about The Browser Film").click()
    playwright_api.expect(more_actions).not_to_have_attribute("open", "")
    more_actions.locator("summary").click()
    summary_box = more_actions.locator("summary").bounding_box()
    delete_box = page.locator("#delete-entry").bounding_box()
    assert summary_box and delete_box and delete_box["x"] > summary_box["x"]
    _close_dialog(page, "#entry-dialog")

    # Manual add and import preview/commit use only synthetic local content.
    page.locator("#quick-add-shortcut").click()
    page.locator("#open-manual").click()
    manual = page.locator("#manual-dialog")
    manual.locator("[name='canonical_title']").fill("Manual Browser Series")
    manual.locator("[name='media_type']").select_option("tv")
    manual.locator("[name='status']").select_option("watching")
    manual.get_by_role("button", name="Add to library").click()
    playwright_api.expect(
        page.locator(".entry-card", has_text="Manual Browser Series")
    ).to_be_visible()
    tracked_response = page.request.post(
        f"{browser_server}/api/entries/manual",
        data={
            "canonical_title": "Tracked Browser Series",
            "media_type": "tv",
            "status": "watching",
            "provider_source": "tmdb_tv",
            "provider_id": "browser-series-1",
            "tmdb_tv_id": "browser-series-1",
            "episode_count": 2,
        },
    )
    assert tracked_response.ok
    tracked_entry_id = tracked_response.json()["entry"]["id"]
    page.reload()
    playwright_api.expect(page.locator("#library")).to_have_attribute("aria-busy", "false")
    refresh_library = page.locator("#refresh-library")
    refresh_library.click()
    playwright_api.expect(refresh_library).to_be_enabled()
    refresh_library.click()
    playwright_api.expect(refresh_library).to_be_enabled()
    tracked_card = page.locator(".entry-card", has_text="Tracked Browser Series")
    progress = tracked_card.locator("[data-episode-progress]")
    playwright_api.expect(progress).to_contain_text("0 / 2 episodes")
    progress.get_by_role("button", name="Increase watched episode count").click()
    playwright_api.expect(progress).to_contain_text("1 / 2 episodes")

    import_file = tmp_path / "browser-import.csv"
    import_file.write_text(
        "title,year,media_type,watched_status,user_rating,rewatch_count,external_tmdb_id,notes\n"
        "Imported Browser Film,2021,movie,watched,7.6,0,555001,synthetic import\n",
        encoding="utf-8",
    )
    page.locator("#open-settings").click()
    page.locator("#settings-dialog").get_by_role("tab", name="Data & Backup").click()
    page.locator("#settings-dialog").get_by_role("button", name="Import a list").click()
    page.locator("#import-form [name='file']").set_input_files(import_file)
    page.locator("#import-form").get_by_role("button", name="Preview").click()
    playwright_api.expect(page.locator("#import-preview")).to_contain_text("1 parsed")
    page.locator("#enrich-after-import").uncheck()
    page.locator("#commit-form").get_by_role("button", name="Commit import").click()
    playwright_api.expect(page.locator("#import-message")).to_contain_text("Import complete")
    _close_dialog(page, "#import-dialog")
    playwright_api.expect(
        page.locator(".entry-card", has_text="Imported Browser Film")
    ).to_be_visible()
    # Imports opened from Settings intentionally return there after the import dialog closes.
    playwright_api.expect(page.locator("#settings-dialog")).to_be_visible()
    _close_dialog(page, "#settings-dialog")
    playwright_api.expect(page.locator("#settings-dialog")).to_be_hidden()

    # Filters and URL state remain useful and omit personal fields.
    page.locator("#toggle-filters").click()
    page.locator("#filter-form [name='media_type']").select_option("tv")
    page.locator("#filter-form").get_by_role("button", name="Apply filters").click()
    playwright_api.expect(page.locator(".entry-card")).to_have_count(2)
    assert "media_type=tv" in page.url
    assert "note" not in page.url and "rating" not in page.url and "token" not in page.url
    page.locator("#filter-form").get_by_role("button", name="Clear").click()
    playwright_api.expect(page.locator(".entry-card")).to_have_count(4)

    # Seed enough synthetic records to exercise pagination and page-size controls.
    for index in range(25):
        response = page.request.post(
            f"{browser_server}/api/entries/manual",
            data={
                "canonical_title": "History"
                if index == 0
                else f"Pagination Fixture {index:02d}",
                "media_type": "movie",
                "status": "plan_to_watch",
            },
        )
        assert response.ok
    page.reload()
    playwright_api.expect(page.locator("#library")).to_have_attribute("aria-busy", "false")
    next_page = page.locator("#pagination button[data-page='2']:not([aria-label])")
    playwright_api.expect(next_page).to_be_visible()
    next_page.click()
    playwright_api.expect(page.locator("#pagination [aria-current='page']")).to_have_text("2")
    assert "page=2" in page.url
    page.locator("#page-size").select_option("48")
    playwright_api.expect(page.locator("#pagination")).to_be_empty()
    assert "page_size=48" in page.url
    assert page.get_by_role("button", name="Grid layout").count() == 0
    layout_card = page.locator(".entry-card", has_text="The Browser Film")
    poster_box = layout_card.locator(".poster").bounding_box()
    title_box = layout_card.locator(".entry-copy").bounding_box()
    signals_box = layout_card.locator(".entry-signals").bounding_box()
    views_box = layout_card.locator(".view-chip").bounding_box()
    layout_box = layout_card.bounding_box()
    assert poster_box and title_box and signals_box and views_box and layout_box
    assert poster_box["width"] >= 118
    assert title_box["x"] > poster_box["x"] + poster_box["width"]
    assert signals_box["y"] >= poster_box["y"] + poster_box["height"]
    assert views_box["x"] < layout_box["x"] + (layout_box["width"] / 2)
    assert layout_card.locator(".entry-signals .genre-chip").count() <= 2
    genre_tops = layout_card.locator(".entry-signals .genre-chip").evaluate_all(
        "items => items.map(item => item.getBoundingClientRect().top)"
    )
    assert len({round(value) for value in genre_tops}) <= 1
    assert page.locator(".app-sidebar").bounding_box()["width"] < 180

    # Theme, navigation, exports, backup UI, and user-configured shortcuts.
    assert page.locator(".app-sidebar h1").count() == 0
    assert page.locator("#theme-toggle").count() == 0
    assert page.locator(".export-menu").count() == 0
    page.locator("#open-settings").click()
    theme_settings = page.locator("#settings-dialog")
    playwright_api.expect(page.locator("#open-account")).to_be_hidden()
    theme_settings.get_by_role("tab", name="Access & Devices").click()
    playwright_api.expect(theme_settings.locator("#access-mode-chip")).to_have_text(
        "Not detected"
    )
    playwright_api.expect(theme_settings.locator("#server-mode-toggle")).to_be_disabled()
    playwright_api.expect(theme_settings.locator(".server-package-card")).to_be_visible()
    playwright_api.expect(theme_settings.locator(".server-package-card")).to_contain_text(
        "separate PMT Server Beta package"
    )
    playwright_api.expect(theme_settings.locator("#personal-tailscale-card")).to_be_visible()
    playwright_api.expect(
        theme_settings.locator("#tailscale-private-connection-section")
    ).to_contain_text("Tailscale private connection setup")
    playwright_api.expect(theme_settings.locator("#pmt-server-mode-section")).to_contain_text(
        "Connect this application to PMT Server"
    )
    playwright_api.expect(theme_settings.locator("#personal-tailscale-toggle")).to_be_disabled()
    assert theme_settings.locator("#shared-access-setup").count() == 0
    playwright_api.expect(theme_settings.locator("#server-readiness")).to_be_hidden()
    theme_settings.get_by_role("tab", name="General", exact=True).click()
    with page.expect_response(
        lambda response: (
            response.url.endswith("/api/settings/general") and response.request.method == "PUT"
        )
    ):
        theme_settings.locator("#theme-preference").select_option("dark")
    assert page.locator("html").get_attribute("data-theme") in {"light", "dark"}
    # Advanced rating controls now live compactly in General rather than a separate tab.
    with page.expect_response(
        lambda response: (
            response.url.endswith("/api/settings/general") and response.request.method == "PUT"
        )
    ):
        theme_settings.locator("#advanced-ratings-enabled").check()
    playwright_api.expect(page.locator("#advanced-ratings-state")).to_contain_text("Enabled")
    theme_settings.get_by_role("tab", name="Shortcuts").click()
    playwright_api.expect(theme_settings.locator("#shortcut-editor kbd")).to_have_count(7)
    for value in theme_settings.locator("#shortcut-editor kbd").all():
        playwright_api.expect(value).to_have_text("Not set")
    theme_settings.locator('[data-record-shortcut="rankings"]').click()
    page.keyboard.press("Meta+Alt+R")
    playwright_api.expect(
        theme_settings.locator('[data-shortcut-row="rankings"] kbd')
    ).not_to_have_text("Not set")
    theme_settings.locator('[data-record-shortcut="currently_watching"]').click()
    page.keyboard.press("Meta+Alt+W")
    playwright_api.expect(
        theme_settings.locator('[data-shortcut-row="currently_watching"] kbd')
    ).not_to_have_text("Not set")
    _close_dialog(page, "#settings-dialog")

    # Former defaults do nothing; only the combinations the user chose work.
    page.keyboard.press("Meta+Shift+3")
    playwright_api.expect(page.locator("#library-view")).to_be_visible()
    page.keyboard.press("Meta+Alt+R")
    playwright_api.expect(page.locator("#rankings-view")).to_be_visible()
    page.keyboard.press("Meta+Alt+W")
    playwright_api.expect(
        page.locator("#currently-watching-library", has_text="Manual Browser Series")
    ).to_be_visible()
    assert "view=currently_watching" in page.url
    assert page.locator("#currently-watching-view .release-status-strip").count() == 0
    normal_viewport = page.viewport_size
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(220)
    watching_scope = page.locator("#watching-scope")
    playwright_api.expect(watching_scope).to_be_visible()
    watching_select = watching_scope
    playwright_api.expect(watching_select).to_be_visible()
    assert watching_select.evaluate(
        "element => element.scrollWidth <= element.clientWidth && "
        "element.scrollHeight <= element.clientHeight"
    )
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )
    assert watching_select.locator("option").all_text_contents() == [
        "All active & planned",
        "Watching",
        "Rewatching",
        "Plan to watch",
    ]
    page.set_viewport_size({"width": 820, "height": 844})
    page.wait_for_timeout(220)
    assert watching_select.evaluate(
        "element => element.scrollWidth <= element.clientWidth && "
        "element.scrollHeight <= element.clientHeight"
    )
    page.get_by_role("button", name="Rankings", exact=True).click()
    assert page.locator("#rankings-filter-form").evaluate(
        "toolbar => { const items = [...toolbar.querySelectorAll(':scope > *')].filter(item => "
        "getComputedStyle(item).display !== 'none'); const rects = items.map(item => "
        "item.getBoundingClientRect()); return rects.every((a, index) => rects.slice(index + 1)"
        ".every(b => a.right <= b.left || b.right <= a.left || a.bottom <= b.top || "
        "b.bottom <= a.top)); }"
    )
    page.get_by_role("button", name="Library", exact=True).click()
    assert page.locator(".library-toolbar .toolbar-actions").evaluate(
        "toolbar => { const rects = [...toolbar.children].filter(item => "
        "getComputedStyle(item).display !== 'none').map(item => item.getBoundingClientRect()); "
        "return rects.every((a, index) => rects.slice(index + 1).every(b => a.right <= b.left "
        "|| b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top)); }"
    )
    page.set_viewport_size(normal_viewport)

    # Release tracking lives in the compact Active Shows heading.
    page.get_by_role("button", name="Active Shows", exact=True).click()
    assert page.locator("#release-check-dialog").count() == 0
    playwright_api.expect(page.locator("#release-check-mode")).not_to_be_checked()
    playwright_api.expect(page.locator("#release-sync-status")).to_contain_text(
        "Manual checks only"
    )
    playwright_api.expect(page.locator("#active-shows-library")).to_contain_text(
        "No confirmed active shows"
    )
    assert (
        page.locator(
            "#active-shows-library .entry-card", has_text="Manual Browser Series"
        ).count()
        == 0
    )
    page.locator("#sync-releases").click()
    tracked_card = page.locator(
        "#active-shows-library .entry-card", has_text="Tracked Browser Series"
    )
    playwright_api.expect(tracked_card).to_be_visible()
    assert (
        page.locator(
            "#active-shows-library .entry-card", has_text="Manual Browser Series"
        ).count()
        == 0
    )
    tracked_card.get_by_role("button", name="Information about Tracked Browser Series").click()
    release_tab = page.locator("#entry-dialog").get_by_role("tab", name="Episodes & releases")
    release_tab.click()
    assert page.locator("#follow-series").count() == 0
    playwright_api.expect(page.locator("#series-release-panel")).to_contain_text("Season 1")
    season_button = page.locator("#series-release-panel .season-card-button").first
    season_drawer = page.locator("#season-episode-drawer")
    playwright_api.expect(season_button).to_have_attribute("aria-expanded", "false")
    playwright_api.expect(season_drawer).to_be_hidden()
    season_button.click()
    playwright_api.expect(season_button).to_have_attribute("aria-expanded", "true")
    playwright_api.expect(season_drawer).to_be_visible()
    page.wait_for_timeout(220)
    season_card_box = season_button.locator("..").bounding_box()
    release_main_box = page.locator("#series-release-panel .series-release-main").bounding_box()
    season_drawer_box = season_drawer.bounding_box()
    assert season_card_box and release_main_box and season_drawer_box
    assert season_drawer_box["x"] >= release_main_box["x"] + release_main_box["width"]
    assert abs(season_drawer_box["y"] - release_main_box["y"]) < 3
    normal_viewport = page.viewport_size
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(220)
    narrow_season_card_box = season_button.locator("..").bounding_box()
    narrow_release_layout_box = page.locator(
        "#series-release-panel .series-release-layout"
    ).bounding_box()
    narrow_season_drawer_box = season_drawer.bounding_box()
    assert narrow_season_card_box and narrow_release_layout_box and narrow_season_drawer_box
    assert abs(narrow_season_drawer_box["x"] - narrow_release_layout_box["x"]) < 2
    assert narrow_season_drawer_box["width"] <= narrow_release_layout_box["width"] + 2
    assert (
        narrow_season_drawer_box["y"]
        >= narrow_season_card_box["y"] + narrow_season_card_box["height"] - 2
    )
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )
    page.set_viewport_size(normal_viewport)
    season_button.click()
    playwright_api.expect(season_button).to_have_attribute("aria-expanded", "false")
    playwright_api.expect(season_drawer).to_be_hidden()
    season_button.click()
    playwright_api.expect(season_drawer).to_be_visible()
    first_episode = page.locator(
        "#series-release-panel .episode-row", has_text="Released Browser Episode"
    )
    first_episode.evaluate("element => { element.dataset.testIdentity = 'retained'; }")
    drawer_scroll_before = season_drawer.evaluate("element => element.scrollTop")
    window_scroll_before = page.evaluate("window.scrollY")
    first_episode.get_by_role("button", name="Mark watched").click()
    playwright_api.expect(first_episode.get_by_role("button")).to_have_text("Mark unwatched")
    assert first_episode.get_attribute("data-test-identity") == "retained"
    playwright_api.expect(first_episode).to_have_class(re.compile(r"episode-just-updated"))
    assert season_drawer.evaluate("element => element.scrollTop") == drawer_scroll_before
    assert page.evaluate("window.scrollY") == window_scroll_before
    assert (
        page.request.get(f"{browser_server}/api/entries/{tracked_entry_id}").json()["status"]
        == "watching"
    )
    _close_dialog(page, "#entry-dialog")
    page.locator("#refresh-active-shows").click()
    playwright_api.expect(page.locator("#active-calendar-summary")).to_contain_text(
        "dated episode"
    )
    playwright_api.expect(page.locator("#release-sync-progress")).to_have_attribute(
        "role", "progressbar"
    )
    page.locator("[data-open-calendar-page]").click()
    playwright_api.expect(page.locator("#calendar-view")).to_be_visible()
    playwright_api.expect(page.locator('[data-view="calendar"]')).to_be_visible()
    playwright_api.expect(page.locator("#release-calendar")).to_contain_text(
        "Tracked Browser Series"
    )
    assert page.get_by_role("button", name="Agenda", exact=True).count() == 0
    playwright_api.expect(page.locator("#release-calendar .calendar-month")).to_be_visible()
    calendar_event = page.locator("#release-calendar .calendar-event").first
    calendar_event.hover()
    playwright_api.expect(page.locator("#floating-help-tooltip")).to_be_visible()
    page.locator("#release-calendar h3").hover()
    playwright_api.expect(page.locator("#floating-help-tooltip")).to_be_hidden()
    calendar_event.click()
    playwright_api.expect(page.locator("#calendar-selection")).to_contain_text(
        "Upcoming Browser Episode"
    )
    page.get_by_role("button", name="Active Shows", exact=True).first.click()
    page.locator("#sync-releases").click()
    playwright_api.expect(page.locator("#release-sync-status")).to_contain_text(
        "Last successful"
    )
    page.locator("#open-release-notifications").click()
    playwright_api.expect(page.locator("#notifications-view")).to_be_visible()
    playwright_api.expect(page.locator("#release-notifications")).to_contain_text(
        "No release notifications yet"
    )
    page.get_by_role("button", name="Rankings", exact=True).click()
    playwright_api.expect(page.locator('[data-view="calendar"]')).to_be_hidden()
    playwright_api.expect(page.locator("#rankings-list")).to_contain_text("The Browser Film")
    assert "view=rankings" in page.url
    playwright_api.expect(page.locator("#rankings-mode-control")).to_be_visible()
    browser_ranking = page.locator(".ranking-tile", has_text="The Browser Film")
    playwright_api.expect(browser_ranking).to_contain_text("Your rating")
    playwright_api.expect(browser_ranking).to_contain_text("Technical")
    playwright_api.expect(browser_ranking).to_contain_text("Not refined")
    evidence_box = browser_ranking.locator(".evidence-chip").bounding_box()
    tile_box = browser_ranking.bounding_box()
    assert evidence_box and tile_box
    assert evidence_box["y"] > tile_box["y"] + (tile_box["height"] / 2)
    assert (
        float(
            browser_ranking.locator(".evidence-chip").evaluate(
                "element => Number.parseFloat(getComputedStyle(element).fontSize)"
            )
        )
        < 12
    )
    ranking_poster = browser_ranking.locator(".poster").bounding_box()
    assert ranking_poster and ranking_poster["width"] >= 122
    assert (
        float(
            browser_ranking.locator(".ranking-scores strong").first.evaluate(
                "element => Number.parseFloat(getComputedStyle(element).fontSize)"
            )
        )
        >= 24
    )
    assert browser_ranking.get_by_text("Why this position?").count() == 0
    browser_ranking.locator("h3").click()
    playwright_api.expect(page.locator("#entry-dialog")).to_be_hidden()
    ranking_mode = page.locator("#rankings-technical-mode")
    ranking_mode_control = page.locator("#rankings-mode-control")
    playwright_api.expect(ranking_mode).to_be_checked()
    ranking_mode_control.click()
    playwright_api.expect(ranking_mode).not_to_be_checked()
    personal_ranking = page.locator(".ranking-tile", has_text="The Browser Film")
    playwright_api.expect(personal_ranking.locator(".ranking-scores.personal")).to_be_visible()
    personal_poster = personal_ranking.locator(".poster").bounding_box()
    assert personal_poster and personal_poster["width"] >= 122
    ranking_mode_control.click()
    playwright_api.expect(ranking_mode).to_be_checked()
    browser_ranking = page.locator(".ranking-tile", has_text="The Browser Film")
    playwright_api.expect(browser_ranking).to_contain_text("Technical")
    tech_help = page.locator("#technical-score-help")
    playwright_api.expect(tech_help).to_be_visible()
    tech_help.click()
    technical_dialog = page.locator("#technical-score-dialog")
    playwright_api.expect(technical_dialog).to_contain_text("personal rating")
    playwright_api.expect(technical_dialog).to_contain_text("Rewatches")
    playwright_api.expect(technical_dialog.locator(".equation-visual")).to_contain_text(
        "Technical score"
    )
    technical_dialog.locator("#ranking-calculation-status").click()
    playwright_api.expect(
        technical_dialog.locator("#ranking-calculation-status-note")
    ).to_have_text("Work in progress.")
    _close_dialog(page, "#technical-score-dialog")
    assert page.get_by_text("Help me decide", exact=True).count() == 0
    playwright_api.expect(page.locator("#rankings-help")).to_contain_text("Technical order")
    page.locator("#refine-rankings").click()
    scope_dialog = page.locator("#refinement-scope-dialog")
    playwright_api.expect(scope_dialog).to_be_visible()
    playwright_api.expect(scope_dialog).to_contain_text("Entire rated library")
    assert scope_dialog.locator(".refinement-scope-card").evaluate_all(
        "cards => cards.every(card => card.scrollWidth <= card.clientWidth + 1)"
    )
    scope_dialog.get_by_role("button", name="Small focused portion").click()
    comparison = page.locator("#comparison-dialog")
    playwright_api.expect(comparison).to_be_visible()
    playwright_api.expect(page.locator("#comparison-cards .comparison-card")).to_have_count(2)
    playwright_api.expect(page.locator("#comparison-progress")).to_contain_text("Stage 1 of 2")
    for _ in range(3):
        if page.locator("#assessment-dialog").is_visible():
            break
        try:
            page.locator("#prefer-left").click(timeout=2_000)
        except playwright_api.TimeoutError:
            if page.locator("#assessment-dialog").is_visible():
                break
            raise
        page.wait_for_timeout(120)
    assessment = page.locator("#assessment-dialog")
    playwright_api.expect(assessment).to_be_visible()
    playwright_api.expect(page.locator("#assessment-run-progress")).to_contain_text(
        "Stage 2 of 2"
    )
    assert assessment.locator("input[type='radio']:checked").count() == 0
    core_scores = {
        "impact": "5",
        "distinctiveness": "4",
        "formula_freshness": "4",
        "engagement": "5",
        "coherence": "4",
        "lasting_value": "5",
    }
    for dimension in (
        "impact",
        "distinctiveness",
        "formula_freshness",
        "engagement",
        "coherence",
        "lasting_value",
        "consistency",
        "personal_significance",
        "rewatch_desire",
        "reward_vs_flaws",
    ):
        value = core_scores.get(dimension, "skip")
        choice = assessment.locator(f"input[name='assessment-{dimension}'][value='{value}']")
        playwright_api.expect(choice).to_be_visible()
        choice.check()
        assessment.get_by_role("button", name="Continue", exact=False).click()
    assessment.get_by_role("button", name="Save evidence & continue").click()
    playwright_api.expect(page.locator("#assessment-run-progress")).to_contain_text(
        "Title 2 of"
    )
    _close_dialog(page, "#assessment-dialog")
    page.get_by_role("button", name="Insights").click()
    playwright_api.expect(page.locator("#insights-content")).to_contain_text(
        "Viewing over time"
    )
    playwright_api.expect(page.locator("#summary-cards")).to_contain_text("Titles watched")
    playwright_api.expect(page.locator("#insight-activity-chart")).to_be_visible()
    playwright_api.expect(page.locator(".insight-rating-histogram")).to_be_visible()
    page.locator("[data-insight-period='all']").click()
    page.wait_for_url(re.compile(r"[?&]period=all(?:&|$)"))

    # Add Media is an overlay and must not unexpectedly change the active page.
    page.locator("#quick-add-shortcut").click()
    playwright_api.expect(page.locator("#quick-add-dialog")).to_be_visible()
    playwright_api.expect(page.locator("#insights-view")).to_be_visible()
    _close_dialog(page, "#quick-add-dialog")

    # PMT is the home action and returns to Library without hiding content under the rail.
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.locator(".brand").click()
    page.wait_for_timeout(450)
    assert page.evaluate("window.scrollY") == 0
    playwright_api.expect(page.locator("#library-view")).to_be_visible()
    heading_box = page.locator("#library-heading").bounding_box()
    sidebar_box = page.locator(".app-sidebar").bounding_box()
    assert heading_box and sidebar_box and heading_box["x"] >= sidebar_box["width"]
    assert page.request.get(f"{browser_server}/api/exports/watch-log.csv").ok
    assert page.request.get(f"{browser_server}/api/exports/preference-profile.json").ok
    assert page.request.get(f"{browser_server}/api/exports/preference-profile.md").ok
    assert page.request.get(f"{browser_server}/api/exports/advanced-ratings.json").ok
    page.locator("#open-settings").click()
    settings_dialog = page.locator("#settings-dialog")
    settings_dialog.get_by_role("tab", name="General", exact=True).click()
    settings_box = settings_dialog.bounding_box()
    assert settings_box and settings_box["width"] > 900
    settings_layout = settings_dialog.evaluate(
        """dialog => {
          const tabs = dialog.querySelector('.settings-tabs').getBoundingClientRect();
          const panel = dialog.querySelector('[data-settings-panel="general"]');
          const panelBox = panel.getBoundingClientRect();
          return {
            dialogOverflowX: dialog.scrollWidth - dialog.clientWidth,
            dialogOverflowY: dialog.scrollHeight - dialog.clientHeight,
            panelOverflowY: panel.scrollHeight - panel.clientHeight,
            sidebarBeforePanel: tabs.right < panelBox.left,
          };
        }"""
    )
    assert settings_layout == {
        "dialogOverflowX": 0,
        "dialogOverflowY": 0,
        "panelOverflowY": 0,
        "sidebarBeforePanel": True,
    }
    settings_dialog.get_by_role("tab", name="Metadata", exact=True).click()
    tmdb_help = settings_dialog.get_by_label("TMDb help")
    tmdb_help.hover()
    tooltip = settings_dialog.locator("#floating-help-tooltip")
    playwright_api.expect(tooltip).to_be_visible()
    playwright_api.expect(tooltip).to_contain_text("movie and TV search")
    settings_dialog.locator("#tmdb-status").hover()
    playwright_api.expect(tooltip).to_be_hidden()
    settings_dialog.get_by_role("tab", name="General", exact=True).click()
    timezone_help = settings_dialog.get_by_label("Timezone help")
    timezone_help.hover()
    playwright_api.expect(tooltip).to_be_visible()
    tooltip_box = tooltip.bounding_box()
    viewport = page.viewport_size
    assert tooltip_box and viewport
    assert tooltip_box["x"] >= 0
    assert tooltip_box["x"] + tooltip_box["width"] <= viewport["width"]
    settings_dialog.locator("#general-timezone").hover()
    playwright_api.expect(tooltip).to_be_hidden()
    settings_dialog.locator("#dismiss-settings-intro").click()
    playwright_api.expect(settings_dialog.locator("#settings-intro")).to_be_hidden()
    settings_dialog.locator("#general-timezone").fill("America/Los_Angeles")
    playwright_api.expect(settings_dialog.locator("#general-settings-state")).to_contain_text(
        "Unsaved"
    )
    settings_dialog.locator("#save-general-settings").click()
    playwright_api.expect(settings_dialog.locator("#general-settings-state")).to_contain_text(
        "Effective timezone: America/Los_Angeles"
    )
    settings_dialog.get_by_role("tab", name="General", exact=True).click()
    playwright_api.expect(settings_dialog.locator(".accent-swatch[data-accent]")).to_have_count(
        0
    )
    settings_dialog.locator("#accent-color").evaluate(
        "element => { element.value = '#e1b12c'; element.dispatchEvent(new Event('input', {bubbles:true})); element.dispatchEvent(new Event('change', {bubbles:true})); }"
    )
    playwright_api.expect(page.locator("html")).to_have_attribute("data-custom-accent", "true")
    settings_dialog.locator("#background-color").evaluate(
        "element => { element.value = '#374f7a'; element.dispatchEvent(new Event('input', {bubbles:true})); element.dispatchEvent(new Event('change', {bubbles:true})); }"
    )
    settings_dialog.locator("#background-strength").evaluate(
        "element => { element.value = '82'; element.dispatchEvent(new Event('input', {bubbles:true})); element.dispatchEvent(new Event('change', {bubbles:true})); }"
    )
    settings_dialog.locator("#background-mode").select_option("full")
    playwright_api.expect(page.locator("html")).to_have_attribute(
        "data-background-mode", "full"
    )
    playwright_api.expect(settings_dialog.locator("#background-strength-value")).to_have_text(
        "82%"
    )
    settings_dialog.locator("#media-artwork-tint").check()
    playwright_api.expect(page.locator("html")).to_have_attribute(
        "data-media-artwork-tint", "true"
    )
    playwright_api.expect(settings_dialog.locator("#appearance-state")).to_contain_text(
        "save automatically"
    )
    assert (
        page.request.get(f"{browser_server}/api/settings/general").json()["media_artwork_tint"]
        is True
    )
    settings_dialog.locator("#media-artwork-full-color").check()
    playwright_api.expect(page.locator("html")).to_have_attribute(
        "data-media-artwork-full-color", "true"
    )
    settings_dialog.locator("#show-episode-progress").uncheck()
    playwright_api.expect(
        page.locator("#library .entry-card", has_text="Tracked Browser Series").locator(
            "[data-episode-progress]"
        )
    ).to_have_count(0)
    settings_dialog.locator("#icon-background-color").evaluate(
        "element => { element.value = '#220f33'; element.dispatchEvent(new Event('input', {bubbles:true})); element.dispatchEvent(new Event('change', {bubbles:true})); }"
    )
    settings_dialog.locator("#icon-text-color").evaluate(
        "element => { element.value = '#88ee22'; element.dispatchEvent(new Event('input', {bubbles:true})); element.dispatchEvent(new Event('change', {bubbles:true})); }"
    )
    brand_monogram = page.locator(".brand .brand-monogram")
    playwright_api.expect(brand_monogram).to_have_css("background-color", "rgb(34, 15, 51)")
    playwright_api.expect(brand_monogram).to_have_css("color", "rgb(136, 238, 34)")
    settings_dialog.locator("#icon-follow-accent").check()
    playwright_api.expect(brand_monogram).to_have_css("color", "rgb(225, 177, 44)")
    playwright_api.expect(settings_dialog.locator("#icon-text-color")).to_be_disabled()
    page.wait_for_function(
        """async () => {
          const settings = await fetch('/api/settings/general').then(response => response.json());
          return settings.media_artwork_full_color === true
            && settings.show_episode_progress === false
            && settings.icon_background_color === '#220f33'
            && settings.icon_text_color === '#88ee22'
            && settings.icon_follow_accent === true;
        }"""
    )
    settings = page.request.get(f"{browser_server}/api/settings/general").json()
    assert settings["media_artwork_full_color"] is True
    assert settings["show_episode_progress"] is False
    assert settings["icon_background_color"] == "#220f33"
    assert settings["icon_text_color"] == "#88ee22"
    assert settings["icon_follow_accent"] is True
    assert (
        page.request.get(f"{browser_server}/api/settings/general").json()["accent_color"]
        == "#e1b12c"
    )
    artwork_card = page.locator(".entry-card", has_text="The Browser Film")
    playwright_api.expect(artwork_card).to_have_attribute(
        "data-media-art", "https://images.invalid/browser-poster.jpg"
    )
    assert "browser-poster.jpg" in artwork_card.evaluate(
        "element => getComputedStyle(element, '::before').backgroundImage"
    )
    _close_dialog(page, "#settings-dialog")
    page.locator("#open-settings").click()
    settings_dialog.get_by_role("tab", name="General", exact=True).click()
    playwright_api.expect(page.locator("html")).to_have_attribute("data-custom-accent", "true")
    playwright_api.expect(settings_dialog.locator("#icon-follow-accent")).to_be_checked()
    playwright_api.expect(settings_dialog.locator("#icon-text-color")).to_be_disabled()
    assert settings_dialog.locator("#accent-color").input_value() == "#e1b12c"
    settings_dialog.get_by_role("tab", name="Metadata", exact=True).click()
    playwright_api.expect(settings_dialog.locator(".connection-provider-button")).to_have_count(
        5
    )
    settings_dialog.locator('[data-connection-provider="kitsu"]').click()
    playwright_api.expect(
        settings_dialog.locator('[data-connection-panel="kitsu"]')
    ).to_be_visible()
    playwright_api.expect(
        settings_dialog.locator('[data-connection-panel="kitsu"]')
    ).to_contain_text("Ready · no key")
    integration_viewport = page.viewport_size
    page.set_viewport_size({"width": 760, "height": 700})
    page.wait_for_timeout(220)
    assert settings_dialog.evaluate("element => element.scrollWidth <= element.clientWidth")
    assert settings_dialog.evaluate(
        """dialog => {
          const tabs = dialog.querySelector('.settings-tabs').getBoundingClientRect();
          const panel = dialog.querySelector('[data-settings-panel]:not([hidden])')
            .getBoundingClientRect();
          return tabs.bottom <= panel.top;
        }"""
    )
    page.set_viewport_size(integration_viewport)
    settings_dialog.get_by_role("tab", name="Shortcuts").click()
    playwright_api.expect(settings_dialog.locator("#shortcut-editor")).to_contain_text(
        "Open title search without changing pages"
    )
    playwright_api.expect(
        settings_dialog.locator('[data-shortcut-row="rankings"] kbd')
    ).not_to_have_text("Not set")
    playwright_api.expect(
        settings_dialog.locator('[data-shortcut-row="quick_add"] kbd')
    ).to_have_text("Not set")
    assert (
        page.request.get(f"{browser_server}/api/settings/general").json()["keyboard_shortcuts"][
            "rankings"
        ]
        == "Meta+Alt+KeyR"
    )
    settings_dialog.get_by_role("tab", name="Data & Backup").click()
    playwright_api.expect(
        settings_dialog.get_by_role("link", name="Watch log CSV")
    ).to_be_visible()
    playwright_api.expect(
        settings_dialog.get_by_role("link", name="Profile JSON")
    ).to_be_visible()
    playwright_api.expect(
        settings_dialog.get_by_role("link", name="Profile Markdown")
    ).to_be_visible()
    settings_dialog.locator(".advanced-transfer > summary").click()
    with page.expect_download() as portable_download:
        settings_dialog.get_by_role("link", name="Export everything").click()
    migration_file = portable_download.value.path()
    assert migration_file is not None
    settings_dialog.locator("#migration-file").set_input_files(migration_file)
    settings_dialog.get_by_role("button", name="Inspect migration file").click()
    preview = settings_dialog.locator("#migration-preview")
    playwright_api.expect(preview).to_be_visible()
    playwright_api.expect(preview).to_contain_text("Portable library archive")
    playwright_api.expect(preview.locator("#migration-active-titles")).to_have_text("29")
    playwright_api.expect(preview.locator("#migration-preferences")).to_have_text("Included")
    settings_dialog.get_by_role("button", name="Create backup").click()
    playwright_api.expect(page.locator("#settings-message")).to_contain_text("Backup created")
    page.evaluate("window.__underlyingScroll = window.scrollY")
    settings_dialog.evaluate("element => { element.scrollTop = element.scrollHeight; }")
    settings_dialog.hover(position={"x": 20, "y": 20})
    page.mouse.wheel(0, 1000)
    assert page.evaluate("window.scrollY === window.__underlyingScroll")
    settings_dialog.get_by_role("tab", name="General").click()
    settings_dialog.locator("#interface-language").select_option("fr")
    with page.expect_navigation(wait_until="domcontentloaded"):
        settings_dialog.locator("#save-general-settings").click()
    playwright_api.expect(page.locator("html")).to_have_attribute("lang", "fr")
    playwright_api.expect(page.locator('[data-view="library"]')).to_have_text("Bibliothèque")
    playwright_api.expect(
        page.locator("#library-view .entry-card h3", has_text="History")
    ).to_have_text("History")
    page.locator('[data-view="insights"]').click()
    playwright_api.expect(page.locator("#insights-view")).to_be_visible()
    playwright_api.expect(page.locator("#insights-content")).to_contain_text(
        "Visionnage dans le temps"
    )
    playwright_api.expect(page.locator("#insights-content")).to_contain_text(
        "Votre courbe de notes"
    )
    playwright_api.expect(page.locator("#insights-updated")).to_contain_text("Mis à jour")
    assert page.evaluate("formatDate('2026-08-12')") == "12/08/2026"
    insight_copy = page.locator("#insights-content").inner_text()
    for untranslated in (
        "Recent months",
        "Days of the week",
        "completed but unrated",
        "metadata verified",
        "dated this year",
        "Your busiest period",
        "A well-supported favourite",
        "Ratings can sharpen your profile",
        "Titles you returned to",
        "Distinct library titles with a title or episode viewing",
        "Undated imported counts appear in all-time totals",
    ):
        assert untranslated not in insight_copy
    assert (
        page.request.get(f"{browser_server}/api/settings/general").json()["interface_language"]
        == "fr"
    )
    playwright_api.expect(page.locator("html")).to_have_attribute("lang", "fr")
    page.locator('[data-view="rankings"]').click()
    playwright_api.expect(page.locator("#rankings-view")).to_be_visible()
    page.locator("#refine-rankings").click()
    french_scope = page.locator("#refinement-scope-dialog")
    playwright_api.expect(french_scope).to_contain_text("Affinement avancé du classement")
    playwright_api.expect(french_scope).to_contain_text("Reprendre l’affinement")
    french_scope.get_by_role("button", name="Reprendre l’affinement").click()
    french_assessment = page.locator("#assessment-dialog")
    playwright_api.expect(french_assessment).to_contain_text("Étape 2 sur 2")
    playwright_api.expect(french_assessment).to_contain_text(
        "Quelle a été la force de son impact émotionnel ou intellectuel ?"
    )
    _close_dialog(page, "#assessment-dialog")
    page.locator("#open-settings").click()
    settings_dialog = page.locator("#settings-dialog")
    settings_dialog.locator('[data-settings-tab="data"]').click()
    playwright_api.expect(settings_dialog.locator("#ai-import-prompt")).to_contain_text(
        "Convertis ma liste de médias"
    )
    settings_dialog.locator('[data-settings-tab="general"]').click()
    settings_dialog.locator("#interface-language").select_option("en")
    with page.expect_navigation(wait_until="domcontentloaded"):
        settings_dialog.locator("#save-general-settings").click()
    playwright_api.expect(page.locator("html")).to_have_attribute("lang", "en")
    page.locator("#open-settings").click()
    settings_dialog = page.locator("#settings-dialog")
    settings_dialog.get_by_role("tab", name="Privacy & About").click()
    playwright_api.expect(settings_dialog).to_contain_text(f"Version {__version__}")
    playwright_api.expect(settings_dialog).to_contain_text(
        "This product uses the TMDB API but is not endorsed or certified by TMDB."
    )
    _close_dialog(page, "#settings-dialog")
    page.locator("#open-settings").click()
    playwright_api.expect(page.locator("#settings-intro")).to_be_hidden()
    _close_dialog(page, "#settings-dialog")
    page.keyboard.press("/")
    playwright_api.expect(page.locator("#quick-add-dialog")).to_be_hidden()

    # Soft delete and restore through the recoverable deleted filter.
    page.get_by_role("button", name="Library", exact=True).click()
    page.locator("#page-size").select_option("24")
    page.locator("#library-filters").evaluate("element => element.open = true")
    page.locator("#filter-form").get_by_role("button", name="Clear").click()
    playwright_api.expect(page.locator("#pagination [aria-current='page']")).to_have_text("1")
    playwright_api.expect(page.locator("#library")).to_have_attribute("aria-busy", "false")
    first_card = page.locator(".entry-card").first
    playwright_api.expect(first_card.locator("h3")).to_be_visible()
    assert first_card.locator("h3").evaluate(
        """element => {
            const style = getComputedStyle(element);
            return style.userSelect !== "none" && style.webkitUserSelect !== "none";
        }"""
    )
    deleted_title = first_card.locator("h3").inner_text()
    first_card.locator("[data-details]").click()
    playwright_api.expect(page.locator("#entry-dialog")).to_be_visible()
    page.locator("#entry-dialog .more-actions").evaluate("element => element.open = true")
    page.locator("#delete-entry").click()
    page.locator("#confirm-submit").click()
    page.locator("#library-filters").evaluate("element => element.open = true")
    page.locator("#filter-form [name='include_deleted']").check()
    page.locator("#filter-form").get_by_role("button", name="Apply filters").click()
    deleted_card = page.locator(".entry-card.deleted", has_text=deleted_title)
    playwright_api.expect(deleted_card).to_be_visible()
    deleted_card.locator("[data-details]").click()
    playwright_api.expect(page.locator("#entry-dialog")).to_be_visible()
    page.locator("#entry-dialog .more-actions").evaluate("element => element.open = true")
    playwright_api.expect(page.locator("#restore-entry")).to_be_visible()
    page.locator("#restore-entry").click()
    playwright_api.expect(page.locator(".entry-card", has_text=deleted_title)).to_be_visible()

    # Narrow-window and lightweight equivalent accessibility audit.
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )
    violations = page.evaluate(
        """
        () => {
          const visible = element => Boolean(element.offsetWidth || element.offsetHeight || element.getClientRects().length);
          const issues = [];
          if (!document.documentElement.lang) issues.push('html-language');
          if (document.querySelectorAll('h1').length !== 1) issues.push('single-h1');
          document.querySelectorAll('button').forEach(button => {
            if (visible(button) && !(button.textContent.trim() || button.getAttribute('aria-label') || button.title)) issues.push('unnamed-button');
          });
          document.querySelectorAll('input:not([type=hidden]), select, textarea').forEach(control => {
            if (visible(control) && !control.closest('label') && !control.getAttribute('aria-label') && !control.getAttribute('aria-labelledby')) issues.push(`unlabelled-${control.tagName.toLowerCase()}`);
          });
          document.querySelectorAll('img').forEach(image => { if (!image.hasAttribute('alt')) issues.push('image-without-alt'); });
          document.querySelectorAll('a[href], img[src]').forEach(element => {
            const value = element.getAttribute('href') || element.getAttribute('src') || '';
            if (/^javascript:/i.test(value)) issues.push('dangerous-url');
          });
          return [...new Set(issues)];
        }
        """
    )
    assert violations == []
