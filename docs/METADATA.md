# Metadata providers and reliability

PMT searches multiple independent catalogs while keeping one provider-neutral identity
record for each Library title. A provider outage should reduce enrichment, not make an
otherwise usable title disappear.

| Provider | Credential | Current purpose |
| --- | --- | --- |
| TVmaze | None | TV search, aliases, artwork, details, and episode schedules |
| Jikan / MyAnimeList data | None | Anime search, details, genres, artwork, and MAL identities |
| Kitsu | None | Independent anime search, artwork, categories, runtime, and MAL/AniList ID corroboration |
| TMDb | Optional read token | Rich movie search and artwork; additional TV metadata and schedules |
| Wikidata | None | Limited movie fallback, external-ID bridge, and available Commons artwork when TMDb is unavailable |

Search results are clustered only when providers share an external ID, or when exact
title/alias, compatible type, and year evidence agree. PMT stores external identities,
normalized source snapshots, and the source chosen for each filled field. Refreshes do not
replace personal ratings, notes, tags, viewing history, list membership, episode edits, or
manually selected artwork.

Automatic enrichment can accept one type/year-compatible result and can select a clear
leader from a small candidate set when title evidence is strong. Conflicting years or
types and close ties remain in manual review. Provider failures are isolated and reported
without discarding successful results from other providers.

TV data from TVmaze is used under CC BY-SA. Wikidata content is CC0. TMDb, Jikan, Kitsu,
TVmaze, and Wikidata attribution links remain visible in Settings → Privacy & About.

## Translated descriptions

Media details request available text in the interface language: English, French, or
Simplified Chinese (beta). This is a display overlay, not a rewrite of your library.
Existing TVmaze/anime entries can use TMDb translations after adding a token: PMT tries
stable IMDb/TVDB/Wikidata cross-IDs first, then a unique exact title, year, and compatible
format match for verified provider entries. Ambiguous results are not guessed or relinked.

Titles and summaries fall back independently. A failed provider does not block the next
source; a short Wikidata description is labeled as such. Missing translations keep the
saved description visible, with an explanation and retry action. A token cannot supply
a translation the provider does not have; no machine-translation service is contacted.
