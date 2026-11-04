"""Cross-collection behavior and geometry for the 22:54 handoff."""

from uuid import uuid4

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect
from test_collection_design import _card, _seed, _switch
from test_collections_browser import browser_server as browser_server
from test_collections_browser import edit_panel, edit_tracks
from test_collections_browser import page as page
from test_handoff_20261103_followup_browser import settled

pytestmark = pytest.mark.parametrize("page", ["chromium", "webkit"], indirect=True)


def screen_entry(page, server, **values):
    identifier = str(uuid4())
    response = page.request.post(
        server + "/api/entries/manual",
        data={
            "canonical_title": "Compact screen " + identifier,
            "media_type": "tv",
            "status": "watching",
            "provider_source": "tmdb_tv",
            "provider_id": identifier,
            "tmdb_tv_id": identifier,
            "runtime_minutes": 23,
            "public_score": 8.4,
            "provider_genres": ["Drama"],
            "overview": "A long description with meaningful context. " * 70,
            **values,
        },
    )
    assert response.ok, response.text()
    row = response.json()["entry"]
    saved = page.request.patch(
        f"{server}/api/entries/{row['id']}", data={"subgenre_additions": ["Mystery"]}
    )
    assert saved.ok, saved.text()
    page.reload(wait_until="networkidle")
    page.locator(f'[data-entry="{row["id"]}"] [data-details]').click()
    expect(page.locator("#entry-dialog")).to_be_visible()
    return row


@pytest.mark.parametrize("domain", ["music", "books"])
def test_creator_badge_gap_is_constant_for_short_and_long_titles(page, browser_server, domain):
    rows = [
        _seed(
            page,
            browser_server,
            domain,
            title=title + str(uuid4())[:5],
            status="listening" if domain == "music" else "reading",
        )
        for title in ("Short ", "A substantially longer title that takes more than one line ")
    ]
    _switch(page, domain)
    gaps = []
    for row in rows:
        card = _card(page, row)
        creator = card.locator(".music-card-artist").bounding_box()
        badges = card.locator(".entry-signals").bounding_box()
        gaps.append(badges["y"] - creator["y"] - creator["height"])
    assert max(gaps) - min(gaps) <= 1, gaps
    assert all(2 <= gap <= 8 for gap in gaps), gaps


@pytest.mark.parametrize("domain", ["music", "books"])
@pytest.mark.parametrize("width", [1440, 900, 390])
def test_compact_details_fit_and_tracking_stays_on_one_line(
    page, browser_server, domain, width
):
    row = _seed(
        page,
        browser_server,
        domain,
        **(
            {
                "description": "An extended book description. " * 90,
                "page_count": 320,
                "subgenres": ["Literary fiction"],
                "publisher": "Example Publisher",
            }
            if domain == "books"
            else {"tracks": [{"title": "One", "position": 1, "disc": 1}]}
        ),
    )
    page.set_viewport_size({"width": width, "height": 950})
    _switch(page, domain)
    _card(page, row).locator("[data-open-music]").click()
    dialog = page.locator("#music-editor")
    settled(dialog)
    controls = [
        page.locator(f'#music-form [name="{key}"]').bounding_box()
        for key in (
            "status",
            "rating",
            "current_page" if domain == "books" else "completion_count",
        )
    ]
    assert max(c["y"] for c in controls) - min(c["y"] for c in controls) <= 2, controls
    frame = page.locator("#music-editor .detail-main").bounding_box()
    assert frame["height"] <= 560
    assert dialog.evaluate("e=>e.scrollWidth <= e.clientWidth + 1")
    for tab in ("notes", "genres", "metadata", "details"):
        edit_panel(page, tab)
        assert page.locator("#music-editor .detail-main").bounding_box() == frame
    expect(page.locator("#music-overview")).not_to_contain_text("Subgenres")
    expect(page.locator("#music-overview")).not_to_contain_text("Example Publisher")
    if domain == "books":
        content = page.locator("#music-overview").bounding_box()
        description = page.locator("#music-description").bounding_box()
        assert description["width"] >= content["width"] * 0.85
        page.locator("#music-description-toggle").click()
        expect(page.locator("#music-description-toggle")).to_have_attribute(
            "aria-expanded", "true"
        )


@pytest.mark.parametrize("domain", ["music", "books"])
def test_provider_catalog_is_readonly_but_tracking_and_artwork_remain_available(
    page, browser_server, domain
):
    row = _seed(
        page,
        browser_server,
        domain,
        provider_id=str(uuid4()) if domain == "music" else f"OL{uuid4().int % 100000000}M",
        **(
            {"tracks": [{"title": "Provider track", "position": 1, "disc": 1}]}
            if domain == "music"
            else {"chapters": ["Provider chapter"]}
        ),
    )
    _switch(page, domain)
    _card(page, row).locator("[data-open-music]").click()
    page.locator("#music-more-actions summary").hover()
    expect(page.locator("#music-edit-catalog")).to_be_hidden()
    expect(page.locator("#music-edit-tracklist")).to_be_hidden()
    expect(page.locator("#music-browse-artwork")).to_be_visible()
    expect(page.locator("#music-title")).to_be_disabled()
    if domain == "books":
        edit_panel(page, "contents")
        expect(page.locator('[name="chapters"]')).not_to_be_editable()
    edit_panel(page, "details")
    page.locator('[name="rating"]').fill("9")
    edit_panel(page, "notes")
    page.locator('#music-form [name="notes"]').fill("My personal note")
    page.locator("#music-save").click()
    expect(page.locator("#music-editor")).to_be_hidden()
    endpoint = "albums" if domain == "music" else "entries"
    saved = page.request.get(f"{browser_server}/api/{domain}/{endpoint}/{row['id']}").json()
    assert saved["rating"] == 9 and saved["notes"] == "My personal note"
    assert saved["provider_id"] == row["provider_id"] and saved["title"] == row["title"]
    assert saved.get("tracks", saved.get("chapters")) == row.get("tracks", row.get("chapters"))


def test_manual_track_editor_uses_compact_top_menu_and_cancel_restores_data(
    page, browser_server
):
    row = _seed(
        page,
        browser_server,
        "music",
        tracks=[{"title": "Original", "disc": 1, "position": 1, "duration_ms": 121234}],
    )
    _switch(page, "music")
    _card(page, row).locator("[data-open-music]").click()
    edit_tracks(page)
    expect(page.locator("#music-add-track")).to_be_hidden()
    assert page.locator(".track-title").bounding_box()["height"] <= 30
    menu = page.locator(".track-edit-actions")
    menu.locator("summary").hover()
    for selector in ("#music-add-track", "#music-cancel-tracks", "#music-done-tracks"):
        expect(menu.locator(selector)).to_be_visible()
    assert menu.bounding_box()["y"] <= page.locator(".music-track-table").bounding_box()["y"]
    page.locator("#music-add-track").click()
    page.locator(".track-title").last.fill("Discarded")
    menu.locator("summary").hover()
    page.locator("#music-cancel-tracks").click()
    expect(page.locator("#music-track-preview tbody tr")).to_have_count(1)
    expect(page.locator("#music-save")).to_be_disabled()


@pytest.mark.parametrize("domain", ["screen", "music", "books"])
def test_pointer_close_does_not_leave_stuck_card_glow_and_keyboard_focus_works(
    page, browser_server, domain
):
    if domain == "screen":
        row = screen_entry(page, browser_server, media_type="movie")
        card = page.locator(f'[data-entry="{row["id"]}"]')
        close = page.locator("#entry-dialog .dialog-close")
        trigger = card.locator("[data-details]")
    else:
        row = _seed(page, browser_server, domain)
        _switch(page, domain)
        card = _card(page, row)
        trigger = card.locator("[data-open-music]")
        trigger.click()
        close = page.locator("#music-editor .dialog-close")
    close.click()
    page.locator("#open-settings").hover()
    expect(card).to_have_css(
        "border-top-color",
        card.evaluate(
            "e=>{const x=document.createElement('i'); x.style.color='var(--line)'; e.append(x); const c=getComputedStyle(x).color; x.remove(); return c}"
        ),
    )
    trigger.focus()
    trigger.press("ArrowRight")
    expect(page.locator("html")).to_have_attribute("data-input-modality", "keyboard")
    expect(card).to_have_css(
        "border-top-color",
        card.evaluate(
            "e=>{const x=document.createElement('i'); x.style.color='var(--accent-choice,var(--accent))'; e.append(x); const c=getComputedStyle(x).color; x.remove(); return c}"
        ),
    )


@pytest.mark.parametrize("domain", ["screen", "music", "books"])
def test_action_menu_closes_on_blank_footer_and_delete_hover_is_red(
    page, browser_server, domain
):
    if domain == "screen":
        screen_entry(page, browser_server)
        root = page.locator("#entry-dialog")
        button = root.locator("#delete-entry")
    else:
        row = _seed(
            page,
            browser_server,
            domain,
            provider_id=str(uuid4()) if domain == "music" else f"OL{uuid4().int % 100000000}M",
        )
        _switch(page, domain)
        _card(page, row).locator("[data-open-music]").click()
        root = page.locator("#music-editor")
        button = root.locator("#music-delete")
    menu = root.locator(".more-actions")
    menu.locator("summary").hover()
    button.hover()
    expect(button).to_have_css("color", "rgb(255, 255, 255)")
    settled(button)
    assert button.evaluate(
        "e=>{const s=getComputedStyle(e); return s.backgroundColor === s.borderTopColor && s.color === 'rgb(255, 255, 255)'}"
    )
    footer, bounds = root.locator(".dialog-footer").bounding_box(), menu.bounding_box()
    assert bounds["width"] < footer["width"] - 90
    # Same footer, outside both the menu and the save button.
    page.mouse.move(bounds["x"] + bounds["width"] + 4, bounds["y"] + bounds["height"] / 2)
    expect(menu).not_to_have_attribute("open", "")


def test_screen_heart_description_metadata_and_followed_episodes(page, browser_server):
    row = screen_entry(page, browser_server)
    for width in (1440, 390):
        page.set_viewport_size({"width": width, "height": 950})
        settled(page.locator("#entry-dialog"))
        positions = [
            page.locator(selector).bounding_box()["y"]
            for selector in ("#entry-status", "#entry-rating", "#entry-count")
        ]
        assert max(positions) - min(positions) <= 2, positions
    page.set_viewport_size({"width": 1440, "height": 950})
    expect(page.locator("#entry-community-score")).to_contain_text("8.4")
    expect(page.locator("#entry-overview-facts")).not_to_contain_text("Runtime")
    expect(page.locator("#entry-overview-facts")).not_to_contain_text("Subgenres")
    heart = page.locator("#entry-detail-favorite")
    assert heart.evaluate("e=>!!e.closest('.detail-art-meta')")
    heart.click()
    expect(heart).to_have_attribute("aria-pressed", "true")
    page.locator("#follow-series").click()
    expect(page.locator("#series-season-select")).to_be_visible()
    expect(page.locator(".episode-row")).to_have_count(2)
    expect(page.locator(".series-source-panel, .season-card")).to_have_count(0)
    expect(heart).to_have_attribute("aria-pressed", "true")
    future = page.locator(".episode-row", has_text="Upcoming Browser Episode").locator(
        "[data-toggle-episode]"
    )
    expect(future).to_be_disabled()
    released = page.locator(".episode-row", has_text="Released Browser Episode").locator(
        "[data-toggle-episode]"
    )
    released.click()
    expect(released).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#series-season-select option")).to_contain_text("1/2")
    page.locator('[data-entry-tab="metadata"]').click()
    expect(page.locator("#entry-metadata-facts")).to_contain_text("Episode runtime")
    page.locator('[data-entry-tab="genres"]').click()
    expect(page.locator("#entry-effective-genres")).to_contain_text("Mystery")
    expect(page.locator("#entry-translation-retry")).to_have_count(0)
    page.locator('button[form="entry-form"]').click()
    expect(page.locator("#entry-dialog")).to_be_hidden()
    assert (
        page.request.get(f"{browser_server}/api/entries/{row['id']}").json()["is_favorite"]
        is True
    )
    page.locator(f'[data-entry="{row["id"]}"] [data-details]').click()
    heart.click()
    page.locator("#entry-dialog .dialog-close").click()
    assert (
        page.request.get(f"{browser_server}/api/entries/{row['id']}").json()["is_favorite"]
        is True
    )


def test_watching_count_belongs_to_toolbar(page):
    page.locator('.primary-nav [data-view="currently_watching"]').click()
    expect(page.locator("#currently-watching-library")).to_have_attribute("aria-busy", "false")
    assert page.locator("#currently-watching-state").evaluate(
        "e=>!!e.closest('.library-toolbar')"
    )


def test_season_switch_keeps_updated_progress_and_server_date_eligibility(page, browser_server):
    screen_entry(page, browser_server)
    expect(page.locator("#follow-series")).to_be_visible()
    first, second = str(uuid4()), str(uuid4())
    data = {
        "supported": True,
        "provider_source": "tvmaze",
        "as_of_date": "2000-01-05",
        "subscription": {"enabled": True, "include_specials": False},
        "progress": {"watched": 0, "released": 1, "total": 2},
        "seasons": [
            {
                "id": "s1",
                "season_number": 1,
                "watched_count": 0,
                "episodes": [
                    {
                        "id": first,
                        "episode_number": 1,
                        "title": "Earlier",
                        "air_date": "2000-01-01",
                        "watched": False,
                    }
                ],
            },
            {
                "id": "s2",
                "season_number": 2,
                "watched_count": 0,
                "episodes": [
                    {
                        "id": second,
                        "episode_number": 1,
                        "title": "Later",
                        "air_date": "2000-01-10",
                        "watched": False,
                    }
                ],
            },
        ],
    }
    page.evaluate("data=>renderSeriesReleases(data)", data)
    expect(page.locator(".series-source-menu > summary")).to_contain_text("TVmaze")
    page.locator("#series-season-select").select_option("s2")
    # Even though 2000 is in the browser's past, eligibility follows the
    # server's explicit library date, not this device's current date.
    expect(page.locator("[data-toggle-episode]")).to_be_disabled()
    page.locator("#series-season-select").select_option("s1")
    data["progress"]["watched"] = 1
    data["seasons"][0]["watched_count"] = 1
    data["seasons"][0]["episodes"][0]["watched"] = True
    page.route(f"**/api/episodes/{first}/viewing", lambda route: route.fulfill(json=data))
    page.locator("[data-toggle-episode]").click()
    expect(page.locator("[data-toggle-episode]")).to_have_attribute("aria-pressed", "true")
    page.locator("#series-season-select").select_option("s2")
    page.locator("#series-season-select").select_option("s1")
    expect(page.locator("[data-toggle-episode]")).to_have_attribute("aria-pressed", "true")
    expect(page.locator(".series-progress-copy")).to_contain_text("1 watched")


@pytest.mark.parametrize("domain", ["music", "books"])
def test_list_membership_has_compact_click_targets_and_keeps_pending_notes(
    page, browser_server, domain
):
    row = _seed(page, browser_server, domain)
    response = page.request.post(
        f"{browser_server}/api/{domain}/lists", data={"name": "List " + str(uuid4())[:8]}
    )
    assert response.ok, response.text()
    listing = response.json()
    _switch(page, domain)
    _card(page, row).locator("[data-open-music]").click()
    edit_panel(page, "notes")
    page.locator('#music-form [name="notes"]').fill("Keep my note while adding to a list")
    page.locator("#music-membership > summary").click()
    checkbox = page.locator(f'[data-music-membership="{listing["id"]}"]')
    label = checkbox.locator("..")
    box, text = checkbox.bounding_box(), label.locator("span").bounding_box()
    assert 0 < text["x"] - box["x"] - box["width"] <= 8
    label.click()
    expect(checkbox).to_be_checked()
    expect(page.locator('#music-form [name="notes"]')).to_have_value(
        "Keep my note while adding to a list"
    )
    page.locator("#music-save").click()
    expect(page.locator("#music-editor")).to_be_hidden()
