from __future__ import annotations

import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from watchtracker.app import create_app
from watchtracker.config import Settings
from watchtracker.launcher import ServerController
from watchtracker.services.secrets import SecretStore

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "screenshots"

DEMO_ENTRIES = [
    ("The Glass Harbor", 2025, "movie", "watched", 9.2, 3, ["Drama", "Mystery"]),
    ("Orbit of Winter", 2023, "tv", "watched", 8.8, 1, ["Science Fiction", "Drama"]),
    ("Paper Moons", 2021, "anime", "watched", 8.5, 2, ["Animation", "Fantasy"]),
    ("A Map of Quiet Places", 2024, "movie", "watched", 8.1, 1, ["Drama"]),
    ("Signal at Dusk", 2022, "tv", "watching", None, 0, ["Mystery", "Thriller"]),
    ("Lantern City", 2020, "anime", "watched", 7.9, 1, ["Animation", "Adventure"]),
    ("The Long Sunday", 2019, "movie", "watched", 7.6, 1, ["Comedy", "Drama"]),
    ("Copper & Snow", 2025, "tv", "plan_to_watch", None, 0, ["Crime", "Drama"]),
    ("After the Comet", 2018, "movie", "watched", 8.9, 2, ["Science Fiction"]),
    ("Small Hours", 2024, "tv", "dropped", 5.8, 0, ["Comedy"]),
    ("Threads of Summer", 2022, "anime", "watched", 8.3, 1, ["Animation", "Romance"]),
    ("Northbound", 2017, "movie", "watched", 7.8, 1, ["Adventure", "Drama"]),
]


class ScreenshotKeyring:
    value = None

    def get_password(self, _service_name, _username):
        return self.value

    def set_password(self, _service_name, _username, password):
        self.value = password

    def delete_password(self, _service_name, _username):
        self.value = None


def _seed(page, base_url: str) -> None:
    response = page.request.put(
        f"{base_url}/api/settings/general", data={"onboarding_complete": True}
    )
    if not response.ok:
        raise RuntimeError(response.text())
    for index, (title, year, media_type, status, rating, views, genres) in enumerate(
        DEMO_ENTRIES, start=1
    ):
        response = page.request.post(
            f"{base_url}/api/entries/manual",
            data={
                "canonical_title": title,
                "release_year": year,
                "media_type": media_type,
                "status": status,
                "personal_rating": rating,
                "view_count": views,
                "provider_source": "tmdb_movie" if media_type == "movie" else "tmdb_tv",
                "provider_id": f"synthetic-{index}",
                "tmdb_movie_id": f"synthetic-{index}" if media_type == "movie" else None,
                "tmdb_tv_id": f"synthetic-{index}" if media_type == "tv" else None,
                "mal_id": f"synthetic-{index}" if media_type == "anime" else None,
                "provider_genres": genres,
                "keywords": ["synthetic demo"],
                "notes": "Synthetic demonstration data only.",
                "user_tags": ["demo"],
            },
        )
        if not response.ok:
            raise RuntimeError(response.text())


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="watchtracker-screenshots-") as temporary:
        runtime = Path(temporary)
        settings = Settings(
            data_dir=runtime / "data",
            config_dir=runtime / "config",
            log_dir=runtime / "logs",
            backups_dir=runtime / "backups",
            database_path=runtime / "watchtracker.sqlite3",
            cache_dir=runtime / "cache",
            env_path=runtime / ".env",
            timezone="UTC",
            release_mode=True,
        )
        controller = ServerController(
            create_app(
                settings,
                secret_store=SecretStore(settings, keyring_backend=ScreenshotKeyring()),
            ),
            "127.0.0.1",
            0,
        )
        controller.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(
                    viewport={"width": 1440, "height": 1000}, reduced_motion="reduce"
                )
                _seed(page, controller.url)
                page.goto(controller.url)
                page.locator("#library").wait_for(state="visible")
                page.wait_for_timeout(500)
                page.screenshot(path=OUTPUT / "library-grid.png", full_page=True)

                page.locator(".entry-card").first.get_by_role("button", name="Open").click()
                page.locator("#entry-dialog").wait_for(state="visible")
                page.wait_for_timeout(250)
                page.screenshot(path=OUTPUT / "entry-detail.png")
                page.locator("#entry-dialog").get_by_role("button", name="Close").click()
                page.locator("#entry-dialog").wait_for(state="hidden")

                page.get_by_role("button", name="Insights", exact=True).click()
                page.locator("#insights-content").get_by_text(
                    "What shapes your taste?"
                ).wait_for()
                page.wait_for_timeout(500)
                page.screenshot(path=OUTPUT / "insights.png", full_page=True)

                page.locator("#open-settings").click()
                settings_dialog = page.locator("#settings-dialog")
                settings_dialog.get_by_role("tab", name="Appearance").click()
                page.locator("#background-color").evaluate(
                    "element => { element.value = '#526f82'; "
                    "element.dispatchEvent(new Event('input', {bubbles: true})); "
                    "element.dispatchEvent(new Event('change', {bubbles: true})); }"
                )
                page.wait_for_timeout(500)
                settings_dialog.screenshot(path=OUTPUT / "appearance-settings.png")
                settings_dialog.get_by_role("tab", name="Data & Backup").click()
                page.wait_for_timeout(250)
                settings_dialog.screenshot(path=OUTPUT / "data-backup-settings.png")
                settings_dialog.get_by_role("button", name="Close").click()

                page.get_by_role("button", name="Library", exact=True).click()
                page.locator("#theme-toggle").click()
                page.wait_for_timeout(500)
                page.screenshot(path=OUTPUT / "dark-mode.png", full_page=True)
                browser.close()
        finally:
            controller.stop()
    print(f"Wrote synthetic screenshots to {OUTPUT}")


if __name__ == "__main__":
    main()
