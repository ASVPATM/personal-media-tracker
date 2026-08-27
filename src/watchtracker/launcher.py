from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import logging
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
from contextlib import suppress
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import uvicorn
from filelock import FileLock, Timeout

from watchtracker import __version__
from watchtracker.config import Settings
from watchtracker.db import make_engine, make_session_factory, upgrade_database
from watchtracker.icons import (
    DEFAULT_ICON_BACKGROUND,
    DEFAULT_ICON_TEXT,
    render_icon,
    valid_icon_color,
)
from watchtracker.remote_client import RemoteClientError, RemoteDeviceClient, RemoteProfileStore
from watchtracker.services.auth import AuthService
from watchtracker.services.backups import BackupService
from watchtracker.services.preferences import PreferenceStore
from watchtracker.tailscale_access import TailscaleAccessError, TailscaleAccessManager

logger = logging.getLogger(__name__)

DEFAULT_DESKTOP_WINDOW_WIDTH = 1360
DEFAULT_DESKTOP_WINDOW_HEIGHT = 880
LEGACY_DESKTOP_WINDOW_SIZE = {"width": 1180, "height": 780}
MINIMUM_DESKTOP_WINDOW_SIZE = {"width": 760, "height": 560}


class LauncherError(RuntimeError):
    pass


def reject_root_linux_desktop_launch(arguments: argparse.Namespace) -> None:
    """Keep desktop installs and private libraries in the signed-in Linux account."""
    if (
        sys.platform.startswith("linux")
        and hasattr(os, "geteuid")
        and os.geteuid() == 0
        and arguments.command == "run"
        and not arguments.smoke_test
    ):
        raise LauncherError(
            "Do not start the Personal Media Tracker desktop app with sudo. "
            "That opens a separate root-owned install and library, which may be an older "
            "version. Extract the latest Linux archive as your normal user, run "
            "./install-linux.sh without sudo, then open PMT from your application launcher."
        )


def regular_desktop_settings(settings: Settings, *, command: str) -> Settings:
    """Keep the packaged desktop artifact a client even with legacy server.env state.

    PMT Server ships as the separate Docker/setup artifact. Older desktop releases
    could persist server mode into the regular app's config directory; treating that
    stale value as local at runtime prevents an update from gating the personal app
    behind the old server-account login. No database row or config file is deleted.
    """
    if not settings.packaged or settings.access_mode != "server":
        return settings
    if command == "server":
        raise LauncherError(
            "The regular desktop package cannot host PMT Server. Use the separate "
            "PMT Server Setup Beta package."
        )
    logger.warning(
        "Ignoring legacy server mode in the regular desktop package; opening local client mode."
    )
    return settings.model_copy(
        update={
            "access_mode": "local",
            "host": "127.0.0.1",
            "public_base_url": None,
            "application_secret": None,
            "server_bootstrap_token": None,
            "trusted_hosts": "",
            "trusted_proxy_ips": "",
        }
    )


def show_launcher_error(message: str) -> None:
    """Show a small native error for windowed builds, with a safe stderr fallback."""
    title = "Personal Media Tracker"
    try:
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
            return
        if sys.platform == "darwin" and Path("/usr/bin/osascript").exists():
            script = (
                f"display alert {json.dumps(title)} message {json.dumps(message)} as critical"
            )
            subprocess.run(
                ["/usr/bin/osascript", "-e", script],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
            return
        for executable, arguments in (
            ("zenity", ["--error", f"--title={title}", f"--text={message}"]),
            ("kdialog", ["--error", message, "--title", title]),
        ):
            path = shutil.which(executable)
            if path:
                subprocess.run(
                    [path, *arguments],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=15,
                )
                return
    except Exception:
        pass
    print(f"{title}: {message}", file=sys.stderr)


def bind_server_socket(host: str, port: int) -> socket.socket:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    server_socket = socket.socket(family, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_socket.bind((host, port))
        server_socket.listen(128)
        server_socket.set_inheritable(True)
    except OSError as exc:
        server_socket.close()
        requested = f"port {port}" if port else "a local port"
        raise LauncherError(f"Personal Media Tracker could not use {requested}.") from exc
    return server_socket


def socket_port(server_socket: socket.socket) -> int:
    return int(server_socket.getsockname()[1])


def wait_for_health(url: str, *, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=0.5) as response:
                if response.status == 200:
                    return
        except Exception as exc:
            last_error = exc
        time.sleep(0.05)
    raise LauncherError(
        "The local application server did not become ready. Open the logs folder for details."
    ) from last_error


class ServerController:
    def __init__(self, app, host: str, port: int):
        self.app = app
        self.host = host
        self.socket = bind_server_socket(host, port)
        self.port = socket_port(self.socket)
        # Wildcard addresses are valid bind targets but unreliable client targets:
        # proxy-aware HTTP clients can route 0.0.0.0 externally. Always probe and
        # publish the corresponding loopback address instead.
        if host == "0.0.0.0":
            display_host = "127.0.0.1"
        elif host in {"::", "::1"}:
            display_host = "[::1]"
        else:
            display_host = host
        self.url = f"http://{display_host}:{self.port}"
        self.server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=host,
                port=self.port,
                log_config=None,
                access_log=False,
                server_header=False,
            )
        )
        self.thread = threading.Thread(
            target=self.server.run,
            kwargs={"sockets": [self.socket]},
            name="watchtracker-local-server",
            daemon=True,
        )

    def start(self, *, timeout: float = 20.0) -> None:
        self.thread.start()
        wait_for_health(self.url, timeout=timeout)

    def stop(self, *, timeout: float = 10.0) -> None:
        self.server.should_exit = True
        if self.thread.is_alive():
            self.thread.join(timeout)
        with suppress(OSError):
            self.socket.close()
        if self.thread.is_alive():
            raise LauncherError("The local application server did not stop cleanly.")


class SingleInstance:
    def __init__(self, settings: Settings):
        settings.resolved_data_dir.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(settings.instance_lock_path)
        self.state_path = settings.instance_state_path

    def acquire(self) -> None:
        try:
            self.lock.acquire(timeout=0)
        except Timeout as exc:
            raise LauncherError("Personal Media Tracker is already running.") from exc

    def publish(self, url: str, *, native_window: bool = False) -> None:
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "url": url,
                    "pid": os.getpid(),
                    "native_window": native_window,
                }
            ),
            encoding="utf-8",
        )
        os.replace(temporary, self.state_path)
        if os.name != "nt":
            self.state_path.chmod(0o600)

    def existing_state(self) -> dict | None:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            url = str(value.get("url") or "")
            parsed = urlsplit(url)
            pid = int(value.get("pid") or 0)
            if (
                parsed.scheme == "http"
                and parsed.hostname in {"127.0.0.1", "::1", "localhost"}
                and pid > 1
            ):
                return {
                    "url": url,
                    "pid": pid,
                    "native_window": value.get("native_window") is True,
                }
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
        return None

    def existing_url(self) -> str | None:
        state = self.existing_state()
        return str(state["url"]) if state else None

    def release(self) -> None:
        self.state_path.unlink(missing_ok=True)
        if self.lock.is_locked:
            self.lock.release()


def activate_existing_instance(pid: int, *, appkit=None) -> bool:
    """Bring an existing macOS native window forward without opening a browser."""
    if (sys.platform != "darwin" and appkit is None) or pid <= 1:
        return False
    try:
        if appkit is None:
            import AppKit as appkit

        application = appkit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if application is None:
            return False
        options = int(appkit.NSApplicationActivateAllWindows) | int(
            appkit.NSApplicationActivateIgnoringOtherApps
        )
        return bool(application.activateWithOptions_(options))
    except Exception:
        return False


def reopen_existing_instance(instance: SingleInstance, settings: Settings) -> bool:
    """Handle a duplicate launch without exposing a protected server loopback URL."""
    state = instance.existing_state()
    if state is None:
        return False
    if state["native_window"]:
        if activate_existing_instance(int(state["pid"])):
            return True
        raise LauncherError(
            "Personal Media Tracker is already running. Bring its existing window forward "
            "from the Dock, or close it before opening the app again."
        )
    if settings.access_mode == "local":
        webbrowser.open(str(state["url"]))
        return True
    raise LauncherError(
        "PMT Server is already running in the background. Stop that headless server "
        "before opening the desktop application."
    )


class DesktopBridge:
    def __init__(self, base_url: str, update_service=None):
        self.base_url = base_url
        self.update_service = update_service
        self.window = None

    def open_external(self, url: str) -> bool:
        parsed = urlsplit(url)
        if parsed.scheme not in {"https", "mailto"}:
            return False
        return webbrowser.open(url)

    def set_window_background(self, color: str) -> bool:
        """Keep macOS native window chrome in step with the web theme."""
        if not self.window or not re.fullmatch(r"#[0-9a-fA-F]{6}", str(color)):
            return False
        try:
            native_window = self.window.native
            if sys.platform == "darwin":
                from PyObjCTools import AppHelper

                AppHelper.callAfter(style_macos_titlebar, native_window, color)
                return True
            return False
        except Exception:
            return False

    def set_application_icon(self, background_color: str, text_color: str) -> bool:
        """Update the running macOS Dock icon without modifying the signed bundle."""
        if (
            not self.window
            or sys.platform != "darwin"
            or not valid_icon_color(background_color)
            or not valid_icon_color(text_color)
        ):
            return False
        try:
            from PyObjCTools import AppHelper

            AppHelper.callAfter(
                set_macos_application_icon,
                background_color,
                text_color,
            )
            return True
        except Exception:
            return False

    def install_update(self) -> bool:
        """Hand a verified staged update to a detached helper, then close cleanly."""
        if not self.window or not self.update_service or sys.platform != "darwin":
            return False
        try:
            self.update_service.launch_installer(current_pid=os.getpid())
            from PyObjCTools import AppHelper

            AppHelper.callAfter(self.window.destroy)
            return True
        except Exception:
            return False

    def save_export(self, url: str) -> bool:
        if not self.window:
            return False
        parsed = urlsplit(url)
        base = urlsplit(self.base_url)
        if (
            parsed.scheme != base.scheme
            or parsed.netloc != base.netloc
            or not parsed.path.startswith("/api/exports/")
        ):
            return False
        temporary_destination: Path | None = None
        try:
            with tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024) as staged:
                cookie_values = []
                get_cookies = getattr(self.window, "get_cookies", None)
                for cookie_jar in get_cookies() if callable(get_cookies) else []:
                    cookie_values.extend(
                        f"{morsel.key}={morsel.value}" for morsel in cookie_jar.values()
                    )
                request = urllib.request.Request(
                    url,
                    headers={"Cookie": "; ".join(cookie_values)} if cookie_values else {},
                )
                with urllib.request.urlopen(request, timeout=30) as response:
                    disposition = response.headers.get("Content-Disposition", "")
                    match = re.search(r'filename="?([^";]+)', disposition)
                    filename = Path(match.group(1)).name if match else "watchtracker-export"
                    shutil.copyfileobj(response, staged, length=1024 * 1024)
                staged.seek(0)

                import webview

                selected = self.window.create_file_dialog(
                    webview.SAVE_DIALOG,
                    save_filename=filename,
                )
                if not selected:
                    return False
                if isinstance(selected, (list, tuple)):
                    if not selected:
                        return False
                    selected = selected[0]
                destination = Path(selected)
                descriptor, temporary_name = tempfile.mkstemp(
                    prefix=f".{destination.name}.",
                    dir=destination.parent,
                )
                temporary_destination = Path(temporary_name)
                with os.fdopen(descriptor, "wb") as output:
                    shutil.copyfileobj(staged, output, length=1024 * 1024)
                os.replace(temporary_destination, destination)
                temporary_destination = None
            return True
        except Exception:
            return False
        finally:
            if temporary_destination is not None:
                temporary_destination.unlink(missing_ok=True)


def desktop_window_background(preferences: dict, *, system_dark: bool = False) -> str:
    """Match native desktop chrome to the saved application background."""
    theme = preferences.get("theme")
    use_dark_background = theme == "dark" or (theme == "system" and system_dark)
    background = "#151918" if use_dark_background else "#f4f2ed"
    custom = preferences.get("background_color")
    if isinstance(custom, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", custom):
        if preferences.get("background_mode") == "full":
            return custom.lower()
        try:
            strength = max(0.0, min(100.0, float(preferences.get("background_strength", 16))))
        except (TypeError, ValueError):
            strength = 16.0
        ratio = strength / 100
        custom_channels = [int(custom[index : index + 2], 16) for index in (1, 3, 5)]
        base_channels = [int(background[index : index + 2], 16) for index in (1, 3, 5)]
        blended = [
            int(custom_value * ratio + base_value * (1 - ratio) + 0.5)
            for custom_value, base_value in zip(custom_channels, base_channels, strict=True)
        ]
        return "#" + "".join(f"{channel:02x}" for channel in blended)
    return background


def macos_prefers_dark_appearance(*, appkit=None) -> bool:
    """Resolve macOS' effective appearance for the desktop startup color."""
    if sys.platform != "darwin" and appkit is None:
        return False
    try:
        if appkit is None:
            import AppKit as appkit

        appearance = appkit.NSApplication.sharedApplication().effectiveAppearance()
        match = appearance.bestMatchFromAppearancesWithNames_(
            [appkit.NSAppearanceNameAqua, appkit.NSAppearanceNameDarkAqua]
        )
        return match == appkit.NSAppearanceNameDarkAqua
    except Exception:
        return False


def desktop_window_dimension(stored: dict, name: str) -> int:
    """Return a saved desktop dimension while upgrading the former default size."""
    default = DEFAULT_DESKTOP_WINDOW_WIDTH if name == "width" else DEFAULT_DESKTOP_WINDOW_HEIGHT
    try:
        value = int(stored.get(name, default))
    except (TypeError, ValueError):
        return default
    if value == LEGACY_DESKTOP_WINDOW_SIZE[name]:
        return default
    return max(value, MINIMUM_DESKTOP_WINDOW_SIZE[name])


def prepare_macos_application_lifecycle(*, cocoa=None) -> bool:
    """Make a hidden PMT window reopen when its Dock icon is selected."""
    if sys.platform != "darwin" and cocoa is None:
        return False
    try:
        if cocoa is None:
            import webview.platforms.cocoa as cocoa

        browser_view = cocoa.BrowserView

        def applicationShouldHandleReopen_hasVisibleWindows_(
            _delegate, _application, _has_visible_windows
        ):
            for instance in tuple(browser_view.instances.values()):
                with suppress(Exception):
                    instance.show()
            return True

        browser_view.AppDelegate.applicationShouldHandleReopen_hasVisibleWindows_ = (
            applicationShouldHandleReopen_hasVisibleWindows_
        )
        return True
    except Exception:
        return False


def configure_macos_close_button(native_window, *, appkit=None) -> bool:
    """Make the red traffic-light hide PMT; Dock Quit still terminates the app."""
    if not native_window or (sys.platform != "darwin" and appkit is None):
        return False
    try:
        if appkit is None:
            import AppKit as appkit

        close_button = native_window.standardWindowButton_(appkit.NSWindowCloseButton)
        if close_button is None:
            return False
        close_button.setTarget_(native_window)
        close_button.setAction_("orderOut:")
        return True
    except Exception:
        return False


def style_macos_titlebar(native_window, color: str, *, appkit=None) -> bool:
    """Theme a framed Cocoa title bar without replacing its native controls or drag area."""
    if not native_window or not re.fullmatch(r"#[0-9a-fA-F]{6}", str(color)):
        return False
    try:
        if appkit is None:
            import AppKit as appkit

        red, green, blue = (int(color[index : index + 2], 16) / 255 for index in (1, 3, 5))
        color_factory = getattr(
            appkit.NSColor,
            "colorWithSRGBRed_green_blue_alpha_",
            appkit.NSColor.colorWithCalibratedRed_green_blue_alpha_,
        )
        background = color_factory(red, green, blue, 1.0)
        clear = appkit.NSColor.clearColor()
        full_size_mask = getattr(
            appkit,
            "NSWindowStyleMaskFullSizeContentView",
            getattr(appkit, "NSFullSizeContentViewWindowMask", 0),
        )
        if full_size_mask:
            native_window.setStyleMask_(native_window.styleMask() | full_size_mask)
        native_window.setBackgroundColor_(background)
        native_window.setTitlebarAppearsTransparent_(True)
        native_window.setTitleVisibility_(appkit.NSWindowTitleHidden)
    except Exception:
        return False

    with suppress(Exception):
        native_window.setOpaque_(True)
    with suppress(Exception):
        native_window.setMovableByWindowBackground_(True)
    try:
        theme_frame = native_window.contentView().superview()
        titlebar = theme_frame.subviews().lastObject()
    except Exception:
        return True

    # A framed NSWindow contains an NSVisualEffectView inside its title-bar
    # background. On recent macOS releases that material keeps drawing the
    # system window color above a custom container color. Hide only that
    # decorative material; the native traffic-light controls and title-bar
    # event handling remain untouched.
    def hide_titlebar_material(view) -> None:
        with suppress(Exception):
            if str(view.className()) == "NSVisualEffectView":
                view.setHidden_(True)
                return
        with suppress(Exception):
            for child in view.subviews():
                hide_titlebar_material(child)

    hide_titlebar_material(titlebar)
    with suppress(Exception):
        titlebar.setBackgroundColor_(clear)
    with suppress(Exception):
        titlebar.setWantsLayer_(True)
        titlebar.layer().setOpaque_(False)
        titlebar.layer().setBackgroundColor_(clear.CGColor())
    with suppress(Exception):
        native_window.setTitlebarSeparatorStyle_(appkit.NSWindowTitlebarSeparatorStyleNone)
    return True


def set_macos_application_icon(
    background_color: str,
    text_color: str,
    *,
    appkit=None,
    foundation=None,
) -> bool:
    """Set a device-local Dock icon while preserving the signed on-disk bundle."""
    if not valid_icon_color(background_color) or not valid_icon_color(text_color):
        return False
    if sys.platform != "darwin" and (appkit is None or foundation is None):
        return False
    try:
        if appkit is None:
            import AppKit as appkit
        if foundation is None:
            import Foundation as foundation

        output = BytesIO()
        render_icon(
            512,
            background_color=background_color,
            text_color=text_color,
        ).save(output, format="PNG", optimize=True)
        payload = output.getvalue()
        data = foundation.NSData.dataWithBytes_length_(payload, len(payload))
        icon = appkit.NSImage.alloc().initWithData_(data)
        if icon is None:
            return False
        appkit.NSApplication.sharedApplication().setApplicationIconImage_(icon)
        return True
    except Exception:
        return False


def _saved_server_window_url(
    settings: Settings,
    local_url: str,
    *,
    client: RemoteDeviceClient | None = None,
) -> str | None:
    """Prepare an enabled saved server account for the installed app window."""
    client = client or RemoteDeviceClient(RemoteProfileStore(settings.remote_client_path))
    profiles = client.store.enabled_profiles()
    if not profiles:
        return None
    profile, handoff = client.browser_handoff(profiles[0].id)
    desktop_platform = {
        "darwin": "macos",
        "win32": "windows",
    }.get(sys.platform, "linux")
    query = urlencode({"desktop": desktop_platform, "client_return": local_url})
    fragment = urlencode({"native-session": handoff})
    return f"{profile.base_url}/?{query}#{fragment}"


def _run_webview(
    controller: ServerController,
    settings: Settings,
    *,
    window_url_override: str | None = None,
) -> None:
    try:
        import webview
    except ImportError as exc:
        raise LauncherError(
            "The desktop window component is unavailable. Use --browser as a fallback."
        ) from exc
    appearance = PreferenceStore(settings).load()
    stored = appearance.get("window") or {}

    def position(name: str) -> int | None:
        value = stored.get(name)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    remote_window = window_url_override is not None
    bridge = (
        None if remote_window else DesktopBridge(controller.url, controller.app.state.updates)
    )
    native_background = desktop_window_background(
        appearance,
        system_dark=sys.platform == "darwin" and macos_prefers_dark_appearance(),
    )
    desktop_platform = {
        "darwin": "macos",
        "win32": "windows",
    }.get(sys.platform, "linux")
    window_url = window_url_override or f"{controller.url}?desktop={desktop_platform}"
    if settings.native_host_token and not remote_window:
        window_url = f"{window_url}#native-host={settings.native_host_token}"
    if sys.platform == "darwin":
        prepare_macos_application_lifecycle()
    window = webview.create_window(
        "Personal Media Tracker",
        window_url,
        js_api=bridge,
        width=desktop_window_dimension(stored, "width"),
        height=desktop_window_dimension(stored, "height"),
        x=position("x"),
        y=position("y"),
        min_size=(760, 560),
        background_color=native_background,
    )
    if bridge is not None:
        bridge.window = window
    if sys.platform == "darwin":

        def apply_native_appearance() -> None:
            style_macos_titlebar(window.native, native_background)
            configure_macos_close_button(window.native)
            icon_text = appearance.get("icon_text_color", DEFAULT_ICON_TEXT)
            if appearance.get("icon_follow_accent"):
                icon_text = appearance.get("accent_color") or icon_text
            set_macos_application_icon(
                appearance.get("icon_background_color", DEFAULT_ICON_BACKGROUND),
                icon_text,
            )

        window.events.before_show += apply_native_appearance
    storage_path = settings.resolved_config_dir / "native-webview"
    storage_path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        storage_path.chmod(0o700)
    start_options = {
        "debug": not settings.release_mode and not remote_window,
        "private_mode": False,
        "storage_path": str(storage_path),
    }
    if sys.platform.startswith("linux"):
        # The Linux bundles ship Qt. Selecting it explicitly avoids pywebview
        # probing an unavailable system GTK/PyGObject installation first.
        start_options["gui"] = "qt"
    webview.start(**start_options)
    try:
        preferences = PreferenceStore(settings).load()
        preferences["window"] = {
            "width": getattr(window, "width", DEFAULT_DESKTOP_WINDOW_WIDTH),
            "height": getattr(window, "height", DEFAULT_DESKTOP_WINDOW_HEIGHT),
            "x": getattr(window, "x", None),
            "y": getattr(window, "y", None),
        }
        PreferenceStore(settings).replace(preferences)
    except Exception:
        pass


def _remote_server_url(value: str) -> tuple[str, dict]:
    url = value.strip().rstrip("/")
    parsed = urlsplit(url)
    loopback = parsed.hostname in {"127.0.0.1", "::1", "localhost"}
    if (
        parsed.scheme not in ({"http", "https"} if loopback else {"https"})
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise LauncherError("A remote PMT connection must be an HTTPS origin without a path.")
    try:
        request = urllib.request.Request(
            f"{url}/api/v1/server/capabilities",
            headers={"Accept": "application/json", "User-Agent": f"PMT/{__version__}"},
        )
        with urllib.request.urlopen(request, timeout=8) as response:
            if response.status != 200:
                raise LauncherError("The PMT Server capability check failed.")
            payload = json.loads(response.read(64 * 1024))
    except LauncherError:
        raise
    except Exception as exc:
        raise LauncherError("The PMT Server could not be reached or verified.") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("product") != "personal-media-tracker"
        or str(payload.get("api_version")) != "1"
        or not payload.get("instance_id")
    ):
        raise LauncherError("The address is not a compatible PMT Server.")
    if payload.get("mode") != "server" or payload.get("library_authority") != "pmt_server":
        raise LauncherError(
            "The address belongs to a local-only PMT library, not a PMT Server."
        )
    return url, payload


def _run_remote_webview(url: str, settings: Settings) -> None:
    try:
        import webview
    except ImportError as exc:
        raise LauncherError(
            "The desktop window component is unavailable. Use --browser as a fallback."
        ) from exc
    appearance = PreferenceStore(settings).load()
    if sys.platform == "darwin":
        prepare_macos_application_lifecycle()
    window = webview.create_window(
        "Personal Media Tracker",
        url,
        width=desktop_window_dimension(appearance.get("window") or {}, "width"),
        height=desktop_window_dimension(appearance.get("window") or {}, "height"),
        min_size=(760, 560),
        background_color=desktop_window_background(
            appearance,
            system_dark=sys.platform == "darwin" and macos_prefers_dark_appearance(),
        ),
    )
    if sys.platform == "darwin":
        native_background = desktop_window_background(
            appearance, system_dark=macos_prefers_dark_appearance()
        )

        def apply_native_appearance() -> None:
            style_macos_titlebar(window.native, native_background)
            configure_macos_close_button(window.native)

        window.events.before_show += apply_native_appearance
    storage_path = settings.resolved_config_dir / "native-webview"
    storage_path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        storage_path.chmod(0o700)
    start_options = {
        "debug": False,
        "private_mode": False,
        "storage_path": str(storage_path),
    }
    if sys.platform.startswith("linux"):
        start_options["gui"] = "qt"
    webview.start(**start_options)


def _settings_from_arguments(arguments) -> Settings:
    values = {}
    env_file = None
    if arguments.host:
        values["host"] = arguments.host
    if arguments.port is not None:
        values["port"] = arguments.port
    if arguments.data_dir:
        data_dir = Path(arguments.data_dir).expanduser().resolve()
        env_file = data_dir / "config" / "server.env"
        values.update(
            data_dir=data_dir,
            database_path=data_dir / "watchtracker.sqlite3",
            backups_dir=data_dir / "backups",
            cache_dir=data_dir / "cache",
            config_dir=data_dir / "config",
            log_dir=data_dir / "logs",
            env_path=env_file,
        )
    return Settings(_env_file=env_file, **values) if env_file else Settings(**values)


def _command_service(settings: Settings) -> BackupService:
    try:
        upgrade_database(settings)
    except OSError as exc:
        raise LauncherError(
            "Personal Media Tracker could not use its data folder. Check folder permissions."
        ) from exc
    engine = make_engine(settings.database_url)
    return BackupService(settings, engine, make_session_factory(engine))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="personal-media-tracker", description="Personal Media Tracker local application"
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--browser", action="store_true", help="open in the default browser")
    parser.add_argument(
        "--desktop", action="store_true", help="force the native desktop window"
    )
    parser.add_argument("--no-open", action="store_true", help="run without opening a UI")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="start the local server, verify it is healthy, then exit",
    )
    parser.add_argument("--host", help="development host override")
    parser.add_argument(
        "--port", type=int, help="fixed development port; packaged mode uses a free port"
    )
    parser.add_argument("--data-dir", help="explicit local data directory")
    parser.add_argument(
        "--connect",
        metavar="HTTPS_URL",
        help="open a verified PMT Server instead of the embedded local library",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=(
            "run",
            "server",
            "worker",
            "backup",
            "verify-backup",
            "restore",
            "migrate-database",
            "setup-owner",
            "recover-server-account",
            "server-readiness",
        ),
        default="run",
    )
    parser.add_argument("path", nargs="?", help="database or backup path for restore/migration")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    reject_root_linux_desktop_launch(arguments)
    settings = _settings_from_arguments(arguments)
    settings = regular_desktop_settings(settings, command=arguments.command)
    if arguments.connect:
        if arguments.command != "run":
            raise LauncherError("--connect cannot be combined with a maintenance command.")
        remote_url, capabilities = _remote_server_url(arguments.connect)
        if capabilities.get("setup_required"):
            # Opening the server is intentional: it lets its owner finish secure setup.
            pass
        if arguments.browser or not (settings.release_mode or arguments.desktop):
            webbrowser.open(remote_url)
        else:
            _run_remote_webview(remote_url, settings)
        return 0
    if arguments.command == "worker":
        if settings.access_mode != "server":
            raise LauncherError("The worker command requires WATCHTRACKER_ACCESS_MODE=server.")
        if settings.database_url.startswith("sqlite"):
            raise LauncherError(
                "SQLite uses the in-process server worker. A separate worker requires PostgreSQL."
            )

        async def run_worker() -> None:
            from watchtracker.app import create_app

            worker_app = create_app(settings)
            async with worker_app.router.lifespan_context(worker_app):
                while True:
                    await asyncio.sleep(30)

        with suppress(KeyboardInterrupt):
            asyncio.run(run_worker())
        return 0
    if arguments.command not in {"run", "server"}:
        service = _command_service(settings)
        if arguments.command == "backup":
            result = (
                service.create_server_snapshot()
                if settings.access_mode == "server"
                else service.create()
            )
            print(result.path)
            return 0
        if arguments.command == "verify-backup":
            if not arguments.path:
                raise LauncherError("verify-backup requires a backup file name")
            source = Path(arguments.path).expanduser().resolve()
            if source.parent != settings.resolved_backups_dir.resolve():
                raise LauncherError(
                    "Copy the archive into PMT's backups directory before verification."
                )
            print(json.dumps(service.verify_recovery_archive(source), indent=2))
            return 0
        if arguments.command == "setup-owner":
            password = getpass.getpass("New owner password (12+ characters): ")
            confirmation = getpass.getpass("Confirm owner password: ")
            if password != confirmation:
                raise LauncherError("The owner password confirmation did not match.")
            try:
                AuthService(service.session_factory, settings).bootstrap(password)
            except ValueError as exc:
                raise LauncherError(str(exc)) from exc
            print("Owner account created. Bootstrap is now locked.")
            return 0
        if arguments.command == "recover-server-account":
            if settings.access_mode != "server":
                raise LauncherError(
                    "Server-account recovery requires the standalone PMT Server environment."
                )
            password = getpass.getpass("New server-account password (12+ characters): ")
            confirmation = getpass.getpass("Confirm server-account password: ")
            if password != confirmation:
                raise LauncherError("The password confirmation did not match.")
            try:
                AuthService(service.session_factory, settings).recover_server_account_password(
                    password
                )
            except ValueError as exc:
                raise LauncherError(str(exc)) from exc
            print(
                "Server-account password replaced from the server host; all existing "
                "sessions were revoked. No library data was changed."
            )
            return 0
        if arguments.command == "server-readiness":
            auth = AuthService(service.session_factory, settings)
            configuration = settings.model_copy(update={"access_mode": "server"})
            checks = {
                "safe_configuration": not configuration.access_configuration_errors(),
                "owner_configured": auth.owner_exists(),
                "local_sqlite": settings.database_url.startswith("sqlite:///"),
                "backup_available": any(settings.resolved_backups_dir.glob("*.zip")),
            }
            print(json.dumps({"ready": all(checks.values()), "checks": checks}, indent=2))
            return 0 if all(checks.values()) else 2
        if not arguments.path:
            raise LauncherError(f"{arguments.command} requires a file path")
        source = Path(arguments.path).expanduser().resolve()
        content = source.read_bytes()
        result = service.restore(
            source.name, content, import_existing=arguments.command == "migrate-database"
        )
        print(json.dumps(result, indent=2))
        return 0

    if arguments.command == "server":
        if settings.access_mode != "server":
            raise LauncherError("The server command requires WATCHTRACKER_ACCESS_MODE=server.")
        arguments.no_open = True
    if not arguments.host and settings.access_mode == "local":
        settings.host = "127.0.0.1"
    if (
        settings.access_mode == "local"
        and (settings.release_mode or arguments.smoke_test)
        and arguments.port is None
        and not settings.personal_tailscale_enabled
    ):
        settings.port = 0
    native_window_requested = bool(
        not arguments.browser
        and not arguments.no_open
        and (settings.release_mode or arguments.desktop)
    )
    settings.native_actions = native_window_requested
    settings.native_host_token = (
        secrets.token_urlsafe(32)
        if native_window_requested and settings.access_mode == "server"
        else None
    )
    try:
        instance = SingleInstance(settings)
    except OSError as exc:
        raise LauncherError(
            "Personal Media Tracker could not use its data folder. Check folder permissions."
        ) from exc
    try:
        instance.acquire()
    except LauncherError:
        if reopen_existing_instance(instance, settings):
            return 0
        raise

    controller = None
    try:
        from watchtracker.app import create_app

        application = create_app(settings)
        controller = ServerController(application, settings.host, settings.port)
        controller.start()
        if settings.personal_tailscale_enabled and native_window_requested:
            try:
                snapshot = TailscaleAccessManager().ensure_route(
                    port=controller.port,
                    previous_managed_port=settings.personal_tailscale_target_port,
                )
                logger.info("Personal Tailscale access ready: %s", snapshot.access_url)
            except TailscaleAccessError as exc:
                # A disconnected tailnet must never prevent the local library from opening.
                logger.warning("Personal Tailscale access is unavailable: %s", exc)
        logger.info(
            "Launcher UI selected: native_window=%s browser=%s no_open=%s access_mode=%s",
            native_window_requested,
            arguments.browser,
            arguments.no_open,
            settings.access_mode,
        )
        instance.publish(controller.url, native_window=native_window_requested)
        if arguments.smoke_test:
            print(f"Personal Media Tracker {__version__} healthy at {controller.url}")
            return 0
        use_desktop = native_window_requested
        if arguments.no_open:
            while controller.thread.is_alive():
                controller.thread.join(0.25)
        elif use_desktop:
            window_url = None
            if settings.access_mode == "local":
                try:
                    window_url = _saved_server_window_url(settings, controller.url)
                except RemoteClientError as exc:
                    logger.warning(
                        "Saved PMT Server is unavailable; opening the local library: %s",
                        exc,
                    )
            _run_webview(controller, settings, window_url_override=window_url)
        else:
            webbrowser.open(settings.public_base_url or controller.url)
            while controller.thread.is_alive():
                controller.thread.join(0.25)
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        if controller:
            controller.stop()
        instance.release()
