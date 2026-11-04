"""Save only changed data and paint detail glass consistently from its first frame."""

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect
from test_collection_design import _card, _seed, _switch
from test_collections_browser import browser_server as browser_server
from test_collections_browser import page as page
from test_handoff_20261103_225456_browser import screen_entry
from test_handoff_20261104_glass_browser import open_detail, rgba

pytestmark = pytest.mark.parametrize("page", ["chromium", "webkit"], indirect=True)


def test_screen_save_tracks_actual_changes_and_reverts(page, browser_server):
    row = screen_entry(
        page,
        browser_server,
        media_type="movie",
        personal_rating=8,
        view_count=2,
        user_tags=["quiet", "weekend"],
        notes="Initial note",
        started_date="2023-01-01",
        finished_date="2024-03-01",
        watched_date="2024-03-01",
    )
    dialog, save = page.locator("#entry-dialog"), page.locator("#save-entry")
    writes = []
    page.on(
        "request",
        lambda r: (
            writes.append(r.post_data_json)
            if r.method == "PATCH" and r.url.endswith(f"/api/entries/{row['id']}")
            else None
        ),
    )
    expect(save).to_be_disabled()
    assert float(save.evaluate("e=>getComputedStyle(e).opacity")) < 1
    page.locator("#entry-form").evaluate("form=>form.requestSubmit()")
    expect(dialog).to_be_visible()
    assert writes == []

    for tab, field, changed in [
        ("details", "entry-status", "dropped"),
        ("details", "entry-rating", "9.1"),
        ("details", "entry-count", "3"),
        ("details", "entry-started", "2024-01-01"),
        ("details", "entry-finished", "2024-02-01"),
        ("details", "entry-watched", "2024-02-02"),
        ("notes", "entry-tags", "New tag"),
        ("notes", "entry-notes", "Changed note"),
        ("genres", "entry-genre-add", "Comedy"),
        ("genres", "entry-genre-remove", "Drama"),
        ("genres", "entry-subgenre-add", "Crime"),
        ("genres", "entry-subgenre-remove", "Mystery"),
    ]:
        page.locator(f'[data-entry-tab="{tab}"]').click()
        control = page.locator("#" + field)
        original = control.input_value()
        edit = control.select_option if field == "entry-status" else control.fill
        edit(changed)
        expect(save).to_be_enabled()
        edit(original)
        expect(save).to_be_disabled()

    page.locator('[data-entry-tab="metadata"]').click()
    page.locator("#entry-metadata-query").fill("Different search")
    page.locator("#entry-metadata-type").select_option("anime")
    expect(save).to_be_disabled()  # Search controls are not saved entry data.
    page.locator('[data-entry-tab="details"]').click()
    page.locator("#entry-rating").fill("8.00")
    expect(save).to_be_disabled()
    page.locator('[data-step-for="entry-count"][data-step-direction="1"]').click()
    expect(save).to_be_enabled()
    page.locator('[data-step-for="entry-count"][data-step-direction="-1"]').click()
    expect(save).to_be_disabled()
    favorite = page.locator("#entry-detail-favorite")
    favorite.click()
    expect(save).to_be_enabled()
    favorite.click()
    expect(save).to_be_disabled()
    assert writes == []
    favorite.click()
    save.click()
    expect(dialog).to_be_hidden()
    assert len(writes) == 1
    saved = page.request.get(f"{browser_server}/api/entries/{row['id']}").json()
    assert saved["is_favorite"] and saved["notes"] == "Initial note"
    assert saved["personal_rating"] == 8 and saved["view_count"] == 2
    page.evaluate("id=>openEntry(id)", row["id"])
    expect(save).to_be_disabled()


def test_screen_pending_and_failed_save_preserve_new_edits(page, browser_server):
    row = screen_entry(page, browser_server, media_type="movie")
    endpoint = f"{browser_server}/api/entries/{row['id']}"
    pending = []
    page.route(
        endpoint,
        lambda route: (
            pending.append(route) if route.request.method == "PATCH" else route.continue_()
        ),
    )
    dialog, save = page.locator("#entry-dialog"), page.locator("#save-entry")
    page.locator('[data-entry-tab="notes"]').click()
    notes = page.locator("#entry-notes")
    notes.fill("First draft")
    save.click()
    expect(save).to_be_disabled()
    page.locator("#entry-form").evaluate("form=>form.requestSubmit()")
    assert len(pending) == 1
    notes.fill("Retained draft")
    pending[0].fulfill(status=503, json={"error": {"message": "Temporary save failure"}})
    expect(page.locator("#entry-message")).to_contain_text("Temporary save failure")
    expect(notes).to_have_value("Retained draft")
    expect(save).to_be_enabled()
    save.click()
    expect(save).to_be_disabled()
    assert len(pending) == 2
    notes.fill("A newer unsaved edit")
    pending[1].fulfill(response=pending[1].fetch())
    expect(page.locator("#entry-form")).to_have_attribute("aria-busy", "false")
    expect(dialog).to_be_visible()
    expect(notes).to_have_value("A newer unsaved edit")
    expect(save).to_be_enabled()
    assert page.request.get(endpoint).json()["notes"] == "Retained draft"
    page.unroute(endpoint)
    save.click()
    expect(dialog).to_be_hidden()
    assert page.request.get(endpoint).json()["notes"] == "A newer unsaved edit"


def test_immediate_episode_saves_do_not_mark_tracking_fields_dirty(page, browser_server):
    row = screen_entry(page, browser_server, episode_count=2, personal_rating=8)
    save = page.locator("#save-entry")
    counter = page.locator(".pmt-detail-progress [data-episode-progress]")
    expect(save).to_be_disabled()
    for watched in [1, 2]:
        counter.locator('[data-episode-step="1"]').click()
        expect(counter).to_have_attribute("data-watched", str(watched))
        expect(save).to_be_disabled()
    stored = page.request.get(f"{browser_server}/api/entries/{row['id']}").json()
    expect(page.locator("#entry-status")).to_have_value(stored["status"])
    expect(page.locator("#entry-count")).to_have_value(str(stored["view_count"]))
    page.locator("#entry-rating").fill("9")
    counter.locator('[data-episode-step="-1"]').click()
    expect(counter).to_have_attribute("data-watched", "1")
    expect(page.locator("#entry-rating")).to_have_value("9")
    expect(save).to_be_enabled()
    page.locator("#entry-rating").fill("8")
    expect(save).to_be_disabled()


@pytest.mark.parametrize("domain", ["music", "books"])
def test_collection_save_remains_disabled_when_edits_are_reverted(page, browser_server, domain):
    row = _seed(page, browser_server, domain)
    _switch(page, domain)
    _card(page, row).locator("[data-open-music]").click()
    save = page.locator("#music-save")
    expect(save).to_be_disabled()
    page.locator('[data-collection-tab="notes"]').click()
    notes = page.locator('#music-form [name="notes"]')
    notes.fill("Changed note")
    expect(save).to_be_enabled()
    notes.fill(row["notes"])
    expect(save).to_be_disabled()
    page.locator("#music-detail-favorite").click()
    expect(save).to_be_enabled()
    page.locator("#music-detail-favorite").click()
    expect(save).to_be_disabled()


@pytest.mark.parametrize("domain", ["screen", "music", "books"])
@pytest.mark.parametrize("native", [False, True])
def test_detail_glass_is_stable_from_first_frame_with_normal_motion(
    page, browser_server, domain, native
):
    page.emulate_media(reduced_motion="no-preference")
    assert page.request.put(
        browser_server + "/api/settings/general", data={"interface_transparency": 100}
    ).ok
    page.add_init_script("""(() => {
      for (const name of ['show', 'showModal']) {
        const original = HTMLDialogElement.prototype[name];
        HTMLDialogElement.prototype[name] = function(...args) {
          const result = original.apply(this, args);
          if (this.matches('.detail-window')) {
            const dialog = this, frames = window.detailOpeningFrames = [];
            const sample = () => {
              const style = getComputedStyle(dialog), main = getComputedStyle(dialog.querySelector('.detail-main'));
              frames.push({opacity:style.opacity, transform:style.transform, background:main.backgroundColor, artwork:main.backgroundImage});
              if (frames.length < 16 && dialog.open) requestAnimationFrame(sample);
            };
            sample();
          }
          return result;
        };
      }
    })();""")
    page.goto(browser_server + ("/?desktop=macos" if native else "/"), wait_until="networkidle")
    dialog = open_detail(page, browser_server, domain)
    page.wait_for_function("() => window.detailOpeningFrames?.length === 16")
    frames = page.evaluate("window.detailOpeningFrames")
    assert all(f["opacity"] == "1" and f["transform"] == "none" for f in frames), frames
    assert all(
        f["background"] == frames[0]["background"] and f["artwork"] == "none" for f in frames
    ), frames
    assert rgba(dialog.locator(".detail-main"))[3] < 85
    expect(page.locator("#main > .app-view:not([hidden])").first).to_have_css(
        "filter", "blur(8px)"
    )
    if native:
        drag = page.locator(".native-titlebar-drag-main")
        assert drag.evaluate(
            "e=>{const r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}"
        )
