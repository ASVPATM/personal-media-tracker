from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import watchtracker.tailscale_access as tailscale_access
from watchtracker.tailscale_access import TailscaleAccessError, TailscaleAccessManager


def _completed(arguments: tuple[str, ...], payload: dict, returncode: int = 0):
    return subprocess.CompletedProcess(
        ["tailscale", *arguments],
        returncode,
        stdout=json.dumps(payload),
        stderr="",
    )


def test_macos_finder_launch_forces_tailscale_cli_mode(monkeypatch):
    manager = TailscaleAccessManager(executable=Path("/fake/Tailscale"))
    captured: dict[str, object] = {}

    def run(command, **options):
        captured["command"] = command
        captured["environment"] = options["env"]
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    monkeypatch.setattr(tailscale_access.sys, "platform", "darwin")
    monkeypatch.delenv("TERM", raising=False)
    monkeypatch.setattr(tailscale_access.subprocess, "run", run)

    manager._run("status", "--json")

    assert captured["command"] == ["/fake/Tailscale", "status", "--json"]
    assert captured["environment"]["TERM"] == "dumb"


def test_managed_tailscale_route_uses_private_serve_without_funnel(monkeypatch):
    manager = TailscaleAccessManager(executable=Path("/fake/tailscale"))
    route = {"active": False}
    calls: list[tuple[str, ...]] = []

    def run(*arguments: str, timeout: float = 12.0):
        del timeout
        calls.append(arguments)
        if arguments == ("status", "--json"):
            return _completed(
                arguments,
                {
                    "BackendState": "Running",
                    "Self": {"DNSName": "media.private.ts.net."},
                },
            )
        if arguments == ("serve", "status", "--json"):
            payload = (
                {
                    "Web": {
                        "media.private.ts.net:443": {
                            "Handlers": {"/": {"Proxy": "http://127.0.0.1:8000"}}
                        }
                    }
                }
                if route["active"]
                else {}
            )
            return _completed(arguments, payload)
        if arguments == ("serve", "--bg", "http://127.0.0.1:8000"):
            route["active"] = True
            return _completed(arguments, {})
        raise AssertionError(arguments)

    monkeypatch.setattr(manager, "_run", run)
    snapshot = manager.ensure_route(port=8000)

    assert snapshot.access_url == "https://media.private.ts.net"
    assert snapshot.route_active is True
    assert any(call[:2] == ("serve", "--bg") for call in calls)
    assert all("funnel" not in call for arguments in calls for call in arguments)


def test_managed_tailscale_refuses_to_replace_another_serve_route(monkeypatch):
    manager = TailscaleAccessManager(executable=Path("/fake/tailscale"))

    def run(*arguments: str, timeout: float = 12.0):
        del timeout
        if arguments == ("status", "--json"):
            return _completed(
                arguments,
                {
                    "BackendState": "Running",
                    "Self": {"DNSName": "media.private.ts.net."},
                },
            )
        if arguments == ("serve", "status", "--json"):
            return _completed(
                arguments,
                {
                    "Web": {
                        "media.private.ts.net:443": {
                            "Handlers": {"/": {"Proxy": "http://127.0.0.1:9000"}}
                        }
                    }
                },
            )
        raise AssertionError("A conflicting route must not be changed")

    monkeypatch.setattr(manager, "_run", run)
    with pytest.raises(TailscaleAccessError, match="another local service"):
        manager.ensure_route(port=8000)


def test_managed_tailscale_updates_its_previous_random_port(monkeypatch):
    manager = TailscaleAccessManager(executable=Path("/fake/tailscale"))
    route_port = {"value": 56_330}

    def run(*arguments: str, timeout: float = 12.0):
        del timeout
        if arguments == ("status", "--json"):
            return _completed(
                arguments,
                {
                    "BackendState": "Running",
                    "Self": {"DNSName": "media.private.ts.net."},
                },
            )
        if arguments == ("serve", "status", "--json"):
            return _completed(
                arguments,
                {
                    "Web": {
                        "media.private.ts.net:443": {
                            "Handlers": {
                                "/": {"Proxy": f"http://127.0.0.1:{route_port['value']}"}
                            }
                        }
                    }
                },
            )
        if arguments == ("serve", "--bg", "http://127.0.0.1:8000"):
            route_port["value"] = 8000
            return _completed(arguments, {})
        raise AssertionError(arguments)

    monkeypatch.setattr(manager, "_run", run)
    snapshot = manager.ensure_route(port=8000, previous_managed_port=56_330)

    assert snapshot.route_active is True
    assert route_port["value"] == 8000
