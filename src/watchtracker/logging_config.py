from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from watchtracker.config import Settings


def configure_logging(settings: Settings) -> None:
    """Configure bounded local diagnostics without enabling remote telemetry."""
    settings.resolved_log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(getattr(logging, settings.log_level))
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    if not any(getattr(handler, "_watchtracker_console", False) for handler in root.handlers):
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        console._watchtracker_console = True  # type: ignore[attr-defined]
        root.addHandler(console)

    log_path = settings.resolved_log_dir / "watchtracker.log"
    matching = [
        handler
        for handler in root.handlers
        if getattr(handler, "baseFilename", None) == str(log_path)
    ]
    if not matching:
        rotating = RotatingFileHandler(
            log_path,
            maxBytes=2 * 1024 * 1024,
            backupCount=4,
            encoding="utf-8",
        )
        rotating.setFormatter(formatter)
        root.addHandler(rotating)
