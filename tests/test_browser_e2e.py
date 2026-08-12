from __future__ import annotations

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


@pytest.fixture(scope="module")
def browser_server(tmp_path_factory):
    root = tmp_path_factory.mktemp("browser-e2e")
    settings = Settings(
        data_dir=root / "data",
        config_dir=root / "config",
        log_dir=root / "logs",
        backups_dir=root / "backups",
        database_path=root / "watchtracker.sqlite3",
        cache_dir=root / "cache",
        env_path=root / ".env",
        timezone="UTC",
        release_mode=True,
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
        dialog.get_by_role("button", name="Close").click()


def test_complete_private_diary_browser_flow(browser_page, browser_server, tmp_path):
    page = browser_page

    # First-run onboarding can be completed without a provider credential.
    onboarding = page.locator("#onboarding-dialog")
    playwright_api.expect(onboarding).to_be_visible()
    onboarding.get_by_role("button", name="Get started").click()
    onboarding.get_by_role("button", name="Skip for now").click()
    onboarding.get_by_role("button", name="Search for a title").click()
    playwright_api.expect(page.locator("#search-input")).to_be_focused()

    # One-character search, add, and explicit duplicate behavior.
    page.locator("#search-input").fill("B")
    playwright_api.expect(page.locator(".search-result")).to_be_visible()
    page.locator(".search-result").click()
    playwright_api.expect(
        page.locator(".entry-card", has_text="The Browser Film")
    ).to_be_visible()
    page.locator("#quick-add-shortcut").click()
    page.locator("#search-input").fill("B")
    playwright_api.expect(page.locator(".search-result")).to_be_visible()
    page.locator(".search-result").click()
    duplicate = page.locator("#duplicate-actions")
    playwright_api.expect(duplicate).to_contain_text("already in your library")
    duplicate.get_by_role("button", name="Add rewatch today").click()
    playwright_api.expect(page.locator(".entry-card", has_text="2 views")).to_be_visible()

    # Inline edit, full detail tabs, notes-as-text, rating, rewatch, and viewing deletion.
    page.get_by_role("button", name="List layout").click()
    card = page.locator(".entry-card", has_text="The Browser Film")
    rating = card.locator("[data-inline='personal_rating']")
    rating.fill("8.7")
    rating.press("Tab")
    playwright_api.expect(card).to_contain_text("8.7/10")
    card.get_by_role("button", name="Open").click()
    entry_dialog = page.locator("#entry-dialog")
    playwright_api.expect(entry_dialog).to_be_visible()
    entry_dialog.get_by_role("tab", name="Notes & tags").click()
    page.locator("#entry-notes").fill("<img src=x onerror=alert(1)> synthetic note")
    page.locator("#entry-tags").fill("browser, synthetic")
    entry_dialog.get_by_role("tab", name="Metadata").click()
    playwright_api.expect(page.locator("#entry-metadata-state")).to_contain_text("verified")
    entry_dialog.get_by_role("tab", name="Details").click()
    page.locator("#entry-rating").fill("9.1")
    entry_dialog.get_by_role("button", name="Save changes").click()
    playwright_api.expect(card).to_contain_text("9.1/10")
    card.get_by_role("button", name="Open").click()
    page.locator("#add-rewatch").click()
    playwright_api.expect(entry_dialog.get_by_role("tab", name="History")).to_have_attribute(
        "aria-selected", "true"
    )
    history_delete = page.locator("#viewing-history [data-event]").last
    history_delete.click()
    page.locator("#confirm-submit").click()
    playwright_api.expect(page.locator("#viewing-history [data-event]")).to_have_count(2)
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

    import_file = tmp_path / "browser-import.csv"
    import_file.write_text(
        "title,year,media_type,watched_status,user_rating,rewatch_count,external_tmdb_id,notes\n"
        "Imported Browser Film,2021,movie,watched,7.6,0,555001,synthetic import\n",
        encoding="utf-8",
    )
    page.locator("#open-import").click()
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

    # Filters and URL state remain useful and omit personal fields.
    page.locator("#toggle-filters").click()
    page.locator("#filter-form [name='media_type']").select_option("tv")
    page.locator("#filter-form").get_by_role("button", name="Apply filters").click()
    playwright_api.expect(page.locator(".entry-card")).to_have_count(1)
    assert "media_type=tv" in page.url
    assert "note" not in page.url and "rating" not in page.url and "token" not in page.url
    page.locator("#filter-form").get_by_role("button", name="Clear").click()
    playwright_api.expect(page.locator(".entry-card")).to_have_count(3)

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

    # Theme, Insights, exports, backup UI, and keyboard shortcut.
    with page.expect_response(
        lambda response: (
            response.url.endswith("/api/settings/general") and response.request.method == "PUT"
        )
    ):
        page.locator("#theme-toggle").click()
    assert page.locator("html").get_attribute("data-theme") in {"light", "dark"}
    page.get_by_role("button", name="Insights").click()
    playwright_api.expect(page.locator("#insights-content")).to_contain_text(
        "What shapes your taste?"
    )
    page.locator("#taste-dimension").select_option("provider")
    page.locator("#taste-metric").select_option("average_personal_rating")
    playwright_api.expect(page.locator("#taste-chart")).to_contain_text("synthetic fixture")
    page.wait_for_timeout(350)
    explorer_chart = page.locator("#taste-chart").bounding_box()
    explorer_detail = page.locator("#taste-detail").bounding_box()
    assert explorer_chart and explorer_detail
    assert explorer_detail["x"] > explorer_chart["x"]
    rating_panel = page.locator(".insight-pair .viz-panel").first.bounding_box()
    status_panel = page.locator(".insight-pair .viz-panel").last.bounding_box()
    assert rating_panel and status_panel
    assert abs(rating_panel["y"] - status_panel["y"]) < 2
    assert page.locator(".status-foot").is_visible()

    # Add Media is an overlay and must not unexpectedly change the active page.
    page.locator("#quick-add-shortcut").click()
    playwright_api.expect(page.locator("#quick-add-dialog")).to_be_visible()
    playwright_api.expect(page.locator("#insights-view")).to_be_visible()
    _close_dialog(page, "#quick-add-dialog")

    # PMT refresh keeps the current view and returns its heading below the sticky header.
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.locator(".brand").click()
    page.wait_for_timeout(450)
    assert page.evaluate("window.scrollY") == 0
    playwright_api.expect(page.locator("#insights-view")).to_be_visible()
    heading_box = page.locator("#insights-heading").bounding_box()
    header_box = page.locator(".app-header").bounding_box()
    assert heading_box and header_box and heading_box["y"] >= header_box["height"]
    export_button = page.locator(".export-menu > summary")
    export_box = export_button.bounding_box()
    export_icon_box = export_button.locator("svg").bounding_box()
    assert export_box and export_icon_box
    assert (
        abs(
            (export_box["x"] + export_box["width"] / 2)
            - (export_icon_box["x"] + export_icon_box["width"] / 2)
        )
        < 1
    )
    assert (
        abs(
            (export_box["y"] + export_box["height"] / 2)
            - (export_icon_box["y"] + export_icon_box["height"] / 2)
        )
        < 1
    )
    assert page.request.get(f"{browser_server}/api/exports/watch-log.csv").ok
    assert page.request.get(f"{browser_server}/api/exports/preference-profile.json").ok
    assert page.request.get(f"{browser_server}/api/exports/preference-profile.md").ok
    page.locator("#open-settings").click()
    settings_dialog = page.locator("#settings-dialog")
    settings_box = settings_dialog.bounding_box()
    assert settings_box and settings_box["width"] > 900
    timezone_help = settings_dialog.get_by_label("Timezone help")
    timezone_help.hover()
    tooltip = page.locator("#floating-help-tooltip")
    playwright_api.expect(tooltip).to_be_visible()
    tooltip_box = tooltip.bounding_box()
    viewport = page.viewport_size
    assert tooltip_box and viewport
    assert tooltip_box["x"] >= 0
    assert tooltip_box["x"] + tooltip_box["width"] <= viewport["width"]
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
    settings_dialog.get_by_role("tab", name="Appearance").click()
    settings_dialog.locator('[data-accent="violet"]').click()
    playwright_api.expect(page.locator("html")).to_have_attribute("data-accent", "violet")
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
        "saved automatically"
    )
    assert (
        page.request.get(f"{browser_server}/api/settings/general").json()["media_artwork_tint"]
        is True
    )
    artwork_card = page.locator(".entry-card", has_text="The Browser Film")
    playwright_api.expect(artwork_card).to_have_attribute(
        "data-media-art", "https://images.invalid/browser-poster.jpg"
    )
    settings_dialog.get_by_role("tab", name="Shortcuts").click()
    playwright_api.expect(settings_dialog.locator(".shortcut-list")).to_contain_text(
        "Open Add Media without leaving your current page"
    )
    settings_dialog.get_by_role("tab", name="Data & Backup").click()
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
    playwright_api.expect(preview.locator("#migration-active-titles")).to_have_text("28")
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
    settings_dialog.locator("#save-general-settings").click()
    playwright_api.expect(page.locator("html")).to_have_attribute("lang", "fr")
    playwright_api.expect(page.locator('[data-view="library"]')).to_have_text("Bibliothèque")
    playwright_api.expect(page.locator(".entry-card h3", has_text="History")).to_have_text(
        "History"
    )
    playwright_api.expect(page.locator("#settings-message")).to_contain_text(
        "Paramètres généraux enregistrés et vérifiés."
    )
    playwright_api.expect(page.locator("#insights-content")).to_contain_text("Mois récents")
    playwright_api.expect(page.locator("#insights-content")).to_contain_text(
        "Jours de la semaine"
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
    ):
        assert untranslated not in insight_copy
    assert (
        page.request.get(f"{browser_server}/api/settings/general").json()["interface_language"]
        == "fr"
    )
    playwright_api.expect(page.locator("html")).to_have_attribute("lang", "fr")
    settings_dialog.locator("#interface-language").select_option("en")
    settings_dialog.locator("#save-general-settings").click()
    playwright_api.expect(page.locator("html")).to_have_attribute("lang", "en")
    playwright_api.expect(page.locator("#settings-message")).to_contain_text(
        "General settings saved and verified."
    )
    settings_dialog.get_by_role("tab", name="About").click()
    playwright_api.expect(settings_dialog).to_contain_text(f"Version {__version__}")
    playwright_api.expect(settings_dialog).to_contain_text(
        "This product uses the TMDB API but is not endorsed or certified by TMDB."
    )
    _close_dialog(page, "#settings-dialog")
    page.locator("#open-settings").click()
    playwright_api.expect(page.locator("#settings-intro")).to_be_hidden()
    _close_dialog(page, "#settings-dialog")
    page.keyboard.press("/")
    playwright_api.expect(page.locator("#search-input")).to_be_focused()
    _close_dialog(page, "#quick-add-dialog")

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
    first_card.get_by_role("button", name="Open").click()
    page.locator("#entry-dialog .more-actions").evaluate("element => element.open = true")
    page.locator("#delete-entry").click()
    page.locator("#confirm-submit").click()
    page.locator("#library-filters").evaluate("element => element.open = true")
    page.locator("#filter-form [name='include_deleted']").check()
    page.locator("#filter-form").get_by_role("button", name="Apply filters").click()
    deleted_card = page.locator(".entry-card.deleted", has_text=deleted_title)
    playwright_api.expect(deleted_card).to_be_visible()
    deleted_card.get_by_role("button", name="Open").click()
    page.locator("#entry-dialog .more-actions").evaluate("element => element.open = true")
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
