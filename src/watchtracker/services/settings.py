from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from pathlib import Path


class SettingsWriteError(RuntimeError):
    pass


def persist_env_value(path: Path, key: str, value: str | None) -> None:
    """Atomically set or remove one .env value while preserving unrelated settings."""
    if not key or any(
        character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for character in key
    ):
        raise ValueError("invalid environment key")
    if value is not None and ("\n" in value or "\r" in value):
        raise ValueError("environment values must be a single line")
    try:
        existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        prefix = f"{key}="
        output: list[str] = []
        replaced = False
        for line in existing:
            if line.startswith(prefix):
                if value is not None and not replaced:
                    output.append(f"{prefix}{value}")
                    replaced = True
                continue
            output.append(line)
        if value is not None and not replaced:
            output.append(f"{prefix}{value}")

        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".watchtracker-env-", dir=path.parent
        )
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
                temporary.write("\n".join(output) + ("\n" if output else ""))
            os.replace(temporary_name, path)
            os.chmod(path, 0o600)
        except Exception:
            with suppress(OSError):
                os.unlink(temporary_name)
            raise
    except (OSError, ValueError) as exc:
        raise SettingsWriteError("Could not save the local settings file.") from exc
