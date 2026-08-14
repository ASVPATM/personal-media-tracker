from __future__ import annotations

import stat

from watchtracker.app import create_app
from watchtracker.services.preferences import PreferenceStore
from watchtracker.services.secrets import SecretStore
from watchtracker.services.settings import persist_env_value


def test_metadata_token_can_be_saved_activated_and_cleared_without_being_returned(
    client, app, settings
):
    status = client.get("/api/settings/metadata")
    assert status.status_code == 200
    assert status.json() == {
        "tmdb_configured": False,
        "anilist_enabled": False,
        "anilist_requires_key": False,
        "jikan_requires_key": False,
        "saved_locally": True,
        "storage": "none",
        "legacy_token_available": False,
        "preferred_storage": "local_secret_file",
        "keychain_available": True,
    }

    token = "tmdb-read-access-token-" + "x" * 32
    saved = client.put("/api/settings/metadata", json={"tmdb_token": token})
    assert saved.status_code == 200
    assert saved.json()["tmdb_configured"] is True
    assert saved.json()["storage"] == "local_secret_file"
    assert token not in saved.text
    assert app.state.secrets.get() == (token, "local_secret_file")
    assert settings.fallback_secret_path.exists()
    assert app.state.metadata.configured_token == token

    current = client.get("/api/settings/metadata")
    assert current.json()["tmdb_configured"] is True
    assert token not in current.text

    cleared = client.put("/api/settings/metadata", json={"clear_tmdb_token": True})
    assert cleared.status_code == 200
    assert cleared.json()["tmdb_configured"] is False
    assert app.state.secrets.get() == (None, "none")
    assert app.state.metadata.configured_token is None


def test_metadata_token_falls_back_to_owner_only_file(settings):
    class UnavailableKeyring:
        def get_password(self, *_args):
            raise RuntimeError("unavailable")

        def set_password(self, *_args):
            raise RuntimeError("unavailable")

        def delete_password(self, *_args):
            raise RuntimeError("unavailable")

    store = SecretStore(settings, keyring_backend=UnavailableKeyring())
    token = "fallback-token-" + "f" * 32
    assert store.save(token) == "local_secret_file"
    assert store.get() == (token, "local_secret_file")
    assert settings.fallback_secret_path.read_text() == f"WATCHTRACKER_TMDB_TOKEN={token}\n"
    assert stat.S_IMODE(settings.fallback_secret_path.stat().st_mode) == 0o600
    assert store.clear() == "none"
    assert "WATCHTRACKER_TMDB_TOKEN" not in settings.fallback_secret_path.read_text()


def test_keychain_storage_requires_an_explicit_api_choice(client, app, settings):
    token = "explicit-keychain-token-" + "k" * 32
    saved = client.put(
        "/api/settings/metadata",
        json={"tmdb_token": token, "credential_storage": "keychain"},
    )
    assert saved.status_code == 200
    assert saved.json()["storage"] == "keychain"
    assert saved.json()["preferred_storage"] == "keychain"
    assert app.state.secrets.keyring.value == token
    assert PreferenceStore(settings).load()["credential_vault_opt_in"] is True
    assert "WATCHTRACKER_TMDB_TOKEN" not in settings.fallback_secret_path.read_text()
    cleared = client.put("/api/settings/metadata", json={"clear_tmdb_token": True})
    assert cleared.status_code == 200
    assert cleared.json()["preferred_storage"] == "local_secret_file"
    assert PreferenceStore(settings).load()["credential_vault_opt_in"] is False


def test_legacy_keychain_preference_cannot_prompt_during_startup(settings, app, monkeypatch):
    calls = []

    class PromptingKeyring:
        priority = 1

        def get_password(self, *_args):
            calls.append("get")
            raise AssertionError("the system vault must not be queried without fresh opt-in")

    PreferenceStore(settings).update(credential_storage="keychain")
    monkeypatch.setattr(
        "watchtracker.services.secrets._system_keyring", lambda: PromptingKeyring()
    )
    fresh_app = create_app(settings, metadata_service=app.state.metadata, migrate=False)
    assert fresh_app.state.secrets.keyring_enabled is False
    assert calls == []


def test_metadata_token_validation(client):
    assert client.put("/api/settings/metadata", json={}).status_code == 422
    assert client.put("/api/settings/metadata", json={"tmdb_token": "short"}).status_code == 422
    assert (
        client.put(
            "/api/settings/metadata", json={"tmdb_token": "x" * 30 + "\nsecret"}
        ).status_code
        == 422
    )


def test_api_responses_disable_webview_caching(client):
    response = client.get("/api/entries")
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["expires"] == "0"


def test_general_settings_validate_timezone_and_appearance(client):
    invalid_timezone = client.put("/api/settings/general", json={"timezone": "Not/A_Timezone"})
    assert invalid_timezone.status_code == 422
    assert client.put("/api/settings/general", json={"accent": "neon"}).status_code == 422
    assert (
        client.put(
            "/api/settings/general", json={"background_color": "not-a-color"}
        ).status_code
        == 422
    )
    assert (
        client.put("/api/settings/general", json={"background_strength": 101}).status_code
        == 422
    )
    assert (
        client.put(
            "/api/settings/general",
            json={"keyboard_shortcuts": {"library": "Meta+KeyL", "rankings": "Meta+KeyL"}},
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/api/settings/general",
            json={"keyboard_shortcuts": {"unknown_action": "Meta+KeyU"}},
        ).status_code
        == 422
    )

    saved = client.put(
        "/api/settings/general",
        json={
            "timezone": "America/Los_Angeles",
            "accent": "ocean",
            "accent_color": "#d4a017",
            "background_color": "#123abc",
            "background_strength": 72,
            "background_mode": "full",
            "media_artwork_tint": True,
            "interface_language": "fr",
            "release_check_mode": "manual",
            "keyboard_shortcuts": {"library": "Meta+Alt+KeyL"},
        },
    )
    assert saved.status_code == 200
    current = client.get("/api/settings/general").json()
    assert current["timezone"] == "America/Los_Angeles"
    assert current["effective_timezone"] == "America/Los_Angeles"
    assert current["accent"] == "ocean"
    assert current["accent_color"] == "#d4a017"
    assert current["background_color"] == "#123abc"
    assert current["background_strength"] == 72
    assert current["background_mode"] == "full"
    assert current["media_artwork_tint"] is True
    assert current["interface_language"] == "fr"
    assert current["release_check_mode"] == "manual"
    assert current["keyboard_shortcuts"] == {"library": "Meta+Alt+KeyL"}

    automatic = client.put("/api/settings/general", json={"release_check_mode": "automatic"})
    assert automatic.status_code == 200
    assert client.get("/api/releases/sync").json()["scheduler_running"] is True
    client.put("/api/settings/general", json={"release_check_mode": "manual"})
    assert client.get("/api/releases/sync").json()["scheduler_running"] is False


def test_env_update_preserves_unrelated_settings_and_replaces_duplicates(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "WATCHTRACKER_LANGUAGE=sv-SE\nWATCHTRACKER_TMDB_TOKEN=old\n"
        "WATCHTRACKER_TMDB_TOKEN=duplicate\n"
    )
    persist_env_value(path, "WATCHTRACKER_TMDB_TOKEN", "new-token")
    assert path.read_text() == (
        "WATCHTRACKER_LANGUAGE=sv-SE\nWATCHTRACKER_TMDB_TOKEN=new-token\n"
    )


def test_import_commit_ui_requires_a_successful_preview(client):
    html = client.get("/").text
    css = client.get("/static/styles.css").text
    javascript = client.get("/static/app.js").text
    assert '<form id="commit-form" class="form-grid" hidden>' in html
    assert "[hidden] { display: none !important; }" in css
    assert "if (!previewId)" in javascript
    assert "Preview a file successfully before committing it." in javascript
    assert "encodeURIComponent(previewId)" in javascript


def test_settings_dialog_and_favicon_are_available(client):
    html = client.get("/").text
    javascript = client.get("/static/app.js").text
    assert 'id="open-settings"' in html
    assert 'id="tmdb-token"' in html
    assert 'id="export-everything"' in html
    assert 'id="migration-inspect-form"' in html
    assert 'id="migration-preview"' in html
    assert 'id="ai-import-prompt"' in html
    assert 'id="background-color"' in html
    assert 'id="background-strength"' in html
    assert 'id="background-mode"' in html
    assert 'id="media-artwork-tint"' in html
    assert 'id="accent-color"' in html
    assert 'id="interface-language"' in html
    assert 'name="credential_storage"' in html
    assert "Operating-system credential vault" in html
    assert "No operating-system password prompt" in html
    assert "macOS" not in html
    assert 'data-settings-panel="shortcuts"' in html
    assert "Personal Media Tracker" in html
    assert "Personal Watch Tracker home" not in html
    assert "/api/data/portable/inspect" in javascript
    assert "/api/data/portable/import" in javascript
    assert "AniList" in html and "no key required" in html
    assert 'id="anilist-status"' in html
    assert 'id="general-settings-state"' in html
    assert 'data-accent="ocean"' in html
    favicon = client.get("/static/favicon.svg")
    assert favicon.status_code == 200
    assert "<svg" in favicon.text
