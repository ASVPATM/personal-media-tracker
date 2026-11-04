"""Shared details, constrained menus, sorting, and appearance in Chromium/WebKit."""

import re
from uuid import uuid4

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect
from test_collection_design import _card, _seed, _switch
from test_collections_browser import browser_server as browser_server
from test_collections_browser import page as page
from test_handoff_20261103_225456_browser import screen_entry
from test_handoff_20261103_followup_browser import settled

pytestmark = pytest.mark.parametrize("page", ["chromium", "webkit"], indirect=True)


def test_screen_favorites_reorder_after_edit_and_art_controls_fit(page, browser_server):
    prefix = "Favorite order " + str(uuid4())[:8]
    favorite = screen_entry(
        page, browser_server, canonical_title=prefix + " Z", episode_count=22
    )
    dialog = page.locator("#entry-dialog")
    settled(dialog)
    # The entire caption, episode counter and heart fit without internal scrolling.
    art = page.locator("#entry-dialog-art")
    assert art.evaluate("e=>e.scrollHeight<=e.clientHeight+1")
    page.locator("#entry-dialog .dialog-close").click()
    ordinary = screen_entry(page, browser_server, canonical_title=prefix + " A")
    page.locator("#entry-dialog .dialog-close").click()
    assert page.request.patch(
        f"{browser_server}/api/entries/{favorite['id']}", data={"is_favorite": True}
    ).ok
    page.locator("#library-toolbar-search").fill(prefix)
    page.locator("#sort").select_option("favorites")
    expect(page.locator("#library > [data-entry]").first).to_have_attribute(
        "data-entry", favorite["id"]
    )
    page.locator(f'#library [data-entry="{favorite["id"]}"] [data-favorite-toggle]').click()
    expect(page.locator("#library > [data-entry]").first).to_have_attribute(
        "data-entry", ordinary["id"]
    )


@pytest.mark.parametrize("domain", ["screen", "music", "books"])
def test_active_collection_toolbar_stays_visible_while_scrolling(page, browser_server, domain):
    for _ in range(12):
        if domain == "screen":
            result = page.request.post(
                browser_server + "/api/entries/manual",
                data={
                    "canonical_title": f"Watching scroll {uuid4()}",
                    "media_type": "movie",
                    "status": "watching",
                },
            )
            assert result.ok
        else:
            _seed(
                page,
                browser_server,
                domain,
                status="listening" if domain == "music" else "reading",
            )
    page.set_viewport_size({"width": 900, "height": 700})
    if domain == "screen":
        page.locator('.primary-nav [data-view="currently_watching"]').click()
        host, bar = "#currently-watching-library", "#currently-watching-view .library-toolbar"
    else:
        _switch(page, domain)
        page.locator('.primary-nav [data-view="music_listening"]').click()
        host, bar = "#music-content", "#music-view .library-toolbar"
    expect(page.locator(host)).to_have_attribute("aria-busy", "false")
    settled(page.locator(bar))
    page.evaluate("()=>window.scrollTo({top:550,behavior:'instant'})")
    page.wait_for_function("()=>scrollY>100")
    expect(page.locator(bar)).to_have_css("position", "sticky")
    assert 0 <= page.locator(bar).bounding_box()["y"] <= 12
    expect(page.locator(bar).get_by_role("button", name=re.compile("Refresh"))).to_be_visible()


@pytest.mark.parametrize("native", [False, True])
def test_short_sidecar_menu_escapes_clip_and_unknown_date_can_be_marked(
    page, browser_server, native
):
    if native:
        page.goto(browser_server + "?desktop=macos", wait_until="networkidle")
    row = screen_entry(page, browser_server)
    episode_id, season_id = str(uuid4()), str(uuid4())
    data = {
        "entry_id": row["id"],
        "supported": True,
        "provider_source": "kitsu",
        "as_of_date": "2026-11-03",
        "subscription": {"enabled": True},
        "progress": {"watched": 0, "released": 0, "total": 1},
        "seasons": [
            {
                "id": season_id,
                "season_number": 1,
                "title": "Season one",
                "watched_count": 0,
                "episodes": [
                    {
                        "id": episode_id,
                        "episode_number": 1,
                        "title": "Unknown air date",
                        "air_date": None,
                        "watched": False,
                    }
                ],
            }
        ],
    }

    def mark(route):
        data["seasons"][0]["episodes"][0]["watched"] = True
        data["seasons"][0]["watched_count"] = 1
        data["progress"]["watched"] = 1
        route.fulfill(json=data)

    page.route(f"**/api/episodes/{episode_id}/viewing", mark)
    page.route(
        f"**/api/entries/{row['id']}",
        lambda route: route.fulfill(
            json={
                **row,
                "episode_progress": {"watched": data["progress"]["watched"], "total": 1},
            }
        ),
    )
    page.evaluate("data=>renderSeriesReleases(data)", data)
    settled(page.locator("#entry-dialog"))
    menu = page.locator(".season-actions .compact-action-menu")
    menu.locator("summary").hover()
    action = menu.locator('[data-season-watched="false"]')
    expect(action).to_be_visible()
    assert action.evaluate(
        "e=>{const r=e.getBoundingClientRect(); return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}"
    )
    assert menu.locator(":scope > div").evaluate("e=>e.matches(':popover-open')")
    menu.locator("summary").focus()
    page.keyboard.press("Escape")
    expect(menu).not_to_have_attribute("open", "")
    button = page.locator("[data-toggle-episode]")
    expect(button).to_be_enabled()
    button.click()
    expect(button).to_have_attribute("aria-pressed", "true")
    progress = page.locator("#series-release-panel .episode-progress")
    expect(progress).to_have_attribute("aria-valuemax", "1")
    expect(progress).to_have_attribute("aria-valuenow", "1")
    assert progress.locator("span").evaluate("e=>e.style.width") == "100%"
    expect(page.locator("#entry-dialog [data-episode-progress]")).to_have_attribute(
        "data-watched", "1"
    )
    assert (
        page.locator(".episode-copy strong").evaluate(
            "e=>getComputedStyle(e).textDecorationLine"
        )
        == "none"
    )
    assert int(button.evaluate("e=>getComputedStyle(e).fontWeight")) >= 800
    selected_ink = page.evaluate("""()=>{
      const probe=document.createElement('span'); probe.style.color='var(--accent-ink)';
      document.body.append(probe); const ink=getComputedStyle(probe).color; probe.remove(); return ink;
    }""")
    expect(button).to_have_css("color", selected_ink)
    # A closed editor must also dismiss any top-layer action panels.
    menu.locator("summary").hover()
    page.locator("#entry-dialog .dialog-close").click()
    expect(page.locator(".compact-action-menu > div:popover-open")).to_have_count(0)


def test_book_current_page_replaces_visible_count_and_preserves_read_total(
    page, browser_server
):
    row = _seed(
        page, browser_server, "books", current_page=12, page_count=230, completion_count=3
    )
    _switch(page, "books")
    _card(page, row).locator("[data-open-music]").click()
    settled(page.locator("#music-editor"))
    expect(page.locator('[name="completion_count"]')).to_be_hidden()
    boxes = [
        page.locator(f'#music-form [name="{key}"]').bounding_box()
        for key in ("status", "rating", "current_page")
    ]
    assert max(b["y"] for b in boxes) - min(b["y"] for b in boxes) < 2
    page.locator('[name="current_page"]').fill("67")
    page.locator("#music-save").click()
    expect(page.locator("#music-editor")).to_be_hidden()
    saved = page.request.get(f"{browser_server}/api/books/entries/{row['id']}").json()
    assert saved["current_page"] == 67
    assert saved["completion_count"] == 3


@pytest.mark.parametrize("domain", ["music", "books"])
def test_centered_art_and_favorite_hit_target_survive_narrow_details(
    page, browser_server, domain
):
    row = _seed(page, browser_server, domain)
    _switch(page, domain)
    _card(page, row).locator("[data-open-music]").click()
    for width in (1440, 900, 390):
        page.set_viewport_size({"width": width, "height": 850})
        settled(page.locator("#music-editor"))
        art = page.locator("#music-editor .entry-dialog-art")
        poster = page.locator("#music-editor-cover .poster")
        if width > 580:
            outer, inner = art.bounding_box(), poster.bounding_box()
            assert abs(outer["x"] + outer["width"] / 2 - inner["x"] - inner["width"] / 2) < 2
        heart = page.locator("#music-detail-favorite")
        heart.hover()
        assert heart.evaluate(
            "e=>{const r=e.getBoundingClientRect(); return [[r.width/2,3],[r.width/2,r.height-3],[3,r.height/2],[r.width-3,r.height/2]].every(([x,y])=>e.contains(document.elementFromPoint(r.x+x,r.y+y)));}"
        ), (width, heart.bounding_box(), art.bounding_box())
        assert not page.locator("#music-editor").evaluate("e=>e.scrollWidth>e.clientWidth+1")


def test_favorite_sort_and_reveal_fades_keep_actions_reachable(page, browser_server):
    prefix = "Fade " + str(uuid4())[:8]
    row = _seed(
        page,
        browser_server,
        "music",
        title=prefix + " An extended title that exceeds the narrow card",
        favorite=True,
        genres=["Electronic", "Experimental", "Ambient", "Classical", "Rock"],
    )
    _seed(page, browser_server, "music", title=prefix + " A plain title", favorite=False)
    assert page.request.put(
        browser_server + "/api/settings/general", data={"music_artwork_reveal": True}
    ).ok
    page.reload(wait_until="networkidle")
    _switch(page, "music")
    page.locator("#music-query").fill(prefix)
    page.locator("#music-sort").select_option("favorites")
    expect(page.locator("#music-sort-direction")).to_contain_text("Favorites first")
    expect(page.locator("#music-favorites")).to_have_count(0)
    expect(page.locator("[data-music-id]").first).to_have_attribute("data-music-id", row["id"])
    card = _card(page, row)
    card.hover()
    signals = card.locator(".entry-signals")
    expect(signals).to_have_class(re.compile("fade-overflow-end"))
    signals.evaluate("e=>e.scrollLeft=e.scrollWidth")
    expect(signals).not_to_have_class(re.compile("fade-overflow-end"))
    heart = card.locator(".favorite-toggle")
    assert heart.evaluate("e=>getComputedStyle(e).maskImage") == "none"
    heart.click()
    expect(heart).to_have_attribute("aria-pressed", "false")


def test_transparency_is_live_persisted_and_data_pairs_adapt(page, browser_server):
    page.locator("#open-settings").click()
    page.locator('[data-settings-tab="general"]').click()
    slider = page.locator("#interface-transparency")
    slider.fill("85")
    slider.dispatch_event("input")
    with page.expect_response(
        lambda r: r.url.endswith("/api/settings/general") and r.request.method == "PUT"
    ):
        slider.dispatch_event("change")
    expect(page.locator("#interface-transparency-value")).to_have_text("85%")
    page.reload(wait_until="networkidle")
    expect(page.locator("html")).to_have_attribute(
        "style", re.compile("--interface-transparency: 85%")
    )
    page.locator("#open-settings").click()
    page.locator('[data-settings-tab="data"]').click()
    settled(page.locator('[data-settings-panel="data"]'))
    expect(page.locator('#collection-export-scope option[value="screen"]')).to_have_text(
        "Screen"
    )
    pairs = page.locator(".data-settings-pair")
    for width in (1440, 390):
        page.set_viewport_size({"width": width, "height": 950})
        settled(page.locator('[data-settings-panel="data"]'))
        for i in range(2):
            children = pairs.nth(i).locator(":scope > section")
            a, b = children.nth(0).bounding_box(), children.nth(1).bounding_box()
            if width == 1440:
                assert abs(a["y"] - b["y"]) < 2
            else:
                assert b["y"] >= a["y"] + a["height"]
        assert page.evaluate("()=>document.documentElement.scrollWidth<=innerWidth+1")
