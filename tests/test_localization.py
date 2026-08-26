from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

STATIC_ROOT = Path(__file__).parents[1] / "src" / "watchtracker" / "static"
CATALOG_KEY = re.compile(r'^\s*"((?:[^"\\]|\\.)*)"\s*:', re.MULTILINE)


def _catalog_keys(source: str) -> set[str]:
    return {json.loads(f'"{value}"') for value in CATALOG_KEY.findall(source)}


class _InterfaceCopyParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._stack: list[tuple[str, bool]] = []
        self.values: set[str] = set()

    @property
    def _excluded(self) -> bool:
        return any(excluded for _, excluded in self._stack)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        excluded = tag in {"code", "path", "script", "style", "svg", "use"} or (
            attributes.get("translate") == "no"
        )
        self._stack.append((tag, excluded))
        if self._excluded:
            return
        for name in ("aria-label", "data-tip", "placeholder", "title"):
            if value := attributes.get(name):
                self.values.add(" ".join(value.split()))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self._stack.pop()

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                del self._stack[index:]
                break

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if (
            value
            and not self._excluded
            and not re.fullmatch(r"[\d\s.,:;!?+−—–/()%·×|]+", value)
        ):
            self.values.add(value)


def test_release_ready_french_covers_static_shell_and_literal_copy() -> None:
    javascript = (STATIC_ROOT / "app.js").read_text()
    french_pack = (STATIC_ROOT / "locales" / "fr.js").read_text()
    legacy_french = javascript.split("const frenchText = {", 1)[1].split(
        "\n};\nObject.assign(frenchText", 1
    )[0]
    french_keys = _catalog_keys(legacy_french) | _catalog_keys(french_pack)

    parser = _InterfaceCopyParser()
    parser.feed((STATIC_ROOT / "index.html").read_text())
    assert parser.values - french_keys == set()

    translated_literals = {
        match.group(2)
        for match in re.finditer(
            r"translatedText\(\s*([\"'])(.*?)\1\s*\)", javascript, re.DOTALL
        )
        if "\n" not in match.group(2)
    }
    assert translated_literals - french_keys == set()

    generated_workflow_copy = {
        "Delete",
        "Delete viewing?",
        "Show provider summary",
        "Mark unwatched",
        "Untitled episode",
        "Scripted",
        "Reality",
        "Imported file",
        "Provider default",
        "Text-free / other",
        "Tracker library",
        "Included",
        "Keep current",
        "Distinct library titles with a title or episode viewing in the selected scope.",
    }
    assert generated_workflow_copy - french_keys == set()
    assert "window.PMT_IMPORT_PROMPTS.fr" in french_pack
    assert "Convertis ma liste de médias" in french_pack


def test_simplified_chinese_remains_explicitly_beta() -> None:
    html = (STATIC_ROOT / "index.html").read_text()
    chinese_pack = (STATIC_ROOT / "locales" / "zh-CN.js").read_text()
    assert '<option value="fr">Français</option>' in html
    assert '<option value="zh-CN">简体中文（测试版）</option>' in html
    assert chinese_pack.startswith("// Simplified Chinese beta locale.")
