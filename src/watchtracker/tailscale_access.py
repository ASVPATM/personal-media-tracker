"""Small, fail-closed adapter for account-free personal Tailscale access.

This is deliberately separate from PMT Server.  It exposes the one local library
through Tailscale Serve while the desktop application is running; it never creates
accounts, changes the database, or enables public Funnel access.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class TailscaleAccessError(RuntimeError):
    pass


@dataclass(frozen=True)
class TailscaleSnapshot:
    installed: bool
    connected: bool
    dns_name: str | None
    access_url: str | None
    route_active: bool
    route_conflict: bool


def tailscale_executable() -> Path | None:
    discovered = shutil.which("tailscale")
    candidates = [
        Path(discovered) if discovered else None,
        Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale"),
    ]
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate
    return None


def _contains_value(value: Any, expected: str) -> bool:
    if isinstance(value, str):
        return value.rstrip("/") == expected.rstrip("/")
    if isinstance(value, dict):
        return any(_contains_value(item, expected) for item in value.values())
    if isinstance(value, list):
        return any(_contains_value(item, expected) for item in value)
    return False


def _proxy_targets(value: Any) -> set[str]:
    targets: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key.casefold() == "proxy" and isinstance(item, str):
                targets.add(item.rstrip("/"))
            else:
                targets.update(_proxy_targets(item))
    elif isinstance(value, list):
        for item in value:
            targets.update(_proxy_targets(item))
    return targets


class TailscaleAccessManager:
    def __init__(self, *, executable: Path | None = None):
        self.executable = executable or tailscale_executable()

    def _run(self, *arguments: str, timeout: float = 12.0) -> subprocess.CompletedProcess[str]:
        if self.executable is None:
            raise TailscaleAccessError("Install Tailscale on this computer first.")
        environment = os.environ.copy()
        if sys.platform == "darwin":
            # The App Store Tailscale executable is both its GUI entry point and
            # its CLI. Finder-launched applications do not normally inherit a
            # terminal marker; without one, `Tailscale status --json` attempts
            # to start the GUI and prints a non-JSON CLIError with exit code 0.
            # Supplying a harmless terminal type selects the documented CLI
            # path without changing Tailscale, its network state, or its socket.
            environment.setdefault("TERM", "dumb")
        try:
            return subprocess.run(
                [str(self.executable), *arguments],
                check=False,
                capture_output=True,
                env=environment,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TailscaleAccessError("Tailscale did not respond on this computer.") from exc

    def _json(self, *arguments: str) -> dict[str, Any]:
        result = self._run(*arguments)
        if result.returncode != 0:
            raise TailscaleAccessError(
                "Open Tailscale and confirm that this computer is connected."
            )
        try:
            payload = json.loads(result.stdout or "{}")
        except (TypeError, ValueError) as exc:
            raise TailscaleAccessError("Tailscale returned an unreadable status.") from exc
        if not isinstance(payload, dict):
            raise TailscaleAccessError("Tailscale returned an unreadable status.")
        return payload

    def snapshot(self, *, port: int) -> TailscaleSnapshot:
        if self.executable is None:
            return TailscaleSnapshot(False, False, None, None, False, False)
        try:
            status = self._json("status", "--json")
        except TailscaleAccessError:
            return TailscaleSnapshot(True, False, None, None, False, False)
        self_status = status.get("Self") if isinstance(status.get("Self"), dict) else {}
        dns_name = str(self_status.get("DNSName") or "").strip().rstrip(".").casefold()
        connected = status.get("BackendState") == "Running" and bool(dns_name)
        access_url = f"https://{dns_name}" if connected else None
        try:
            serve = self._json("serve", "status", "--json")
        except TailscaleAccessError:
            serve = {}
        target = f"http://127.0.0.1:{port}"
        route_active = _contains_value(serve, target)
        targets = _proxy_targets(serve)
        route_conflict = bool(serve) and (
            not route_active or bool(targets - {target.rstrip("/")})
        )
        return TailscaleSnapshot(
            True,
            connected,
            dns_name or None,
            access_url,
            route_active,
            route_conflict,
        )

    def ensure_route(
        self, *, port: int, previous_managed_port: int | None = None
    ) -> TailscaleSnapshot:
        snapshot = self.snapshot(port=port)
        if not snapshot.connected:
            raise TailscaleAccessError(
                "Open Tailscale and confirm that this computer is connected."
            )
        if snapshot.route_conflict:
            previous = (
                self.snapshot(port=previous_managed_port)
                if previous_managed_port and previous_managed_port != port
                else None
            )
            if previous is None or not previous.route_active or previous.route_conflict:
                raise TailscaleAccessError(
                    "Tailscale Serve is already being used by another local service. "
                    "PMT left that route unchanged."
                )
            # PMT deliberately owned this exact prior loopback target. Re-running
            # Serve updates the root proxy after a one-time random-to-stable-port
            # restart without resetting unrelated Tailscale configuration.
            snapshot = TailscaleSnapshot(
                snapshot.installed,
                snapshot.connected,
                snapshot.dns_name,
                snapshot.access_url,
                False,
                False,
            )
        if not snapshot.route_active:
            result = self._run("serve", "--bg", f"http://127.0.0.1:{port}", timeout=30)
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "").strip()
                raise TailscaleAccessError(
                    detail or "Tailscale could not prepare the private PMT link."
                )
        return self.snapshot(port=port)

    def remove_managed_route(self, *, port: int) -> None:
        snapshot = self.snapshot(port=port)
        if not snapshot.route_active:
            return
        if snapshot.route_conflict:
            raise TailscaleAccessError(
                "PMT will not reset Tailscale Serve while another route is configured."
            )
        result = self._run("serve", "reset")
        if result.returncode != 0:
            raise TailscaleAccessError("Tailscale could not remove the private PMT link.")


def supports_managed_tailscale() -> bool:
    return sys.platform in {"darwin", "linux"}
