from __future__ import annotations

import io
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from watchtracker.app import create_app
from watchtracker.config import Settings
from watchtracker.icons import DEFAULT_ICON_BACKGROUND, DEFAULT_ICON_TEXT, render_icon
from watchtracker.launcher import (
    DesktopBridge,
    LauncherError,
    ServerController,
    SingleInstance,
    _remote_server_url,
    _run_webview,
    _saved_server_window_url,
    activate_existing_instance,
    bind_server_socket,
    configure_macos_close_button,
    desktop_window_background,
    desktop_window_dimension,
    macos_prefers_dark_appearance,
    main,
    prepare_macos_application_lifecycle,
    regular_desktop_settings,
    reopen_existing_instance,
    set_macos_application_icon,
    socket_port,
    style_macos_titlebar,
    wait_for_health,
)
from watchtracker.runtime import platform_runtime_paths

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_release_workflow_marks_only_server_artifacts_beta_and_pins_version():
    workflow = (PROJECT_ROOT / ".github/workflows/release.yml").read_text()
    compose = (PROJECT_ROOT / "compose.yaml").read_text()
    notes = (PROJECT_ROOT / "RELEASE_NOTES.md").read_text()
    assert "Verify release tag matches application version" in workflow
    assert "PMT-Server-Setup-Beta-${GITHUB_REF_NAME}.zip" in workflow
    assert "Install PMT Server Beta.command" in workflow
    assert "personal-media-tracker-server:${{ github.ref_name }}-beta" in workflow
    assert "personal-media-tracker-server:beta" in workflow
    assert "personal-media-tracker-server:latest" not in workflow
    assert "${PMT_VERSION:-beta}" in compose
    assert "recommended desktop release" in notes
    assert "PMT Server Beta" in notes


def test_regular_packaged_desktop_ignores_legacy_server_mode(settings):
    legacy = settings.model_copy(
        update={
            "release_mode": True,
            "access_mode": "server",
            "public_base_url": "https://legacy.example",
            "application_secret": "x" * 80,
            "trusted_hosts": "legacy.example",
            "trusted_proxy_ips": "127.0.0.1",
        }
    )

    regular = regular_desktop_settings(legacy, command="run")

    assert regular.access_mode == "local"
    assert regular.host == "127.0.0.1"
    assert regular.public_base_url is None
    assert regular.application_secret is None
    with pytest.raises(LauncherError, match="separate PMT Server Setup Beta"):
        regular_desktop_settings(legacy, command="server")


def test_desktop_window_chrome_matches_saved_background():
    assert desktop_window_background({"theme": "light"}) == "#f4f2ed"
    assert desktop_window_background({"theme": "dark"}) == "#151918"
    assert desktop_window_background({"theme": "system"}, system_dark=True) == "#151918"
    assert (
        desktop_window_background(
            {"theme": "dark", "background_mode": "full", "background_color": "#345b67"}
        )
        == "#345b67"
    )
    assert (
        desktop_window_background(
            {
                "theme": "light",
                "background_mode": "adaptive",
                "background_color": "#345b67",
                "background_strength": 25,
            }
        )
        == "#c4cccc"
    )
    assert (
        desktop_window_background(
            {
                "theme": "dark",
                "background_mode": "adaptive",
                "background_color": "#345b67",
                "background_strength": 50,
            }
        )
        == "#253a40"
    )


def test_generated_icon_uses_black_green_defaults_and_transparent_corners():
    icon = render_icon(256)
    colors = icon.getcolors(maxcolors=256 * 256)

    assert icon.getpixel((0, 0)) == (0, 0, 0, 0)
    assert (17, 16, 16, 255) in {color for _count, color in colors}
    assert (36, 205, 9, 255) in {color for _count, color in colors}
    assert DEFAULT_ICON_BACKGROUND == "#111010"
    assert DEFAULT_ICON_TEXT == "#24cd09"


def test_macos_application_icon_is_built_in_memory_and_applied():
    calls: dict[str, object] = {}

    class Data:
        @staticmethod
        def dataWithBytes_length_(payload, length):
            calls["payload"] = payload
            calls["length"] = length
            return payload

    class ImageBuilder:
        @classmethod
        def alloc(cls):
            return cls()

        def initWithData_(self, data):
            calls["image-data"] = data
            return "runtime-icon"

    application = SimpleNamespace(setApplicationIconImage_=lambda icon: calls.update(icon=icon))
    appkit = SimpleNamespace(
        NSImage=ImageBuilder,
        NSApplication=SimpleNamespace(sharedApplication=lambda: application),
    )
    foundation = SimpleNamespace(NSData=Data)

    assert set_macos_application_icon(
        "#111010", "#24cd09", appkit=appkit, foundation=foundation
    )
    assert calls["length"] == len(calls["payload"])
    assert bytes(calls["payload"]).startswith(b"\x89PNG")
    assert calls["icon"] == "runtime-icon"
    assert not set_macos_application_icon(
        "black", "#24cd09", appkit=appkit, foundation=foundation
    )


def test_macos_system_appearance_can_select_dark_startup_color():
    appearance = SimpleNamespace(bestMatchFromAppearancesWithNames_=lambda _names: "dark-aqua")
    appkit = SimpleNamespace(
        NSApplication=SimpleNamespace(
            sharedApplication=lambda: SimpleNamespace(effectiveAppearance=lambda: appearance)
        ),
        NSAppearanceNameAqua="aqua",
        NSAppearanceNameDarkAqua="dark-aqua",
    )
    assert macos_prefers_dark_appearance(appkit=appkit)


def test_macos_close_button_hides_window_and_dock_reopens_it():
    calls: dict[str, object] = {}
    close_button = SimpleNamespace(
        setTarget_=lambda value: calls.__setitem__("target", value),
        setAction_=lambda value: calls.__setitem__("action", value),
    )
    native_window = SimpleNamespace(
        standardWindowButton_=lambda _kind: close_button,
    )
    appkit = SimpleNamespace(NSWindowCloseButton="close")
    assert configure_macos_close_button(native_window, appkit=appkit)
    assert calls == {"target": native_window, "action": "orderOut:"}

    shown: list[str] = []
    app_delegate = type("AppDelegate", (), {})
    browser_view = SimpleNamespace(
        AppDelegate=app_delegate,
        instances={"master": SimpleNamespace(show=lambda: shown.append("master"))},
    )
    assert prepare_macos_application_lifecycle(cocoa=SimpleNamespace(BrowserView=browser_view))
    delegate = app_delegate()
    assert delegate.applicationShouldHandleReopen_hasVisibleWindows_(None, False)
    assert shown == ["master"]


def test_desktop_window_default_is_larger_and_upgrades_the_previous_default():
    assert desktop_window_dimension({}, "width") == 1360
    assert desktop_window_dimension({}, "height") == 880
    assert desktop_window_dimension({"width": 1180}, "width") == 1360
    assert desktop_window_dimension({"height": 780}, "height") == 880
    assert desktop_window_dimension({"width": 1512}, "width") == 1512


def test_macos_titlebar_uses_theme_color_without_replacing_native_frame():
    calls: dict[str, object] = {}

    class Color:
        @staticmethod
        def colorWithSRGBRed_green_blue_alpha_(red, green, blue, alpha):
            calls["rgba"] = (red, green, blue, alpha)
            return SimpleNamespace(CGColor=lambda: "theme-cg-color")

        @staticmethod
        def colorWithCalibratedRed_green_blue_alpha_(_red, _green, _blue, _alpha):
            raise AssertionError("sRGB should be preferred when AppKit provides it")

        @staticmethod
        def clearColor():
            return SimpleNamespace(CGColor=lambda: "clear-cg-color")

    class Layer:
        def __init__(self, name):
            self.name = name

        def setBackgroundColor_(self, value):
            calls[f"{self.name}-layer"] = value

        def setOpaque_(self, value):
            calls[f"{self.name}-opaque"] = value

    class Titlebar:
        def __init__(self):
            self.material = SimpleNamespace(
                className=lambda: "NSVisualEffectView",
                setHidden_=lambda value: calls.__setitem__("material-hidden", value),
            )

        @staticmethod
        def setWantsLayer_(value):
            calls["titlebar-wants-layer"] = value

        @staticmethod
        def layer():
            return Layer("titlebar")

        def setBackgroundColor_(self, value):
            calls["titlebar"] = value

        def className(self):
            return "NSTitlebarContainerView"

        def subviews(self):
            return [
                SimpleNamespace(
                    className=lambda: "NSTitlebarBackgroundView",
                    subviews=lambda: [self.material],
                )
            ]

    titlebar = Titlebar()

    class ThemeFrame:
        @staticmethod
        def subviews():
            return SimpleNamespace(lastObject=lambda: titlebar)

    theme_frame = ThemeFrame()

    class NativeWindow:
        @staticmethod
        def styleMask():
            return 7

        def setStyleMask_(self, value):
            calls["style-mask"] = value

        def setBackgroundColor_(self, value):
            calls["window"] = value

        def setOpaque_(self, value):
            calls["opaque"] = value

        def setMovableByWindowBackground_(self, value):
            calls["movable-by-background"] = value

        def setTitlebarAppearsTransparent_(self, value):
            calls["transparent"] = value

        def setTitleVisibility_(self, value):
            calls["visibility"] = value

        def setTitlebarSeparatorStyle_(self, value):
            calls["separator"] = value

        @staticmethod
        def contentView():
            return SimpleNamespace(superview=lambda: theme_frame)

    appkit = SimpleNamespace(
        NSColor=Color,
        NSWindowTitleHidden="hidden",
        NSWindowTitlebarSeparatorStyleNone="none",
        NSWindowStyleMaskFullSizeContentView=8,
    )
    assert style_macos_titlebar(NativeWindow(), "#345b67", appkit=appkit)
    assert calls == {
        "rgba": (52 / 255, 91 / 255, 103 / 255, 1.0),
        "style-mask": 15,
        "window": calls["window"],
        "transparent": True,
        "visibility": "hidden",
        "opaque": True,
        "movable-by-background": True,
        "material-hidden": True,
        "titlebar": calls["titlebar"],
        "titlebar-wants-layer": True,
        "titlebar-opaque": False,
        "titlebar-layer": "clear-cg-color",
        "separator": "none",
    }
    assert not style_macos_titlebar(NativeWindow(), "not-a-color", appkit=appkit)


def test_release_security_rejects_foreign_host_and_origin_and_sets_headers(settings, app):
    settings.release_mode = True
    release_app = create_app(
        settings,
        metadata_service=app.state.metadata,
        secret_store=app.state.secrets,
    )
    with TestClient(release_app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert page.headers["x-content-type-options"] == "nosniff"
        assert page.headers["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
        assert "'unsafe-eval'" not in page.headers["content-security-policy"]
        assert "access-control-allow-origin" not in page.headers
        assert client.get("/docs").status_code == 404

        invalid_host = client.get("/health", headers={"Host": "attacker.example"})
        assert invalid_host.status_code == 400
        assert invalid_host.json()["error"]["code"] == "invalid_host"

        foreign = client.post(
            "/api/backups",
            headers={"Origin": "https://attacker.example"},
            json={},
        )
        assert foreign.status_code == 403
        assert foreign.json()["error"]["code"] == "foreign_origin"

        wrong_port = client.post(
            "/api/backups",
            headers={"Origin": "http://testserver:4444"},
            json={},
        )
        assert wrong_port.status_code == 403

        wrong_scheme = client.post(
            "/api/backups",
            headers={"Origin": "https://testserver"},
            json={},
        )
        assert wrong_scheme.status_code == 403

        same_origin = client.post(
            "/api/backups",
            headers={"Origin": "http://testserver"},
            json={},
        )
        assert same_origin.status_code == 200


def test_local_native_bridge_csp_is_scoped_to_packaged_desktop(settings, app):
    native_settings = settings.model_copy(
        update={"native_actions": True, "access_mode": "local"}
    )
    native_app = create_app(
        native_settings,
        metadata_service=app.state.metadata,
        secret_store=app.state.secrets,
    )
    with TestClient(
        native_app,
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 50_000),
    ) as client:
        assert (
            "script-src 'self' 'unsafe-eval'"
            in client.get("/").headers["content-security-policy"]
        )

    server_settings = native_settings.model_copy(
        update={
            "access_mode": "server",
            "native_actions": True,
            "public_base_url": "https://native.example",
            "application_secret": (
                "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_" * 2
            ),
            "server_bootstrap_token": "server-bootstrap-token-that-is-long-enough",
            "trusted_hosts": "native.example",
            "trusted_proxy_ips": "127.0.0.1,::1",
            "release_scheduler_enabled": False,
        }
    )
    server_app = create_app(
        server_settings,
        metadata_service=app.state.metadata,
        secret_store=app.state.secrets,
    )
    with TestClient(server_app, base_url="https://native.example") as client:
        assert "'unsafe-eval'" not in client.get("/").headers["content-security-policy"]


def test_personal_tailscale_host_is_account_free_but_not_a_native_bridge(settings, app):
    shared_settings = settings.model_copy(
        update={
            "native_actions": True,
            "access_mode": "local",
            "personal_tailscale_enabled": True,
            "personal_tailscale_url": "https://media.private.ts.net",
        }
    )
    shared_app = create_app(
        shared_settings,
        metadata_service=app.state.metadata,
        secret_store=app.state.secrets,
    )
    with TestClient(
        shared_app,
        base_url="https://media.private.ts.net",
        client=("127.0.0.1", 50_000),
    ) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "'unsafe-eval'" not in page.headers["content-security-policy"]
        assert client.get("/api/entries").status_code == 200
        settings_payload = client.get("/api/settings/general").json()
        assert settings_payload["native_actions"] is False
        assert (
            client.post(
                "/api/system/open-folder?kind=data",
                headers={"Origin": "https://media.private.ts.net"},
                json={},
            ).status_code
            == 409
        )

    with TestClient(
        shared_app,
        base_url="https://media.private.ts.net",
        client=("100.64.0.8", 50_000),
    ) as tailscale_client:
        assert tailscale_client.get("/").status_code == 200

    with TestClient(
        shared_app,
        base_url="https://media.private.ts.net",
        client=("192.0.2.8", 50_000),
    ) as outside_client:
        rejected = outside_client.get("/")
        assert rejected.status_code == 403
        assert rejected.json()["error"]["code"] == "tailscale_proxy_required"


def test_runtime_paths_and_explicit_overrides_are_outside_install_bundle(tmp_path):
    platform_paths = platform_runtime_paths()
    assert platform_paths.database_path.parent == platform_paths.data_dir
    settings = Settings(
        data_dir=tmp_path / "private-data",
        config_dir=tmp_path / "private-config",
        cache_dir=tmp_path / "private-cache",
        log_dir=tmp_path / "private-logs",
        backups_dir=tmp_path / "private-backups",
        database_path=None,
    )
    settings.ensure_runtime_directories()
    assert settings.resolved_database_path == tmp_path / "private-data/watchtracker.sqlite3"
    assert all(
        path.is_dir()
        for path in (
            settings.resolved_data_dir,
            settings.resolved_config_dir,
            settings.resolved_cache_dir,
            settings.resolved_log_dir,
            settings.resolved_backups_dir,
        )
    )
    if __import__("os").name != "nt":
        assert settings.resolved_config_dir.stat().st_mode & 0o777 == 0o700


def test_native_server_window_uses_loopback_and_persistent_webview_storage(
    settings, monkeypatch
):
    captured: dict[str, object] = {}

    class Window:
        width = 1180
        height = 780
        x = 20
        y = 30

    def create_window(_title, url, **options):
        captured["url"] = url
        captured["window_options"] = options
        return Window()

    def start(**options):
        captured["start_options"] = options

    monkeypatch.setitem(
        sys.modules,
        "webview",
        SimpleNamespace(create_window=create_window, start=start),
    )
    monkeypatch.setattr("watchtracker.launcher.sys.platform", "linux")
    native_settings = settings.model_copy(
        update={
            "access_mode": "server",
            "release_mode": True,
            "native_actions": True,
            "native_host_token": "native-host-token-that-is-long-and-random-enough",
        }
    )
    controller = SimpleNamespace(
        url="http://127.0.0.1:8000",
        app=SimpleNamespace(state=SimpleNamespace(updates=None)),
    )

    _run_webview(controller, native_settings)

    assert str(captured["url"]).startswith("http://127.0.0.1:8000?desktop=linux")
    assert str(captured["url"]).endswith(
        "#native-host=native-host-token-that-is-long-and-random-enough"
    )
    assert captured["window_options"]["width"] == 1360
    assert captured["window_options"]["height"] == 880
    start_options = captured["start_options"]
    assert start_options["private_mode"] is False
    assert start_options["storage_path"] == str(
        native_settings.resolved_config_dir / "native-webview"
    )
    assert (native_settings.resolved_config_dir / "native-webview").is_dir()


def test_saved_server_window_uses_one_time_handoff_without_password(settings, monkeypatch):
    profile = SimpleNamespace(id="profile-1", base_url="https://family.example")
    remote = SimpleNamespace(
        store=SimpleNamespace(enabled_profiles=lambda: [profile]),
        browser_handoff=lambda profile_id: (profile, "h" * 43),
    )
    monkeypatch.setattr("watchtracker.launcher.sys.platform", "darwin")

    url = _saved_server_window_url(
        settings,
        "http://127.0.0.1:43123",
        client=remote,
    )

    assert url is not None
    assert url.startswith(
        "https://family.example/?desktop=macos&client_return=http%3A%2F%2F127.0.0.1%3A43123"
    )
    assert url.endswith(f"#native-session={'h' * 43}")


def test_owner_setup_cli_reads_password_interactively_and_locks_bootstrap(
    tmp_path, monkeypatch, capsys
):
    answers = iter(["correct horse battery", "correct horse battery"])
    monkeypatch.setattr("watchtracker.launcher.getpass.getpass", lambda _prompt: next(answers))
    assert main(["--data-dir", str(tmp_path / "owner-cli"), "setup-owner"]) == 0
    assert "Bootstrap is now locked" in capsys.readouterr().out

    answers = iter(["another secure password", "another secure password"])
    monkeypatch.setattr("watchtracker.launcher.getpass.getpass", lambda _prompt: next(answers))
    with pytest.raises(LauncherError, match="already been set up"):
        main(["--data-dir", str(tmp_path / "owner-cli"), "setup-owner"])


def test_product_rename_reuses_an_existing_legacy_library(tmp_path, monkeypatch):
    class FakePlatformDirs:
        def __init__(self, app_name, _author, **_kwargs):
            root = tmp_path / app_name
            self.user_data_dir = str(root / "data")
            self.user_cache_dir = str(root / "cache")
            self.user_config_dir = str(root / "config")
            self.user_log_dir = str(root / "logs")

    monkeypatch.setattr("watchtracker.runtime.PlatformDirs", FakePlatformDirs)
    legacy_database = tmp_path / "Personal Watch Tracker/data/watchtracker.sqlite3"
    legacy_database.parent.mkdir(parents=True)
    legacy_database.touch()
    paths = platform_runtime_paths()
    assert paths.database_path == legacy_database

    legacy_database.unlink()
    paths = platform_runtime_paths()
    assert paths.database_path == (
        tmp_path / "Personal Media Tracker/data/watchtracker.sqlite3"
    )


def test_free_port_selection_and_single_instance_lock(settings, monkeypatch):
    class FakeSocket:
        def setsockopt(self, *_args):
            return None

        def bind(self, address):
            self.address = (address[0], 43210)

        def listen(self, _backlog):
            return None

        def set_inheritable(self, _value):
            return None

        def getsockname(self):
            return self.address

        def close(self):
            return None

    monkeypatch.setattr("watchtracker.launcher.socket.socket", lambda *_args: FakeSocket())
    server_socket = bind_server_socket("127.0.0.1", 0)
    try:
        assert socket_port(server_socket) > 0
    finally:
        server_socket.close()

    first = SingleInstance(settings)
    second = SingleInstance(settings)
    first.acquire()
    first.publish("http://127.0.0.1:45678", native_window=True)
    assert second.existing_url() == "http://127.0.0.1:45678"
    assert second.existing_state() == {
        "url": "http://127.0.0.1:45678",
        "pid": os.getpid(),
        "native_window": True,
    }
    with pytest.raises(LauncherError, match="already running"):
        second.acquire()
    first.release()
    second.acquire()
    second.release()


def test_duplicate_server_launch_activates_native_window_without_browser(settings, monkeypatch):
    instance = SingleInstance(settings)
    instance.publish("http://127.0.0.1:45678", native_window=True)
    opened = []
    activated = []
    monkeypatch.setattr("watchtracker.launcher.webbrowser.open", opened.append)
    monkeypatch.setattr(
        "watchtracker.launcher.activate_existing_instance",
        lambda pid: activated.append(pid) or True,
    )

    server_settings = settings.model_copy(update={"access_mode": "server"})
    assert reopen_existing_instance(instance, server_settings) is True
    assert activated == [os.getpid()]
    assert opened == []
    instance.release()


def test_duplicate_headless_server_never_opens_protected_loopback_in_browser(
    settings, monkeypatch
):
    instance = SingleInstance(settings)
    instance.publish("http://127.0.0.1:45678", native_window=False)
    opened = []
    monkeypatch.setattr("watchtracker.launcher.webbrowser.open", opened.append)

    server_settings = settings.model_copy(update={"access_mode": "server"})
    with pytest.raises(LauncherError, match="running in the background"):
        reopen_existing_instance(instance, server_settings)
    assert opened == []
    instance.release()


def test_macos_existing_instance_activation_uses_all_windows():
    calls = []

    class Application:
        def activateWithOptions_(self, options):
            calls.append(options)
            return True

    appkit = SimpleNamespace(
        NSApplicationActivateAllWindows=1,
        NSApplicationActivateIgnoringOtherApps=2,
        NSRunningApplication=SimpleNamespace(
            runningApplicationWithProcessIdentifier_=lambda pid: (
                calls.append(pid) or Application()
            )
        ),
    )

    assert activate_existing_instance(1234, appkit=appkit)
    assert calls == [1234, 3]


def test_health_wait_retries_before_returning(monkeypatch):
    attempts = []

    class HealthyResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def fake_urlopen(*_args, **_kwargs):
        attempts.append(True)
        if len(attempts) == 1:
            raise OSError("not ready")
        return HealthyResponse()

    monkeypatch.setattr("watchtracker.launcher.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("watchtracker.launcher.time.sleep", lambda _delay: None)
    wait_for_health("http://127.0.0.1:43210", timeout=1)
    assert len(attempts) == 2


def test_server_controller_probes_wildcard_binding_through_loopback():
    controller = ServerController(object(), "0.0.0.0", 0)
    try:
        assert controller.url == f"http://127.0.0.1:{controller.port}"
    finally:
        controller.socket.close()


def test_fixed_port_and_unwritable_data_errors_are_friendly(settings, monkeypatch, tmp_path):
    class RefusingSocket:
        closed = False

        def setsockopt(self, *_args):
            return None

        def bind(self, _address):
            raise OSError("occupied")

        def close(self):
            self.closed = True

    refusing = RefusingSocket()
    monkeypatch.setattr("watchtracker.launcher.socket.socket", lambda *_args: refusing)
    with pytest.raises(LauncherError, match="port 8000"):
        bind_server_socket("127.0.0.1", 8000)
    assert refusing.closed is True

    real_mkdir = __import__("pathlib").Path.mkdir
    blocked = tmp_path / "blocked"

    def refusing_mkdir(path, *args, **kwargs):
        if path == blocked:
            raise PermissionError("read only")
        return real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr("pathlib.Path.mkdir", refusing_mkdir)
    with pytest.raises(LauncherError, match="data folder"):
        main(["--smoke-test", "--data-dir", str(blocked)])


def test_packaged_static_assets_do_not_depend_on_current_working_directory(settings, app):
    settings.release_mode = True
    release_app = create_app(
        settings,
        metadata_service=app.state.metadata,
        secret_store=app.state.secrets,
    )
    with TestClient(release_app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/static/app.js").status_code == 200
        assert client.get("/static/theme-init.js").status_code == 200
        assert client.get("/static/favicon.svg").status_code == 200


def test_dangerous_poster_url_is_rejected(client):
    response = client.post(
        "/api/entries/from-search",
        json={
            "result": {
                "provider": "tmdb_movie",
                "provider_id": "unsafe-poster",
                "title": "Unsafe Poster",
                "year": 2024,
                "media_type": "movie",
                "poster_url": "javascript:alert(1)",
            }
        },
    )
    assert response.status_code == 422


def test_desktop_bridge_rejects_foreign_and_non_export_urls(monkeypatch):
    opened = []
    monkeypatch.setattr("watchtracker.launcher.webbrowser.open", opened.append)
    bridge = DesktopBridge("http://127.0.0.1:43210")

    assert bridge.open_external("javascript:alert(1)") is False
    assert bridge.open_external("https://example.com/help") is None
    assert opened == ["https://example.com/help"]
    bridge.window = object()
    assert bridge.save_export("https://attacker.example/api/exports/watch-log.csv") is False
    assert bridge.save_export("https://127.0.0.1:43210/api/exports/watch-log.csv") is False
    assert bridge.save_export("http://127.0.0.1:43210/api/entries") is False


def test_remote_client_requires_https_and_versioned_pmt_capabilities(monkeypatch):
    class CapabilityResponse(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    monkeypatch.setattr(
        "watchtracker.launcher.urllib.request.urlopen",
        lambda *_args, **_kwargs: CapabilityResponse(
            b'{"product":"personal-media-tracker","api_version":"1","instance_id":"server-1",'
            b'"mode":"server","library_authority":"pmt_server"}'
        ),
    )
    url, capabilities = _remote_server_url("https://family.example/")
    assert url == "https://family.example"
    assert capabilities["instance_id"] == "server-1"
    with pytest.raises(LauncherError, match="HTTPS origin"):
        _remote_server_url("http://family.example")


@pytest.mark.parametrize("selection_type", [tuple, list])
def test_desktop_bridge_streams_a_local_export_to_the_chosen_file(
    monkeypatch, tmp_path, selection_type
):
    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace(SAVE_DIALOG="save"))

    class ExportResponse(io.BytesIO):
        headers = {
            "Content-Disposition": 'attachment; filename="personal-media-tracker-everything.zip"'
        }

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    destination = tmp_path / "chosen.zip"
    response = ExportResponse(b"portable-archive")

    class Window:
        def create_file_dialog(self, _kind, *, save_filename):
            assert save_filename == "personal-media-tracker-everything.zip"
            assert response.closed
            return selection_type([str(destination)])

    monkeypatch.setattr(
        "watchtracker.launcher.urllib.request.urlopen",
        lambda *_args, **_kwargs: response,
    )
    bridge = DesktopBridge("http://127.0.0.1:43210")
    bridge.window = Window()
    assert bridge.save_export("http://127.0.0.1:43210/api/exports/portable-library.zip")
    assert destination.read_bytes() == b"portable-archive"
