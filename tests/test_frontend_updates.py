from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

import pytest

from watchtracker.frontend import frontend_url, load_frontend


def test_ui_document_never_reuses_a_stale_page_and_every_asset_resolves(client):
    response = client.get("/?desktop=macos&ui=previous-build")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["expires"] == "0"
    assert response.headers["x-pmt-ui-build"] == load_frontend().revision
    assets = re.findall(r'(?:src|href)="(/static/[^\"]+)"', response.text)
    assert assets
    for url in assets:
        assert re.search(r"\?v=[0-9a-f]{16}$", url)
        asset = client.get(url)
        assert asset.status_code == 200, url
        assert asset.headers["cache-control"] == "no-cache"
        # Conditional reuse is allowed, without ever treating stale UI as fresh.
        cached = client.get(url, headers={"If-None-Match": asset.headers["etag"]})
        assert cached.status_code == 304
        assert cached.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("changed", ["index.html", "app.js", "styles.css", "locales/fr.js"])
def test_same_version_rebuild_changes_document_identity_and_changed_asset_url(
    tmp_path, changed
):
    (tmp_path / "locales").mkdir()
    html = (
        '<link href="/static/styles.css?v=3.2.0" rel="stylesheet">'
        '<script src="/static/locales/fr.js?v=3.2.0"></script>'
        '<script src="/static/app.js?v=3.2.0"></script>'
    )
    (tmp_path / "index.html").write_text(html)
    for name in ["app.js", "styles.css", "locales/fr.js"]:
        (tmp_path / name).write_text("old")
    before = load_frontend(tmp_path)
    # Same length, same public version, and even the same filesystem mtime:
    # validators based only on size/time would miss this update.
    import os

    path = tmp_path / changed
    modified = path.stat().st_mtime_ns
    path.write_text(html + "<!-- updated -->" if changed == "index.html" else "new")
    os.utime(path, ns=(modified, modified))
    after = load_frontend(tmp_path)
    assert after.revision != before.revision
    assert after.html != before.html
    assert frontend_url(
        "http://127.0.0.1:8000/?desktop=macos", before.revision
    ) != frontend_url("http://127.0.0.1:8000/?desktop=macos", after.revision)
    assert after == load_frontend(tmp_path)


def test_start_url_preserves_navigation_and_native_session_fragment():
    url = frontend_url(
        "http://127.0.0.1:8000/?desktop=macos&mode=music&ui=old#native-host=token", "new"
    )
    parsed = urlsplit(url)
    assert parsed.netloc == "127.0.0.1:8000"
    assert parse_qs(parsed.query) == {"desktop": ["macos"], "mode": ["music"], "ui": ["new"]}
    assert parsed.fragment == "native-host=token"


def test_frontend_hashing_rejects_asset_paths_outside_bundle(tmp_path):
    (tmp_path / "index.html").write_text('<script src="/static/../private.js"></script>')
    with pytest.raises(ValueError, match="Invalid bundled frontend asset"):
        load_frontend(tmp_path)
