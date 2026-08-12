from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

INFERENCE_VERSION = "2.0"

GENRE_ALIASES = {
    "sci fi": "Science Fiction",
    "sci-fi": "Science Fiction",
    "science fiction": "Science Fiction",
    "tv movie": "TV Movie",
    "slice of life": "Slice of Life",
    "romance": "Romance",
    "animation": "Animation",
}

SUBGENRE_RULES: dict[str, tuple[set[str], ...]] = {
    "Psychological Thriller": ({"psychological", "thriller"}, {"psychological thriller"}),
    "Mystery Thriller": ({"mystery thriller"},),
    "Crime Drama": ({"crime", "drama"},),
    "Dark Comedy": ({"dark comedy"}, {"black comedy"}),
    "Romantic Comedy": ({"romantic comedy"},),
    "Action Comedy": ({"action comedy"},),
    "Workplace Comedy": ({"workplace comedy"},),
    "Satire": ({"satire"}, {"satirical"}),
    "Mockumentary": ({"mockumentary"},),
    "Psychological Horror": ({"psychological horror"},),
    "Supernatural Horror": ({"supernatural", "horror"}, {"supernatural horror"}),
    "Body Horror": ({"body horror"},),
    "Cosmic Horror": ({"cosmic horror"}, {"lovecraftian"}),
    "Folk Horror": ({"folk horror"},),
    "Found-Footage Horror": ({"found footage"},),
    "Zombie Horror": ({"zombie horror"},),
    "Survival Horror": ({"survival horror"},),
    "Slasher": ({"slasher"},),
    "Political Thriller": ({"political thriller"},),
    "Legal Drama": ({"legal drama"}, {"courtroom drama"}),
    "Medical Drama": ({"medical drama"},),
    "Period Drama": ({"period drama"},),
    "Coming-of-Age": ({"coming of age"},),
    "Character-Driven Drama": ({"character study"}, {"character driven"}),
    "Neo-Noir": ({"neo noir"},),
    "Space Opera": ({"space opera"},),
    "Dystopian Sci-Fi": ({"dystopian science fiction"}, {"dystopian sci fi"}),
    "Time-Travel Sci-Fi": ({"time travel science fiction"}, {"time travel sci fi"}),
    "Science Fantasy": ({"science fantasy"},),
    "Cyberpunk": ({"cyberpunk"},),
    "Cerebral Sci-Fi": ({"cerebral", "science fiction"},),
    "Isekai": ({"isekai"},),
    "Mecha": ({"mecha"},),
    "Iyashikei": ({"iyashikei"},),
    "Magical Girl": ({"magical girl"}, {"mahou shoujo"}),
    "Seinen": ({"seinen"},),
    "Shounen": ({"shounen"}, {"shonen"}),
    "Shoujo": ({"shoujo"}, {"shojo"}),
    "Josei": ({"josei"},),
}

DIMENSION_EVIDENCE: dict[str, dict[str, set[str]]] = {
    "pacing": {
        "slow-burn": {"slow burn", "slow-burn"},
        "fast-paced": {"fast paced"},
    },
    "darkness_tone": {
        "dark": {"dark"},
        "light": {"feel-good", "iyashikei", "lighthearted"},
    },
    "narrative_complexity": {
        "complex": {"nonlinear", "cerebral", "complex narrative"},
    },
    "visual_atmosphere": {
        "atmospheric": {"atmospheric", "noir", "cyberpunk", "surreal", "gothic"},
    },
    "ending_ambiguity": {
        "ambiguous": {"ambiguous ending", "open ending"},
    },
    "emotional_register": {
        "tense": {"suspense", "tense"},
        "melancholic": {"melancholy", "melancholic"},
        "uplifting": {"feel good", "inspirational", "uplifting"},
        "comforting": {"iyashikei", "wholesome"},
    },
    "humor_style": {
        "dark": {"dark comedy", "black comedy"},
        "satirical": {"satire", "satirical"},
        "absurdist": {"absurdist", "absurd comedy"},
        "deadpan": {"deadpan", "dry humor"},
    },
    "story_structure": {
        "anthology": {"anthology"},
        "episodic": {"episodic"},
        "nonlinear": {"nonlinear", "non linear"},
        "ensemble": {"ensemble cast", "ensemble"},
    },
    "worldbuilding": {
        "dystopian": {"dystopia", "dystopian"},
        "cyberpunk": {"cyberpunk"},
        "spacefaring": {"space opera", "space travel"},
        "historical": {"historical", "period drama"},
    },
    "thematic_focus": {
        "coming-of-age": {"coming of age"},
        "family": {"family relationships"},
        "identity": {"identity", "self discovery"},
        "survival": {"survival"},
        "political": {"politics", "political"},
    },
}


def normalize_title(title: str) -> str:
    folded = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().casefold()
    folded = folded.replace("'", "")
    folded = re.sub(r"[^a-z0-9]+", " ", folded)
    return " ".join(folded.split())


def _canonical_genre(value: str) -> str:
    cleaned = " ".join(value.replace("_", " ").strip().split())
    return GENRE_ALIASES.get(cleaned.casefold(), cleaned.title())


def _normalize_evidence(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", folded).split())


def _has_evidence(term: str, evidence_terms: set[str]) -> bool:
    needle = _normalize_evidence(term)
    if not needle:
        return False
    pattern = re.compile(rf"(?:^|\s){re.escape(needle)}(?:$|\s)")
    return any(pattern.search(value) for value in evidence_terms)


def classify_media_type(
    media_type: str,
    *,
    provider_source: str | None = None,
    anilist_id: str | None = None,
    mal_id: str | None = None,
    provider_genres: list[str] | None = None,
    keywords: list[str] | None = None,
    country: str | None = None,
    language: str | None = None,
    existing_media_type: str | None = None,
) -> str:
    """Keep anime distinct when provider identity or factual metadata establishes it."""
    if provider_source in {"anilist", "mal"} or anilist_id or mal_id:
        return "anime"
    evidence = {
        _normalize_evidence(value)
        for value in [*(provider_genres or []), *(keywords or [])]
        if value
    }
    provider_calls_it_anime = "anime" in evidence
    japanese_animation = (
        (country or "").strip().upper() == "JP"
        and (language or "").strip().casefold() in {"ja", "jpn", "japanese"}
        and "animation" in evidence
    )
    if provider_calls_it_anime or japanese_animation:
        return "anime"
    if (
        existing_media_type == "anime"
        and media_type in {"movie", "tv"}
        and (provider_source or "").startswith("tmdb_")
    ):
        return "anime"
    return media_type


@dataclass(frozen=True)
class TaxonomyResult:
    genres: list[str]
    subgenres: list[str]
    taste_evidence: dict[str, list[dict[str, str]]]
    provenance: dict[str, object]


def infer_taxonomy(
    provider_genres: list[str] | None,
    keywords: list[str] | None,
    *,
    media_type: str,
) -> TaxonomyResult:
    genres = sorted(
        {_canonical_genre(value) for value in provider_genres or [] if value.strip()}
    )
    evidence_terms = {
        normalized
        for value in [*(provider_genres or []), *(keywords or [])]
        if (normalized := _normalize_evidence(value))
    }

    subgenres: list[str] = []
    subgenre_evidence: dict[str, list[str]] = {}
    for subgenre, alternatives in SUBGENRE_RULES.items():
        matched = next(
            (
                sorted(required)
                for required in alternatives
                if required and all(_has_evidence(term, evidence_terms) for term in required)
            ),
            None,
        )
        if matched:
            subgenres.append(subgenre)
            subgenre_evidence[subgenre] = matched

    taste: dict[str, list[dict[str, str]]] = {}
    for dimension, values in DIMENSION_EVIDENCE.items():
        matches: list[dict[str, str]] = []
        for value, terms in values.items():
            for term in sorted(terms):
                if _has_evidence(term, evidence_terms):
                    matches.append({"value": value, "evidence": term})
                    break
        if matches:
            taste[dimension] = matches

    return TaxonomyResult(
        genres=genres,
        subgenres=sorted(subgenres),
        taste_evidence=taste,
        provenance={
            "version": INFERENCE_VERSION,
            "provider_genres": provider_genres or [],
            "keywords": keywords or [],
            "subgenre_evidence": subgenre_evidence,
        },
    )


def effective_values(
    derived: list[str], additions: list[str], removals: list[str]
) -> list[str]:
    removed = {item.casefold() for item in removals}
    values = {item for item in derived if item.casefold() not in removed}
    values.update(item.strip() for item in additions if item.strip())
    return sorted(values, key=str.casefold)
