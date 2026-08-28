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
        "tvmaze_enabled": True,
        "tvmaze_requires_key": False,
        "wikidata_enabled": True,
        "wikidata_requires_key": False,
        "anilist_enabled": False,
        "anilist_requires_key": False,
        "jikan_requires_key": False,
        "saved_locally": True,
        "storage": "none",
        "legacy_token_available": False,
        "preferred_storage": "local_secret_file",
        "keychain_available": True,
        "credential_scope": "local",
        "individual_token_configured": False,
        "server_token_available": False,
        "use_server_token": False,
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
        client.put(
            "/api/settings/general", json={"icon_background_color": "111010"}
        ).status_code
        == 422
    )
    assert (
        client.put("/api/settings/general", json={"icon_text_color": "#24cd0z"}).status_code
        == 422
    )
    assert (
        client.put("/api/settings/general", json={"background_strength": 101}).status_code
        == 422
    )
    assert (
        client.put("/api/settings/general", json={"sidebar_mode": "hidden"}).status_code == 422
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
            "media_artwork_full_color": True,
            "show_episode_progress": False,
            "icon_background_color": "#220f33",
            "icon_text_color": "#88ee22",
            "icon_follow_accent": True,
            "interface_language": "fr",
            "release_check_mode": "manual",
            "sidebar_mode": "minimized",
            "navigation_order": "reversed",
            "settings_privacy_reminder_dismissed": True,
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
    assert current["media_artwork_full_color"] is True
    assert current["show_episode_progress"] is False
    assert current["icon_background_color"] == "#220f33"
    assert current["icon_text_color"] == "#88ee22"
    assert current["icon_follow_accent"] is True
    assert current["interface_language"] == "fr"
    assert current["release_check_mode"] == "manual"
    assert current["sidebar_mode"] == "minimized"
    assert current["navigation_order"] == "reversed"
    assert current["settings_privacy_reminder_dismissed"] is True
    assert current["keyboard_shortcuts"] == {"library": "Meta+Alt+KeyL"}

    chinese = client.put("/api/settings/general", json={"interface_language": "zh-CN"})
    assert chinese.status_code == 200
    assert client.get("/api/settings/general").json()["interface_language"] == "zh-CN"

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


def test_macos_desktop_titlebar_has_a_safe_drag_region(client):
    html = client.get("/").text
    css = client.get("/static/styles.css").text
    assert 'class="pywebview-drag-region native-titlebar-drag-main"' in html
    assert 'class="pywebview-drag-region native-titlebar-drag-under-controls"' in html
    assert ".native-titlebar-drag-main { top: 0; right: 0; left: 76px; height: 38px; }" in css
    assert (
        ".native-titlebar-drag-under-controls { top: 28px; left: 0; width: 76px; height: 10px; }"
        in css
    )


def test_settings_dialog_and_favicon_are_available(client):
    html = client.get("/").text
    javascript = client.get("/static/app.js").text
    css = client.get("/static/styles.css").text
    assert 'id="open-settings"' in html
    assert 'class="icon-button quiet sidebar-server" id="server-console-nav"' in html
    assert "Personal Tailscale access" in html
    assert 'id="tailscale-private-connection-section"' in html
    assert "Tailscale private connection setup" in html
    assert 'id="pmt-server-mode-section"' in html
    assert "Connect this application to PMT Server" in html
    assert 'id="personal-tailscale-toggle"' in html
    assert 'id="server-mode-toggle"' in html
    assert '$("#open-account").hidden = !active' not in javascript
    access_panel = html.split('data-settings-panel="access"', 1)[1].split(
        'data-settings-panel="shortcuts"', 1
    )[0]
    assert 'id="active-server-actions"' not in access_panel
    assert 'id="server-enrollment-dialog"' in html
    assert 'id="return-local-only"' not in html
    assert 'id="native-owner-recovery"' not in html
    assert 'id="authenticated-host-recovery-form"' not in html
    assert 'id="tmdb-token"' in html
    assert 'id="export-everything"' in html
    assert 'id="migration-inspect-form"' in html
    assert 'id="migration-preview"' in html
    assert 'id="ai-import-prompt"' in html
    assert 'id="background-color"' in html
    assert 'id="background-strength"' in html
    assert 'id="background-mode"' in html
    assert 'id="media-artwork-tint"' in html
    assert 'id="media-artwork-full-color"' in html
    assert 'id="icon-background-color"' in html
    assert 'id="icon-text-color"' in html
    assert 'id="icon-follow-accent"' in html
    assert 'id="reset-icon-colors"' in html
    assert 'id="accent-color"' in html
    assert 'id="interface-language"' in html
    assert '<option value="zh-CN">简体中文（测试版）</option>' in html
    assert "/api/exports/obsidian-vault.zip" in html
    assert 'name="credential_storage"' in html
    assert "Operating-system credential vault" in html
    assert "No operating-system password prompt" in html
    assert "macOS" not in html
    assert 'data-settings-panel="shortcuts"' in html
    assert ">Metadata</button>" in html
    assert 'data-settings-panel="integrations"' in html
    assert 'id="integration-provider-catalog"' in html
    assert 'id="integration-reachability"' in html
    assert 'id="download-update"' in html
    assert 'id="update-progress"' in html
    assert "/api/integrations/catalog" in javascript
    assert "/api/updates/download" in javascript
    assert "insight-date-free-toggle" in javascript
    assert "release_year_from" in javascript
    assert "Download in App" in html
    assert "Personal Media Tracker" in html
    assert "Personal Watch Tracker home" not in html
    assert "/api/data/portable/inspect" in javascript
    assert "/api/data/portable/import" in javascript
    assert "state.nativeWindow" in javascript
    assert "The desktop save dialog is not ready" in javascript
    assert "Changing your account password" in javascript
    assert '$("#account-message")' in javascript
    assert "Kitsu" in html and "no account or API key required" in html
    assert 'data-connection-provider="anilist"' not in html
    assert 'id="show-episode-progress"' in html
    assert 'id="open-notifications"' in html
    assert 'id="release-notifications"' in html
    assert 'id="collaboration-notification-section"' in html
    assert '$("#open-notifications").hidden = false' in javascript
    assert (
        "Unavailable"
        not in client.get("/")
        .text.split('data-settings-panel="metadata"', 1)[1]
        .split('data-settings-panel="data"', 1)[0]
    )
    assert 'id="general-settings-state"' in html
    assert 'data-accent="ocean"' not in html
    assert html.count('id="accent-color"') == 1
    assert 'class="media-artwork-pair"' in html
    assert 'class="appearance-color-pair"' in html
    assert 'id="background-image-file"' in html
    assert 'id="insights-filter-form"' in html
    favicon = client.get("/static/favicon.svg")
    assert favicon.status_code == 200
    assert "<svg" in favicon.text
    assert "#111010" in favicon.text
    assert "#24cd09" in favicon.text
    assert 'data-media-artwork-full-color="true"' in css
    assert "min-width: 1.48rem" in css
    assert "font-weight: 950" in css
    assert "flex-direction: column; align-items: center; align-self: center" in css
    french_locale = client.get("/static/locales/fr.js")
    assert french_locale.status_code == 200
    assert "window.PMT_LOCALES.fr" in french_locale.text
    assert '"Integrations": "Intégrations"' in french_locale.text
    assert '"Download in App": "Télécharger dans l’app"' in french_locale.text
    chinese_locale = client.get("/static/locales/zh-CN.js")
    assert chinese_locale.status_code == 200
    assert 'window.PMT_LOCALES["zh-CN"]' in chinese_locale.text
    assert '"Integrations": "集成"' in chinese_locale.text
    assert '"Download in App": "在应用内下载"' in chinese_locale.text
    integrations = client.get("/api/integrations/catalog")
    assert integrations.status_code == 200
    available = {
        provider["slug"]
        for provider in integrations.json()["providers"]
        if provider["available"]
    }
    assert {"jellyfin", "trakt", "kitsu", "simkl", "myanimelist", "plex", "emby"} <= available
    assert "anilist" not in available
    assert {"jellyfin", "trakt", "anilist", "simkl", "myanimelist"} <= {
        provider["slug"] for provider in integrations.json()["providers"]
    }
