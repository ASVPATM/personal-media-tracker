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

## Music and books

Use the navigation switch for independent Screen, Music, and Books collections; switching never moves or deletes existing entries.

- **MusicBrainz / Cover Art Archive:** optional album search, edition details, genres, tracklists, and available covers; no key required.
- **Open Library:** optional book search, edition details, authors, subjects, ISBNs, page counts, and available covers; no key required.
- **Manual tracking:** ratings, favorites, notes, lists, and reading/listening status stay separate; nothing plays, scrobbles, or syncs.

Lookups run only on request, with caching and rate limiting; review the returned edition before saving. Book searches prefer the interface language. Missing fields remain editable, and a provider outage does not block manual entries.

Quick Add searches the active collection as you type; manual entry remains available under its disclosure. Choosing a result opens a review before anything is saved.

Book search shows works first, then a work-scoped edition picker with publisher, format, language, year and known pages. Title/author relevance leads; study guides are demoted unless requested. Translated edition titles are searched too, so a work's original-language title does not hide it. Editions are a bounded selection, not the full catalog, and missing facts remain unknown. Back returns to the book results without losing the pending edit. Music search groups releases by album and named version (for example Deluxe or Remastered), rather than repeating countries and physical formats. Exact title/artist relevance comes before catalog coverage and original release year, which help order otherwise equivalent matches; coverage is not a popularity score. Searches are bounded, cached and rate limited, with no per-result image probing. Provider catalogs can still contain duplicate or incorrect records; selection always needs your confirmation. See the [Open Library search API](https://openlibrary.org/dev/docs/api/search) and [MusicBrainz search API](https://musicbrainz.org/doc/MusicBrainz_API/Search).

All collections share PMT's controls, neutral tile borders and a full accent outline on hover or keyboard focus. Music uses consistently sized, shorter tiles with square artwork and compact reveal controls. Listening/Reading and Rankings share the Screen dashboard headings. Settings groups Appearance, Metadata and Integrations independently for each collection. Artwork colours are sampled from already-loaded, readable images. For Screen reveal cards whose remote posters block browser sampling, PMT samples the selected image through its local service: known provider hosts only, owned-entry lookup, bounded downloads and decoding, and a small in-memory colour cache. Unavailable images retain a readable fallback. Rankings always keep their information visible.

Tracklists sit to the right of Music Details on wider windows and stack below them on narrow screens. More actions opens explicit entry/tracklist editing and a preview-and-apply artwork chooser. Artwork fills its frame without stretching; this may crop edges but never changes the source image. Metadata is a read-only summary with provider search; book description-source links appear there, with clean prose in Details. Book editions show their own year and page count, with an explicit alternative-edition chooser when information is missing. PMT never borrows a different edition's page count. Old entries retain their data; selecting their metadata source again refreshes edition details for review before saving.

Selected-edition facts and the book edition chooser live in Metadata, not Details. Reading and Listening use the same compact heading pattern as Watching, with a scope selector and Refresh; hidden Library filters never exclude items there. Reveal surfaces share a translucent, contrast-safe artwork palette across Screen, Music and Books; Music alone keeps the shorter panel. Genre translations are presentation-only, including case-insensitive provider labels in French and Simplified Chinese.

Optional manual completion counts are stored even when hidden on tiles; status changes never invent listens or rereads. Personal genre/subgenre additions and removals are separate from the original catalog labels and survive exports and provider refreshes.

Music cover selection prioritizes approved front images and avoids explicitly labelled packaging when possible, using [Cover Art Archive's 1200px images](https://musicbrainz.org/doc/Cover_Art_Archive/API). Books prefer the work's representative cover over an arbitrary edition scan, without changing edition metadata, using [Open Library's largest available cover](https://openlibrary.org/dev/docs/api/covers). Artwork scope is disclosed. Providers do not guarantee clean covers or complete metadata; the chooser and uploads remain available, and no library-wide cover crawl is performed.

Genre chips use shorter, capitalized display labels; source spelling and subjects remain unchanged in storage and exports. Places and events are not presented as genres, and no subgenre hierarchy is invented. New music/books entries start as Plan to listen/read. Legacy Collected entries keep their saved state internally until the user chooses a status; they do not acquire invented progress or dates. Removing a title from a list removes only that membership, not its library entry or other lists.

Uploaded covers are kept locally and included in collection JSON exports. Provider-linked covers need an internet connection. Artwork links are limited to the supported artwork hosts; upload a file for other images. Attribution links are shown with sourced details and in the current mode's Metadata settings.

Music-only and books-only JSON imports preview changes and add missing entries without replacing existing records. Full archives contain **all three** collections; restoring one replaces all three after a safety backup, including when restoring an older archive without music or books.

**Import a list** first asks for Screen, Music or Books. Screen retains its CSV/ZIP importer; Music and Books validate collection JSON against the chosen domain, show a preview, and require confirmation. Choosing another file or closing cancels its pending preview; an import being committed temporarily locks the file and close controls. Data & Backup offers a matching conversion prompt for each collection. Conversion is optional, runs outside PMT, and never sends your list to a provider automatically.

## Screen metadata matching

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
Simplified Chinese. This is a display overlay, not a rewrite of your library.
Existing TVmaze/anime entries can use TMDb translations after adding a token: PMT tries
stable IMDb/TVDB/Wikidata cross-IDs first, then a unique exact title, year, and compatible
format match for verified provider entries. Ambiguous results are not guessed or relinked.

Titles and summaries fall back independently. A failed provider does not block the next
source; a short Wikidata description is labeled as such. Missing translations keep the
saved description visible, with an explanation and retry action. A token cannot supply
a translation the provider does not have; no machine-translation service is contacted.
