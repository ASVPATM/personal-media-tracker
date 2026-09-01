from __future__ import annotations

REASON_MESSAGE_KEYS = {
    "genre_affinity": "recommendations.reason.genre_affinity",
    "subgenre_affinity": "recommendations.reason.subgenre_affinity",
    "keyword_affinity": "recommendations.reason.keyword_affinity",
    "language_affinity": "recommendations.reason.language_affinity",
    "country_affinity": "recommendations.reason.country_affinity",
    "format_affinity": "recommendations.reason.format_affinity",
    "media_type_affinity": "recommendations.reason.media_type_affinity",
    "public_quality": "recommendations.reason.public_quality",
    "provider_similarity": "recommendations.reason.provider_similarity",
    "confirmed_refinement_fit": "recommendations.reason.refinement_fit",
    "positive_rating_anchor": "recommendations.reason.positive_rating_anchor",
    "favorite_anchor": "recommendations.reason.favorite_anchor",
    "discovery_quality": "recommendations.reason.discovery_quality",
}


def message_keys(reason_codes: list[str]) -> list[str]:
    return [REASON_MESSAGE_KEYS[code] for code in reason_codes if code in REASON_MESSAGE_KEYS]
