from pathlib import Path

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")
SOURCE = (
    Path(__file__).parents[1] / "src/watchtracker/static/collection-taxonomy.js"
).read_text()


@pytest.fixture(scope="module")
def taxonomy_page():
    with playwright_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.evaluate(
            (Path(__file__).parents[1] / "src/watchtracker/static/locales/music.js").read_text()
        )
        page.evaluate(SOURCE)
        yield page
        browser.close()


def summarize(page, row, mode="books"):
    return page.evaluate(
        "([row, mode]) => PMTCollectionTaxonomy.summarize(row, mode)", [row, mode]
    )


def test_catalog_paths_become_readable_without_changing_source(taxonomy_page):
    row = {
        "genres": [
            "Fiction, science fiction, general",
            "British and irish fiction (fictional works by one author)",
            "Dune (Imaginary place)",
            "bombing of Dresden",
        ],
        "subgenres": ["Fiction, Romance, Historical, Regency"],
    }
    result = summarize(taxonomy_page, row)
    assert [item["label"] for item in result["genres"]] == ["Science fiction"]
    assert [item["label"] for item in result["subgenres"]] == ["Regency romance"]
    assert result["sourceGenres"] == row["genres"]
    assert result["sourceSubgenres"] == row["subgenres"]
    assert result["genres"][0]["raw"] == [row["genres"][0]]


def test_music_styles_group_for_display_only(taxonomy_page):
    row = {
        "genres": ["contemporary r&b", "cool jazz", "jazz", "alternative rock"],
        "subgenres": ["cool jazz"],
    }
    result = summarize(taxonomy_page, row, "music")
    assert [item["label"] for item in result["genres"]] == ["R&B", "Jazz", "Rock"]
    assert result["genres"][1]["raw"] == ["cool jazz", "jazz"]
    assert result["sourceGenres"] == row["genres"]
    assert [item["label"] for item in result["subgenres"]] == ["cool jazz"]


def test_unknown_terms_are_bounded_but_originals_remain(taxonomy_page):
    unknown = "A very specific classification with considerable regional detail"
    result = summarize(taxonomy_page, {"genres": [unknown, "文学小说"]})
    assert len(result["genres"][0]["label"]) <= 30
    assert result["genres"][0]["label"].endswith("…")
    assert result["genres"][0]["raw"] == [unknown]
    assert result["genres"][1]["label"] == "文学小说"


def test_topics_do_not_invent_genres(taxonomy_page):
    result = summarize(
        taxonomy_page,
        {"genres": ["Dune (Imaginary place)", "bombing of Dresden", "Protected DAISY"]},
    )
    assert result["genres"] == []
    assert len(result["sourceGenres"]) == 3


def test_provider_subjects_never_displace_recognized_genres(taxonomy_page):
    row = {
        "provider_id": "OL123M",
        "genres": [
            "Arkenstone",
            "Hugo Award Winner",
            "award:hugo=1966",
            "Boys",
            "Fiction",
            "Fantasy",
            "New York Times bestseller",
            "Wizards",
        ],
    }
    result = summarize(taxonomy_page, row)
    assert [item["label"] for item in result["genres"]] == ["Fantasy"]
    assert result["sourceGenres"] == row["genres"]
    unknown = summarize(taxonomy_page, {"provider_id": "OL123M", "genres": ["Arkenstone"]})
    assert unknown["genres"] == []
    assert unknown["sourceGenres"] == ["Arkenstone"]


def test_missing_taxonomy_stays_missing(taxonomy_page):
    assert summarize(taxonomy_page, {}) == {
        "genres": [],
        "subgenres": [],
        "sourceGenres": [],
        "sourceSubgenres": [],
    }


def test_summary_is_not_a_mutation_or_persisted_hierarchy(taxonomy_page):
    result = taxonomy_page.evaluate(
        """() => {
            const row = Object.freeze({genres: Object.freeze(['cool jazz']),
                                       subgenres: Object.freeze([])});
            const before = JSON.stringify(row);
            const summary = PMTCollectionTaxonomy.summarize(row, 'music');
            summary.sourceGenres.push('Only a copy');
            return {same: before === JSON.stringify(row), subgenres: summary.subgenres};
        }"""
    )
    assert result == {"same": True, "subgenres": []}


def test_genre_labels_do_not_use_workspace_or_reverse_ui_translation(taxonomy_page):
    assert taxonomy_page.evaluate("PMTCollectionTaxonomy.label('Fiction', 'en')") == "Fiction"
    assert taxonomy_page.evaluate("PMTCollectionTaxonomy.label('Music', 'en')") == "Music"
    assert taxonomy_page.evaluate("PMTCollectionTaxonomy.label('Music', 'fr')") == "Musique"
    assert taxonomy_page.evaluate("PMTCollectionTaxonomy.label('History', 'fr')") == "Histoire"
    assert (
        taxonomy_page.evaluate("PMTCollectionTaxonomy.label('Science fiction', 'zh-CN')")
        == "科幻"
    )
