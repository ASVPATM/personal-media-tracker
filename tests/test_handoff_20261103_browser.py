"""Real browser coverage for detail panes, cancellation and native modal chrome."""

from uuid import uuid4

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect
from test_collection_design import _card, _seed, _switch
from test_collections_browser import browser_server as browser_server
from test_collections_browser import edit_panel, edit_tracks
from test_collections_browser import page as page

pytestmark = pytest.mark.parametrize("page", ["chromium", "webkit"], indirect=True)


@pytest.mark.parametrize("domain", ["music", "books"])
def test_cancel_catalog_preserves_prior_pending_personal_edits(page, browser_server, domain):
    row = _seed(page, browser_server, domain, year=2001)
    _switch(page, domain)
    _card(page, row).locator("[data-open-music]").click()
    expect(page.locator("#music-edit-state")).to_be_empty()
    edit_panel(page, "notes")
    page.locator('#music-form [name="notes"]').fill("Pending note before catalog edit")
    edit_panel(page, "catalog")
    page.locator("#music-title").fill("Discard this title")
    page.locator('#music-form [name="year"]').fill("1999")
    page.locator("#music-cancel-catalog").click()
    expect(page.locator('[data-collection-tab="notes"]')).to_have_attribute(
        "aria-selected", "true"
    )
    expect(page.locator('#music-form [name="notes"]')).to_have_value(
        "Pending note before catalog edit"
    )
    expect(page.locator("#music-title")).to_have_value(row["title"])
    expect(page.locator('#music-form [name="year"]')).to_have_value("2001")
    page.locator("#music-save").click()
    expect(page.locator("#music-editor")).to_be_hidden()
    route = "albums" if domain == "music" else "entries"
    saved = page.request.get(f"{browser_server}/api/{domain}/{route}/{row['id']}").json()
    assert saved["title"] == row["title"] and saved["year"] == 2001
    assert saved["notes"] == "Pending note before catalog edit"


def test_connected_tracklist_stable_tabs_and_cancel_then_save(page, browser_server):
    tracks = [
        {
            "id": str(uuid4()),
            "position": i,
            "disc": 1,
            "title": f"Track {i}",
            "duration_ms": 121234,
            "recording_id": str(uuid4()),
        }
        for i in range(1, 4)
    ]
    row = _seed(page, browser_server, "music", tracks=tracks)
    _switch(page, "music")
    _card(page, row).locator("[data-open-music]").click()
    dialog, side = page.locator("#music-editor"), page.locator("#music-track-sidecar")
    dialog.evaluate(
        "async e => { await new Promise(requestAnimationFrame); await Promise.allSettled(e.getAnimations().map(a => a.finished)); }"
    )
    bounds = dialog.bounding_box()
    tabs = page.locator("#music-editor .dialog-tabs").bounding_box()
    main = page.locator("#music-editor .entry-dialog-content").bounding_box()
    assert side.bounding_box()["x"] > main["x"] + main["width"]
    assert side.bounding_box()["height"] < bounds["height"] * 0.65
    for tab in ("notes", "genres", "metadata", "details"):
        edit_panel(page, tab)
        expect(side).to_be_visible()
        assert abs(dialog.bounding_box()["height"] - bounds["height"]) < 2
        assert (
            abs(page.locator("#music-editor .dialog-tabs").bounding_box()["y"] - tabs["y"]) < 2
        )
    page.locator('#music-form [name="rating"]').fill("9")
    edit_tracks(page)
    page.locator(".track-title").first.fill("Discard me")
    page.locator(".track-remove").last.click()
    page.locator(".track-edit-actions summary").hover()
    page.locator("#music-cancel-tracks").click()
    expect(page.locator("#music-track-preview tbody tr")).to_have_count(3)
    edit_tracks(page)
    page.locator(".track-title").first.fill("Keep me")
    page.locator(".track-edit-actions summary").hover()
    page.locator("#music-done-tracks").click()
    expect(page.locator("#music-track-preview")).to_contain_text("Keep me")
    page.locator("#music-save").click()
    expect(dialog).to_be_hidden()
    saved = page.request.get(f"{browser_server}/api/music/albums/{row['id']}").json()
    assert saved["rating"] == 9 and saved["tracks"][0]["title"] == "Keep me"
    assert [t["id"] for t in saved["tracks"]] == [t["id"] for t in tracks]
    assert all(t["duration_ms"] == 121234 for t in saved["tracks"])


def test_narrow_details_reach_sidecar_save_and_close(page, browser_server):
    row = _seed(
        page,
        browser_server,
        "music",
        tracks=[{"title": "Long track", "position": 1, "disc": 1}],
    )
    page.set_viewport_size({"width": 390, "height": 844})
    _switch(page, "music")
    _card(page, row).locator("[data-open-music]").click()
    art = page.locator("#music-editor .entry-dialog-art").bounding_box()
    cover = page.locator("#music-editor-cover").bounding_box()
    assert art["height"] >= cover["height"] >= 80
    expect(page.locator("#music-track-sidecar")).to_be_visible()
    page.locator("#music-track-sidecar").scroll_into_view_if_needed()
    assert page.locator("#music-editor").evaluate("e => e.scrollWidth <= e.clientWidth + 1")
    edit_panel(page, "notes")
    page.locator('#music-form [name="notes"]').fill("Narrow window edit")
    page.locator("#music-save").click()
    expect(page.locator("#music-editor")).to_be_hidden()


def test_new_metadata_replaces_the_catalog_cancel_context(page, browser_server):
    row = _seed(page, browser_server, "music")
    provider_id = str(uuid4())
    replacement = {
        "provider_id": provider_id,
        "title": f"New provider title {uuid4()}",
        "artist": "New creator",
        "year": 2005,
        "tracks": [],
    }
    page.route(
        "**/api/music/search?*", lambda route: route.fulfill(json={"results": [replacement]})
    )
    page.route(
        f"**/api/music/metadata/{provider_id}", lambda route: route.fulfill(json=replacement)
    )
    _switch(page, "music")
    _card(page, row).locator("[data-open-music]").click()
    edit_panel(page, "catalog")
    page.locator("#music-title").fill("Unfinished old catalog edit")
    edit_panel(page, "metadata")
    page.locator("#music-find-metadata").click()
    page.locator('#music-search-form button[type="submit"]').click()
    page.locator("[data-music-result]").click()
    expect(page.locator("#music-search-dialog")).to_be_hidden()
    # Applying provider metadata ends the old manual edit context. Catalog
    # fields become read-only; its abandoned title must never be restored.
    expect(page.locator("#music-edit-catalog")).to_be_hidden()
    expect(page.locator("#music-title")).to_be_disabled()
    expect(page.locator("#music-title")).to_have_value(replacement["title"])
    page.locator("#music-save").click()
    expect(page.locator("#music-editor")).to_be_hidden()
    saved = page.request.get(f"{browser_server}/api/music/albums/{row['id']}").json()
    assert saved["title"] == replacement["title"] and saved["provider_id"] == provider_id


def test_sidebar_circles_match_in_expanded_and_minimized_modes(page):
    for minimized in (False, True):
        if minimized:
            page.locator("#toggle-sidebar").click()
        rects = page.locator(
            "#open-notifications, #open-recommendations, #open-settings"
        ).evaluate_all(
            "nodes => nodes.filter(e => e.getClientRects().length).map(e => { const r=e.getBoundingClientRect(); return [r.width,r.height,getComputedStyle(e,'::before').content]; })"
        )
        assert len(rects) == 3
        assert max(r[0] for r in rects) - min(r[0] for r in rects) < 1
        assert all(abs(r[0] - r[1]) < 1 for r in rects)
        assert all(r[2] == "none" for r in rects)


def test_regular_server_users_keep_collection_metadata_settings(page):
    page.evaluate("state.currentUser = {role: 'member'}; configureSettingsForAccount();")
    page.locator("#open-settings").click()
    for domain in ("screen", "music", "books"):
        expect(page.locator(f'[data-settings-tab="{domain}"]')).to_be_visible()


def test_beta_label_remains_readable_with_custom_colors(page):
    ratios = page.evaluate("""() => {
      const canvas = document.createElement('canvas'); canvas.width = canvas.height = 1;
      const ctx = canvas.getContext('2d');
      const luminance = color => {
        ctx.fillStyle = color; ctx.fillRect(0, 0, 1, 1);
        const rgb = [...ctx.getImageData(0, 0, 1, 1).data].slice(0, 3).map(v => {
          v /= 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4;
        });
        return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
      };
      const ratios = [];
      for (const theme of ['light', 'dark', 'system']) {
        applyTheme(theme);
        for (const mode of ['adaptive', 'full']) {
          for (const color of ['#000000', '#ffffff', '#808080', '#7777aa', '#ff0000', '#00ff00']) {
            applyAccent('forest', color); applyBackgroundColor(color, 100, mode);
            const style = getComputedStyle(document.querySelector('.recommendation-beta-chip'));
            const values = [luminance(style.color), luminance(style.backgroundColor)].sort((a,b) => a-b);
            ratios.push((values[1] + .05) / (values[0] + .05));
          }
        }
      }
      return ratios;
    }""")
    assert min(ratios) >= 4.5


def test_settings_alignment_retired_integrations_and_native_backdrop(page, browser_server):
    page.goto(browser_server + "/?desktop=macos", wait_until="networkidle")
    page.locator("#open-settings").click()
    expect(page.locator("#settings-view")).to_be_visible()
    expect(page.locator("html")).not_to_have_attribute("data-native-dialog-open", "true")
    assert (
        page.locator(".native-titlebar-drag-main").evaluate("e => getComputedStyle(e).zIndex")
        == "10000"
    )
    reset, save = (
        page.locator("#reset-general-settings").bounding_box(),
        page.locator("#save-general-settings").bounding_box(),
    )
    assert abs(reset["y"] - save["y"]) < 2 and save["x"] > reset["x"]
    for domain in ("screen", "music", "books"):
        page.locator(f'[data-settings-tab="{domain}"]').click()
        expect(page.locator("#settings-view button", has_text="Integrations")).to_have_count(0)
    page.locator('[data-settings-tab="screen"]').click()
    page.locator('[data-screen-settings-tab="metadata"]').click()
    expect(page.locator("#tmdb-token")).to_be_visible()
    page.locator('[data-settings-tab="data"]').click()
    assert (
        page.locator(".data-summary").bounding_box()["y"]
        < page.locator(".collection-transfer").bounding_box()["y"]
    )
    page.locator(".brand").click()
    page.locator("#quick-add-shortcut").click()
    expect(page.locator("#quick-add-dialog")).to_be_visible()
    assert page.evaluate("getComputedStyle(document.body, '::before').top") == "0px"
    close = page.locator("#quick-add-dialog .dialog-close")
    rect, svg = close.bounding_box(), close.locator("svg").bounding_box()
    assert abs(rect["x"] + rect["width"] / 2 - svg["x"] - svg["width"] / 2) < 1
    assert abs(rect["y"] + rect["height"] / 2 - svg["y"] - svg["height"] / 2) < 1
    close.click()
    expect(page.locator("html")).not_to_have_attribute("data-native-dialog-open", "true")


def test_screen_series_sidecar_loads_without_releases_tab(page, browser_server):
    provider_id = "synthetic-series-" + str(uuid4())
    response = page.request.post(
        f"{browser_server}/api/entries/manual",
        data={
            "canonical_title": f"Synthetic series {uuid4()}",
            "media_type": "tv",
            "status": "watching",
            "provider_source": "tmdb_tv",
            "provider_id": provider_id,
            "tmdb_tv_id": provider_id,
        },
    )
    assert response.ok, response.text()
    identifier = response.json()["entry"]["id"]
    page.reload(wait_until="networkidle")
    page.locator(f'[data-entry="{identifier}"] [data-details]').click()
    expect(page.locator('[data-entry-tab="releases"]')).to_have_count(0)
    expect(page.locator("#entry-episodes-sidecar")).to_be_visible()
    expect(page.locator("#follow-series")).to_be_visible()
    page.locator('[data-entry-tab="notes"]').click()
    expect(page.locator("#follow-series")).to_be_visible()
    page.locator("#follow-series").click()
    expect(page.locator("#series-release-panel")).to_contain_text("Season 1")
