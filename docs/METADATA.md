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

Book search groups repeated works by title and author identity, puts covered, relevant works first, and keeps their editions available without borrowing another edition's page count. Music search accepts artist and album together (for example “sade deluxe”), groups redundant physical releases, and retains named versions. Eight results appear initially; use **More catalog results** for the rest. Covers have bounded fallbacks; catalog coverage is only a relevance tie-break, not proof of identity. Searches remain cached and rate limited. See the [Open Library search API](https://openlibrary.org/dev/docs/api/search) and [MusicBrainz search API](https://musicbrainz.org/doc/MusicBrainz_API/Search).

Collection imports offer **Find metadata and artwork after import**, enabled in the confirmation dialog and optional. PMT sends titles and creators (or book ISBNs) to the appropriate public catalog; personal ratings and notes are not sent. Only confident matches are applied; uncertain matches are listed for review. Ratings, notes, tracking progress, custom artwork and existing manual details are retained.

For earlier manual imports, open **Settings → Music (or Books) → Metadata → Library maintenance → Fill missing metadata**—no re-import is needed. The completion summary lives there too, not above your tiles. Progress survives an app restart, checking can be stopped, and selecting a review item opens a compact comparison. Resolved or removed entries leave the review queue. Unavailable catalog fields remain unknown. Re-imports and manual additions check both catalog identity and matching manual entries; existing duplicates are never silently merged or deleted.

Review compares the imported title and creator with a selected edition before applying it. **Keep manual** opts the entry out of automatic checks until it changes; it does not count as a successful match. **Edit imported spelling** previews the correction. **Try again later** leaves the entry unresolved. Decisions are version-checked, and existing duplicates can be inspected without merging or deleting either entry. Checks can target identities, artwork, optional fields or previous provider outages; unchanged entries checked within seven days are skipped unless explicitly retried.

The Metadata settings report identity links, genre coverage and locally stored covers separately. Downloaded covers can be cleared without removing uploaded artwork or your library. See [cache and performance limits](development/PERFORMANCE.md).

**Retry unresolved entries** checks the unresolved part of the previous batch without rechecking successful matches. **More entries to review** reveals remaining review items in large imports. Music fill searches official album groups before selecting an edition, checks credited artists and catalog aliases, and tolerates small spelling/punctuation differences when the other identity evidence is strong. Albums, singles and live/remixed versions are distinguished; ambiguous artist names and same-name albums still require review. A supplied year helps disambiguate them. Artwork or popularity never proves identity.

The Music maintenance dialog also offers **Use Wikidata aliases for unresolved albums**. This optional fallback sends unresolved titles to Wikidata, validates title/performer aliases and explicit MusicBrainz identifiers, then checks the performer against the MusicBrainz album before choosing an official edition. It adds no account requirement or alternate artwork-rights assumptions. Existing background jobs and imports do not enable the extra source without this choice. [Wikidata data access and licensing](https://www.wikidata.org/wiki/Wikidata:Data_access).

Screen, Music and Books share numbered pagination. Background metadata updates are coalesced, yield to navigation and editing, and keep unchanged tiles and page controls in place. Bulk music filling avoids the interactive artwork chooser's additional requests and uses smaller covers; the chooser remains available for manual artwork changes.

Collection covers are cached locally (up to 128 MB / 512 images, plus a 16 MB / 64-image memory cache) and revalidated through an owned-entry endpoint. Cached alternatives are checked before trying remote images. After seven days, a cached cover remains visible during a bounded background refresh, up to a maximum cache age of 30 days. Visible images load first; offscreen covers are lazy-loaded, including their decorative backgrounds. A first uncached download can still depend on provider speed. The cache is disposable; uploaded artwork and backups stay separate.

All collections share PMT's controls, neutral tile borders and a full accent outline on hover or keyboard focus. Music uses consistently sized, shorter tiles with square artwork and compact reveal controls. Listening/Reading and Rankings share the Screen dashboard headings. Settings groups Appearance and Metadata independently for each collection. Account synchronization and playback integrations are unavailable in this version; existing connection records are preserved, but their endpoints and scheduled pulls are disabled. Keyless metadata lookup, optional TMDb access, file imports, release schedules and notifications remain available. Artwork colours are sampled from already-loaded, readable images. For Screen reveal cards whose remote posters block browser sampling, PMT samples the selected image through its local service: known provider hosts only, owned-entry lookup, bounded downloads and decoding, and a small in-memory colour cache. Unavailable images retain a readable fallback. Rankings always keep their information visible.

Media details keep a stable main editor while music tracklists and series episodes live in connected, independently scrolling panes. Narrow windows stack these panes. Catalog and tracklist edits support scoped cancellation without discarding other pending personal changes. Standard music albums use the curated release-group cover consistently in search, detail lookup and metadata fill; named editions retain their specific cover. Approved front images are preferred over labeled packaging scans, and alternative artwork remains selectable. Existing saved artwork is never silently replaced.

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
