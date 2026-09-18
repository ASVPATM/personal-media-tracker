"""Focused browser regressions for preservation while collection edits are pending."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")
from test_collections_browser import (  # noqa: E402
    browser_server as browser_server,
)
from test_collections_browser import edit_panel, edit_tracks  # noqa: E402
from test_collections_browser import page as page  # noqa: E402


def _seed(page, server, domain, **values):
    route = f"{server}/api/{domain}/{'albums' if domain == 'music' else 'entries'}"
    body = {
        "title": f"Edit safety {uuid4()}",
        "artist" if domain == "music" else "author": "Fixture creator",
        "notes": "Private notes must stay unchanged",
        "rating": 8.5,
        "status": "collected",
        **values,
    }
    response = page.request.post(route, data=body)
    assert response.ok, response.text()
    identifier = response.json()["id"]
    return page.request.get(f"{route}/{identifier}").json()


def _open(page, domain, identifier):
    page.locator(f'button[data-workspace="{domain}"]').click()
    playwright_api.expect(page.locator("#music-content")).to_have_attribute(
        "aria-busy", "false"
    )
    page.locator(f'[data-music-id="{identifier}"] [data-open-music]').click()
    playwright_api.expect(page.locator("#music-save")).to_be_disabled()


@pytest.mark.parametrize("edited_field", ["title", "duration"])
def test_track_text_or_duration_edit_keeps_provider_positions(
    page, browser_server, edited_field
):
    tracks = [
        {
            "id": str(uuid4()),
            "disc": disc,
            "position": position,
            "title": f"Original track {index}",
            "artist": "Track artist",
            "duration_ms": milliseconds,
            "recording_id": str(uuid4()),
        }
        for index, (disc, position, milliseconds) in enumerate(
            [(1, 7, 123456), (1, 2, 98765), (2, 4, None)], 1
        )
    ]
    row = _seed(page, browser_server, "music", tracks=tracks)
    _open(page, "music", row["id"])
    edit_tracks(page)
    controls = page.locator("#music-track-rows tr")
    assert controls.locator(".collection-track-number").all_text_contents() == ["7", "2", "4"]
    if edited_field == "title":
        controls.nth(0).locator(".track-title").fill("Corrected title")
        controls.nth(1).locator(".music-track-artist").fill("Corrected artist")
    else:
        controls.nth(0).locator(".track-duration").fill("3:45")
    assert controls.locator(".collection-track-number").all_text_contents() == ["7", "2", "4"]
    page.locator("#music-save").click()
    playwright_api.expect(page.locator("#music-editor")).to_be_hidden()
    saved = page.request.get(f"{browser_server}/api/music/albums/{row['id']}").json()
    for index, track in enumerate(saved["tracks"]):
        assert (track["disc"], track["position"], track["id"], track["recording_id"]) == (
            tracks[index]["disc"],
            tracks[index]["position"],
            tracks[index]["id"],
            tracks[index]["recording_id"],
        )
        expected_duration = (
            225000
            if edited_field == "duration" and index == 0
            else tracks[index]["duration_ms"]
        )
        assert track["duration_ms"] == expected_duration
    assert saved["tracks"][0]["title"] == (
        "Corrected title" if edited_field == "title" else tracks[0]["title"]
    )
    assert saved["notes"] == row["notes"] and saved["status"] == "collected"


@pytest.mark.parametrize("domain", ["music", "books"])
def test_source_labels_reflect_pending_metadata_not_stale_stored_row(
    page, browser_server, domain
):
    old_id = str(uuid4()) if domain == "music" else "OL918271M"
    new_id = str(uuid4()) if domain == "music" else "OL918272M"
    row = _seed(
        page,
        browser_server,
        domain,
        provider_id=old_id,
        genres=["Original obsolete label"],
        subgenres=["Personal classification"],
    )
    replacement = {
        "provider_id": new_id,
        "title": row["title"],
        "artist" if domain == "music" else "author": "Replacement provider creator",
        "release_type" if domain == "music" else "book_format": "album"
        if domain == "music"
        else "book",
        "genres": ["New provider genre, including a comma"],
        "subgenres": [],
        "tracks": [],
        "year": 2024,
    }
    page.route(
        f"**/api/{domain}/search?*",
        lambda route: route.fulfill(json={"results": [replacement]}),
    )
    page.route(
        f"**/api/{domain}/metadata/{new_id}", lambda route: route.fulfill(json=replacement)
    )
    _open(page, domain, row["id"])
    edit_panel(page, "metadata")
    page.locator("#music-find-metadata").click()
    page.locator('#music-search-form button[type="submit"]').click()
    page.locator(f'[data-music-result="{new_id}"]').click()
    playwright_api.expect(page.locator("#music-search-dialog")).to_be_hidden()
    edit_panel(page, "metadata")
    page.locator("#music-panel-metadata summary", has_text="Original source labels").click()
    labels = page.locator("#music-raw-provider-terms")
    playwright_api.expect(labels).to_contain_text(replacement["genres"][0])
    playwright_api.expect(labels).not_to_contain_text("Original obsolete label")
    playwright_api.expect(labels).to_contain_text("Personal classification")
    route = f"{browser_server}/api/{domain}/{'albums' if domain == 'music' else 'entries'}/{row['id']}"
    assert page.request.get(route).json() == row, (
        "Metadata selection must remain a draft until saved."
    )
    page.locator("#music-save").click()
    playwright_api.expect(page.locator("#music-editor")).to_be_hidden()
    saved = page.request.get(route).json()
    assert saved["provider_id"] == new_id and saved["genres"] == replacement["genres"]
    assert saved["subgenres"] == row["subgenres"]
    assert saved["notes"] == row["notes"] and saved["status"] == "collected"


def _controlled_imports(page, hold_saves=False):
    page.evaluate(
        r"""holdSaves => {
          const original = window.api;
          const state = window.editSafetyImports = {previews:{}, saves:{}, submitted:[]};
          window.api = (path, options = {}) => {
            if (/^\/api\/(music|books)\/import(?:\/preview)?$/.test(path)) {
              const payload = JSON.parse(options.body);
              const title = (payload.document.albums || payload.document.books)[0].title;
              if (path.endsWith('/preview')) return new Promise(resolve => {
                state.previews[title] = {resolve, payload};
              });
              state.submitted.push({path, payload});
              if (holdSaves) return new Promise(resolve => { state.saves[title] = {resolve}; });
              return Promise.resolve({new_albums:1, new_books:1, skipped:0, lists:0});
            }
            return original(path, options);
          };
        }""",
        hold_saves,
    )
    page.locator("#open-settings").click()
    page.locator('[data-settings-tab="data"]').click()


def _choose_import(page, title, domain="music"):
    if page.locator("#collection-import-dialog").evaluate("dialog => dialog.open"):
        page.locator("#collection-import-dialog .dialog-close").click()
    playwright_api.expect(page.locator("#settings-dialog")).to_be_visible()
    page.locator("#open-import").click()
    page.locator(f'[data-import-domain="{domain}"]').click()
    document = {
        "format": f"pmt-{'music' if domain == 'music' else 'book'}-collection",
        "version": 1,
        "albums" if domain == "music" else "books": [
            {
                "id": str(uuid4()),
                "title": title,
                "artist" if domain == "music" else "author": "Fixture",
            }
        ],
    }
    page.locator("#music-import-file").set_input_files(
        {
            "name": title + ".json",
            "mimeType": "application/json",
            "buffer": json.dumps(document).encode(),
        }
    )
    page.wait_for_function(
        "title => Boolean(window.editSafetyImports.previews[title])", arg=title
    )
    return document


def _resolve_preview(page, title, count):
    page.evaluate(
        "({title, count}) => window.editSafetyImports.previews[title].resolve({sha256:title, new_albums:count, new_books:count, skipped:0, lists:0})",
        {"title": title, "count": count},
    )


def test_late_import_preview_cannot_replace_a_newer_selected_file(page):
    _controlled_imports(page)
    _choose_import(page, "Older-A")
    newer = _choose_import(page, "Newer-B", "books")
    _resolve_preview(page, "Newer-B", 2)
    playwright_api.expect(page.locator("#music-import-status")).to_contain_text("2 new books")
    _resolve_preview(page, "Older-A", 1)
    playwright_api.expect(page.locator("#music-import-status")).to_contain_text("2 new books")
    page.locator("#music-import-confirm").click()
    page.wait_for_function("window.editSafetyImports.submitted.length === 1")
    submitted = page.evaluate("window.editSafetyImports.submitted[0]")
    assert submitted["path"] == "/api/books/import"
    assert submitted["payload"] == {"document": newer, "sha256": "Newer-B"}


def test_import_commit_locks_file_and_close_until_finished_then_allows_next_list(page):
    _controlled_imports(page, hold_saves=True)
    older = _choose_import(page, "Saving-A")
    _resolve_preview(page, "Saving-A", 1)
    page.locator("#music-import-confirm").click()
    page.wait_for_function("Boolean(window.editSafetyImports.saves['Saving-A'])")
    playwright_api.expect(page.locator("#music-import-file")).to_be_disabled()
    playwright_api.expect(
        page.locator("#collection-import-dialog .dialog-close")
    ).to_be_disabled()
    playwright_api.expect(page.locator("#music-import-confirm")).to_be_disabled()
    page.keyboard.press("Escape")
    playwright_api.expect(page.locator("#collection-import-dialog")).to_be_visible()
    page.evaluate("window.editSafetyImports.saves['Saving-A'].resolve({new_albums:1})")
    playwright_api.expect(page.locator("#music-import-confirm")).to_be_hidden()
    playwright_api.expect(page.locator("#music-import-file")).to_be_enabled()
    newer = _choose_import(page, "Waiting-B", "books")
    _resolve_preview(page, "Waiting-B", 2)
    playwright_api.expect(page.locator("#music-import-confirm")).to_be_visible()
    playwright_api.expect(page.locator("#music-import-confirm")).to_be_enabled()
    playwright_api.expect(page.locator("#music-import-status")).to_contain_text("2 new books")
    page.locator("#music-import-confirm").click()
    page.wait_for_function("window.editSafetyImports.submitted.length === 2")
    submitted = page.evaluate("window.editSafetyImports.submitted")
    assert submitted[0]["payload"]["document"] == older
    assert submitted[1]["path"] == "/api/books/import"
    assert submitted[1]["payload"] == {"document": newer, "sha256": "Waiting-B"}
    page.evaluate("window.editSafetyImports.saves['Waiting-B'].resolve({new_books:2})")
    playwright_api.expect(page.locator("#music-import-confirm")).to_be_hidden()
