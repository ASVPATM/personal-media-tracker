from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


class NativeActionError(RuntimeError):
    pass


def open_local_path(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        elif os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except (OSError, subprocess.SubprocessError) as exc:
        raise NativeActionError("The folder could not be opened automatically.") from exc
