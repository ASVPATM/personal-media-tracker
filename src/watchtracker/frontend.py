"""Give the application document and its assets an identity independent of HTTP age."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

STATIC_DIR = Path(__file__).with_name("static")
_ASSET_REFERENCE = re.compile(
    r"""(?P<prefix>\b(?:src|href)=["'])(?P<path>/static/[^"'?#]+)(?:\?[^"']*)?(?P<quote>["'])"""
)


@dataclass(frozen=True)
class FrontendDocument:
    html: str
    revision: str


def load_frontend(static_dir: Path = STATIC_DIR) -> FrontendDocument:
    """Hash referenced assets so even a rebuild of the same release gets fresh UI."""
    root = static_dir.resolve()

    def reference(match: re.Match) -> str:
        path = (root / match["path"].removeprefix("/static/")).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(f"Invalid bundled frontend asset: {match['path']}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        return f"{match['prefix']}{match['path']}?v={digest}{match['quote']}"

    html = _ASSET_REFERENCE.sub(reference, (root / "index.html").read_text(encoding="utf-8"))
    return FrontendDocument(html, hashlib.sha256(html.encode("utf-8")).hexdigest()[:16])


def frontend_url(url: str, revision: str | None = None) -> str:
    """Bypass a previously cached entry document without clearing cookies or data."""
    parsed = urlsplit(url)
    query = [(key, value) for key, value in parse_qsl(parsed.query) if key != "ui"]
    query.append(("ui", revision or load_frontend().revision))
    return urlunsplit(parsed._replace(query=urlencode(query)))
