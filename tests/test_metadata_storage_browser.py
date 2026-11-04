"""Configured local credentials must not offer a misleading Keychain copy action."""

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")
from test_browser_e2e import browser_server as browser_server  # noqa: E402, F401
from test_collections_browser import page as page  # noqa: E402, F401


@pytest.mark.parametrize("page", ["chromium", "webkit"], indirect=True)
@pytest.mark.parametrize("storage", ["local_secret_file", "environment", "none", "keychain"])
def test_active_credential_storage_is_not_confused_with_vault_migration(page, storage):
    page.route(
        "**/api/settings/metadata",
        lambda route: route.fulfill(
            json={
                "tmdb_configured": storage != "none",
                "storage": storage,
                "keychain_available": True,
                "preferred_storage": "local_secret_file",
                "credential_scope": "local",
                "legacy_token_available": False,
                "server_token_available": False,
                "use_server_token": False,
            }
        ),
    )
    page.locator("#open-settings").click()
    page.locator('[data-settings-tab="screen"]').click()
    page.locator('[data-screen-settings-tab="metadata"]').click()
    button = page.locator("#copy-keychain-token")
    expect = playwright_api.expect
    if storage in {"none", "keychain"}:
        expect(button).to_be_visible()
        expect(page.locator("#tmdb-copy-help")).to_be_hidden()
    else:
        expect(button).to_be_hidden()
        expect(page.locator("#tmdb-copy-help")).to_be_visible()
    expect(
        page.locator('#metadata-api-links a[href="https://www.themoviedb.org/settings/api"]')
    ).to_be_visible()
    expect(
        page.locator('#metadata-api-links a[href="https://openlibrary.org/developers/api"]')
    ).to_be_visible()
