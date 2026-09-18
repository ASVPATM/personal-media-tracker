from __future__ import annotations

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")
from test_collection_design import _card, _seed, _switch  # noqa: E402
from test_collections_browser import (  # noqa: E402
    browser_server as browser_server,
)
from test_collections_browser import page as page  # noqa: E402


@pytest.mark.parametrize("mode", ["music", "books"])
@pytest.mark.parametrize("reveal", [False, True])
def test_collection_taxonomy_updates_in_place_on_interface_language_change(
    page, browser_server, mode, reveal
):
    raw_label = "Fiction, science fiction, general" if mode == "books" else "Electronic"
    row = _seed(page, browser_server, mode, genres=[raw_label])
    _switch(page, mode)
    if reveal:
        page.evaluate(
            "mode => PMTCollectionSettings.applyPreferences({[mode + '_artwork_reveal']: true})",
            mode,
        )
    card = _card(page, row)
    if reveal:
        card.hover()
        playwright_api.expect(card.locator("[data-reveal-music]")).to_have_attribute(
            "aria-expanded", "true"
        )
    card.evaluate("node => { window.collectionLocaleCard = node; }")
    card.locator("[data-open-music]").click()
    page.locator('[data-collection-tab="notes"]').click()
    page.locator('#music-form [name="notes"]').fill("Unsaved multilingual draft")
    page.locator('[data-collection-tab="details"]').click()
    page.locator("#music-overview").evaluate(
        "node => { window.collectionLocaleOverview = node.firstElementChild; }"
    )
    requests = []
    page.on(
        "request",
        lambda request: (
            requests.append(request.url) if f"/api/{mode}/" in request.url else None
        ),
    )
    labels = (
        ["Science fiction", "Science-fiction", "科幻", "Science fiction"]
        if mode == "books"
        else ["Electronic", "Électronique", "电子", "Electronic"]
    )
    for language, label in zip(["en", "fr", "zh-CN", "en"], labels, strict=True):
        page.evaluate("language => applyInterfaceLanguage(language)", language)
        playwright_api.expect(card.locator(".genre-chip").first).to_have_text(label)
        playwright_api.expect(
            page.locator("#music-overview [data-collection-taxonomy]").first
        ).to_have_text(label)
        playwright_api.expect(page.locator('#music-form [name="notes"]')).to_have_value(
            "Unsaved multilingual draft"
        )
        playwright_api.expect(page.locator('#music-form [name="genres"]')).to_have_value(
            raw_label
        )
        playwright_api.expect(page.locator("#music-save")).to_be_enabled()
        assert card.evaluate("node => node === window.collectionLocaleCard")
        assert page.locator("#music-overview").evaluate(
            "node => node.firstElementChild === window.collectionLocaleOverview"
        )
    assert requests == [], "Switching presentation language must not refetch collection data."
    endpoint = "entries" if mode == "books" else "albums"
    stored = page.request.get(f"{browser_server}/api/{mode}/{endpoint}/{row['id']}").json()
    assert stored["genres"] == [raw_label]
    assert stored["notes"] == row["notes"]
    assert stored["version"] == row["version"]
