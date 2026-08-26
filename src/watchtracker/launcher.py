from __future__ import annotations

import argparse
import getpass
import json
import os
import re
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
from urllib.parse import urlsplit

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
from watchtracker.runtime import is_packaged
from watchtracker.services.auth import AuthService
from watchtracker.services.backups import BackupService
from watchtracker.services.preferences import PreferenceStore


class LauncherError(RuntimeError):
    pass


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
        display_host = "[::1]" if host == "::1" else host
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

    def publish(self, url: str) -> None:
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"url": url, "pid": os.getpid()}), encoding="utf-8")
        os.replace(temporary, self.state_path)

    def existing_url(self) -> str | None:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            url = str(value.get("url") or "")
            parsed = urlsplit(url)
            if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "::1", "localhost"}:
                return url
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        return None

    def release(self) -> None:
        self.state_path.unlink(missing_ok=True)
        if self.lock.is_locked:
            self.lock.release()


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
                with urllib.request.urlopen(url, timeout=30) as response:
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


def _run_webview(controller: ServerController, settings: Settings) -> None:
    try:
        import webview
    except ImportError as exc:
        raise LauncherError(
            "The desktop window component is unavailable. Use --browser as a fallback."
        ) from exc
    appearance = PreferenceStore(settings).load()
    stored = appearance.get("window") or {}

    def dimension(name: str, default: int, minimum: int) -> int:
        try:
            return max(int(stored.get(name, default)), minimum)
        except (TypeError, ValueError):
            return default

    def position(name: str) -> int | None:
        value = stored.get(name)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    bridge = DesktopBridge(controller.url, controller.app.state.updates)
    native_background = desktop_window_background(
        appearance,
        system_dark=sys.platform == "darwin" and macos_prefers_dark_appearance(),
    )
    window_url = (
        f"{controller.url}?desktop=macos" if sys.platform == "darwin" else controller.url
    )
    window = webview.create_window(
        "Personal Media Tracker",
        window_url,
        js_api=bridge,
        width=dimension("width", 1180, 760),
        height=dimension("height", 780, 560),
        x=position("x"),
        y=position("y"),
        min_size=(760, 560),
        background_color=native_background,
    )
    bridge.window = window
    if sys.platform == "darwin":

        def apply_native_appearance() -> None:
            style_macos_titlebar(window.native, native_background)
            icon_text = appearance.get("icon_text_color", DEFAULT_ICON_TEXT)
            if appearance.get("icon_follow_accent"):
                icon_text = appearance.get("accent_color") or icon_text
            set_macos_application_icon(
                appearance.get("icon_background_color", DEFAULT_ICON_BACKGROUND),
                icon_text,
            )

        window.events.before_show += apply_native_appearance
    webview.start(debug=not settings.release_mode)
    try:
        preferences = PreferenceStore(settings).load()
        preferences["window"] = {
            "width": getattr(window, "width", 1180),
            "height": getattr(window, "height", 780),
            "x": getattr(window, "x", None),
            "y": getattr(window, "y", None),
        }
        PreferenceStore(settings).replace(preferences)
    except Exception:
        pass


def _settings_from_arguments(arguments) -> Settings:
    values = {}
    if arguments.host:
        values["host"] = arguments.host
    if arguments.port is not None:
        values["port"] = arguments.port
    if arguments.data_dir:
        data_dir = Path(arguments.data_dir).expanduser().resolve()
        values.update(
            data_dir=data_dir,
            database_path=data_dir / "watchtracker.sqlite3",
            backups_dir=data_dir / "backups",
            cache_dir=data_dir / "cache",
            config_dir=data_dir / "config",
            log_dir=data_dir / "logs",
        )
    return Settings(**values)


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
        "command",
        nargs="?",
        choices=(
            "run",
            "backup",
            "restore",
            "migrate-database",
            "setup-owner",
            "server-readiness",
        ),
        default="run",
    )
    parser.add_argument("path", nargs="?", help="database or backup path for restore/migration")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    settings = _settings_from_arguments(arguments)
    if arguments.command != "run":
        service = _command_service(settings)
        if arguments.command == "backup":
            print(service.create().path)
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

    if not arguments.host and settings.access_mode == "local":
        settings.host = "127.0.0.1"
    if (
        settings.access_mode == "local"
        and (settings.release_mode or arguments.smoke_test)
        and arguments.port is None
    ):
        settings.port = 0
    settings.native_actions = bool(
        settings.access_mode == "local" and (settings.release_mode or arguments.desktop)
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
        if url := instance.existing_url():
            webbrowser.open(url)
        raise

    controller = None
    try:
        from watchtracker.app import create_app

        controller = ServerController(create_app(settings), settings.host, settings.port)
        controller.start()
        instance.publish(controller.url)
        if arguments.smoke_test:
            print(f"Personal Media Tracker {__version__} healthy at {controller.url}")
            return 0
        use_desktop = settings.access_mode == "local" and (
            arguments.desktop or (is_packaged() and not arguments.browser)
        )
        if arguments.no_open:
            while controller.thread.is_alive():
                controller.thread.join(0.25)
        elif use_desktop:
            _run_webview(controller, settings)
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
