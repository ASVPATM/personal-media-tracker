# Personal Media Tracker — Technical Guide

Personal Media Tracker is a polished, private media diary for movies, TV, limited series,
and anime. Search or import a title, record ratings and rewatches, keep notes and tags,
and explore explainable viewing insights—all from one local desktop application.

Your library belongs to you. Default local mode has no account or cloud database: it
binds to loopback and keeps SQLite on your computer. Optional single-owner server mode is
self-hosted, authenticated, HTTPS-only, and uses one canonical database rather than file
synchronization. Neither mode adds a social feed, telemetry, advertising, or automatic
third-party upload of watch history.

## Download

Normal users should download the latest build from
[GitHub Releases](https://github.com/ASVPATM/personal-media-tracker/releases/latest).
Packaged builds include Python and start the private local server automatically.

### macOS

Download the Apple Silicon `.dmg` or `.zip`, move **Personal Media Tracker.app** to
Applications, and open it normally. Unsigned development builds may require
Control-click → Open; public builds remain unsigned until notarization credentials are
configured in the release repository.

### Windows

The v2.6.0 native Windows archive is known-broken on real hardware and is not currently a
supported installation path. Its packaged Python.NET runtime can fail before PMT opens.
Use local Docker/browser mode for testing; do not move an important library into the
native package while this status remains.

### Linux

The v2.6.0 native Linux archive is known-broken on real hardware and is not currently a
supported installation path. It can become incorrectly laid out and then terminate with
a segmentation fault during ordinary UI interaction. Use local Docker/browser mode for
testing and do not run the native installer with `sudo`.

Native Windows and Linux packages remain unsupported until real-hardware diagnostics and
stability checks pass. Use Docker/browser mode on those platforms for now.

## First run

The welcome flow explains local privacy and offers search, import, or manual entry.
TVmaze TV search/schedules and Jikan/Kitsu anime search work without accounts or API keys.
A TMDb API read-access token is optional and adds richer movie/TV metadata, artwork, and a
second schedule source; Wikidata supplies a deliberately limited keyless movie fallback.
Tokens saved in the desktop UI use an unencrypted local configuration file with user-only
permissions by default, so app launches do not request an OS password. The
operating-system credential vault remains an explicit, clearly labelled stronger-security
option because it may request authentication; the token is never returned to browser
JavaScript.

AniList is disabled by default because its current terms restrict competing trackers.
Maintainers or developers with permission may explicitly enable it with
`WATCHTRACKER_ANILIST_ENABLED=true`.

## Features

- Focused Quick Add dialog with one-character search, partial-provider failure, and safe duplicate actions.
- Movies, TV, limited series, and evidence-backed anime classification.
- Optional 1.0–10.0 personal ratings in one-decimal increments, separate from community scores.
- Four directly linkable destinations in an existing-style left rail: Library, Currently
  Watching, Rankings, and Insights. Theme and data transfer controls remain in Settings.
- Optional advanced rating drafts, transparent suggestions, short comparison sessions,
  and deterministic technical rankings that never overwrite a score silently.
- Optional series schedules, season/episode progress, Up Next, a month calendar,
  manual/startup/periodic polling, and local `.ics` snapshots. Notification storage is
  present for future work, but its public UI is deliberately marked under development.
- Optional single-owner shared access for Mac and Linux browsers through one authenticated
  HTTPS server; local-only use remains the default.
- Status, notes, tags, dates, viewing events, aggregate counts, and explicit rewatches.
- Grid/list library, filtering, clearly labeled sorting, 24/48/96-title page sizes,
  URL-persisted state, and soft deletion.
- Conservative metadata refresh and a human-confirmed unresolved-title queue.
- Interactive, deterministic Insights for taste, ratings, media mix, status, completion,
  rewatches, monthly activity, and weekday activity.
- Explainable weighted affinity, exact confidence thresholds, honest support counts, and
  insufficient-data states; undated imported view counts are never invented as dates.
- System, Light, and Dark themes; preset or custom accent colours; adjustable background
  strength; an optional full-colour mode; keyboard navigation; and responsive layouts.
- Validated timezone and metadata-locale settings with explicit pending/saved feedback.

The interface includes English, a release-ready French catalog, and a Simplified Chinese
beta catalog. Automated coverage prevents new static or explicitly localized interface
copy from silently shipping without French; the beta Chinese catalog may still fall back
to English. Metadata result languages also include German, Spanish, Simplified Chinese,
Japanese, and Korean; that independent option controls provider titles and summaries
rather than application menus.

### Ratings and technical rankings

Direct 1–10 ratings remain the default and authoritative value used by existing exports
and Insights. Settings → **Ratings & Rankings** enables a staged, resumable private
workflow. The owner chooses a focused sample, the entire rated library, or starts from a
single newly added title. A capped adaptive sample calibrates nearby titles without an
exhaustive pair exercise, and then the workflow records per-title evidence. Six
core dimensions cover impact, distinctiveness, formula freshness, engagement, coherence,
and staying power. Four optional dimensions cover consistency, personal significance,
return desire, and strengths versus flaws; a private reflection remains optional. Answers
map linearly from 1–5 to 1–10 in half-point steps. At least four core answers are required,
and skipped, not-remembered, or not-applicable answers are excluded.

`advanced-ranking-v2` begins with the personal rating. A completed rubric can contribute
at most 30% of the difference and at most ±0.75; pair comparisons use a logistic expected
result with scale 1.25, sparse evidence shrinkage `n/(n+8)`, and another ±0.75 bound. The
final value is clamped to 1–10 and sorted before display rounding with stable title/ID
tie-breaks. Evidence labels describe input coverage only—not objective quality. Filters
run after score calculation, so filtering cannot change a title's score.

The workflow never offers an automatic replacement rating. Completing evidence keeps the
scalar rating unchanged. Actual viewing and rewatch counts are displayed as context,
but do not add technical points; only the deliberate optional return-desire answer can
represent that preference. CSV remains scalar-only; the private Advanced ratings JSON
export includes reflections and refinement-run history deliberately, and a full archive
preserves all rating tables while excluding credentials.

### Episodes and release checks

Episode schedules require a verified TVmaze or TMDb TV identity; TVmaze is keyless, while
TMDb requires its optional token. A manual or automatic library check discovers those
verified TV/anime entries and caches their schedules. **Active Shows** then displays only
entries with a provider-confirmed episode between today and 60 days from today. A compact
heading switch controls automatic checking while PMT is open; leaving it off keeps checks
manual. The app
shows an active progress state, normalizes season and episode facts, performs idempotent
bounded polling, and retains cached schedules through provider failures. It records last
attempted and last successful checks separately and applies bounded exponential backoff.
Desktop automatic checks stop when the app closes; server checks require the host to remain
on.

Episode completion is stored independently from title-level viewing/rewatch history. A
new episode or season never marks anything watched, changes a rating, or rewrites show
status. Specials are excluded by default. Dates are provider-reported **air dates**, not
streaming-availability claims; this release does not fetch TMDB/JustWatch availability.
The release calendar is an indented subpage of Active Shows rather than part of Currently
Watching. Local mode downloads a one-year `.ics` snapshot. Authenticated server mode can explicitly
create and revoke a random read-only subscription URL; it contains only followed-series
titles and provider air dates. The URL is a bearer secret, is shown once, and is scrubbed
from portable archives.

## Imports

Import always starts with a non-mutating preview. Supported formats include canonical or
watch-log CSV and unmodified Letterboxd export ZIPs. Conflicting personal values require
an explicit merge policy. Stable provider IDs are preferred, exact-file imports are
idempotent, and Letterboxd diary rows remain individual viewing events.

Settings → **Data & Backup** also provides a copyable, privacy-aware prompt for turning
a document, spreadsheet, text list, JSON file, or unusual export into the small
supported CSV shape. AI conversion is optional: the instructions ask users to identify
their rating scale, avoid invented values, remove private notes if desired, review the
result, and use the app's non-mutating preview before committing anything.

Archives are processed in memory without extraction and are bounded by request,
decompressed-size, member-count, compression-ratio, row, and cell limits. Path traversal,
nested archives, encrypted members, executable content, malformed quoting, and invalid
encodings are rejected safely.

## Backups and exports

Settings → **Data & Backup** provides:

- **Export everything**, a versioned full-fidelity archive for moving between the
  browser/server and desktop versions;
- non-mutating inspection with real title, viewing, and deleted-item counts before a
  migration can replace anything;
- **Create backup** using SQLite's online backup API;
- **Obsidian vault ZIP**, a one-way Markdown snapshot with an index, YAML properties, and
  one note per active title (including private PMT notes);
- validated restore with an automatic safety backup before replacement;
- deliberate import of an older Personal Watch Tracker database without deleting it;
- data, backups, and logs folder shortcuts in the desktop app.

A version 2 archive contains the complete SQLite database, portable preferences, a
checksummed manifest, and a readable watch-log CSV. This preserves titles, personal
ratings, statuses, notes, tags, viewing history, metadata/provenance, import records,
soft-deleted items, and the underlying data from which Insights are calculated. It never
contains the TMDB credential or machine-specific window geometry. Legacy version 1
backups and raw tracker SQLite databases remain accepted.

To move an existing browser/server library to the desktop app, export everything from
the old installation, inspect the ZIP in the desktop app, verify the counts, and import.
If the older build cannot export, import its untouched `watchtracker.sqlite3` directly.
Do not use CSV for a full-fidelity move. See [MIGRATING.md](../MIGRATING.md) for exact steps
and recovery guidance.

The Obsidian export is intentionally not two-way synchronization. Unzip its `Personal Media
Tracker` folder into a vault and re-export when a new snapshot is wanted. Keeping independent
Obsidian writing outside that generated folder avoids ambiguous merges; poster images remain
remote HTTPS links and are not downloaded.

## Run from source

Python 3.11+ is supported. `uv` is recommended and `pip` remains compatible.

```bash
uv sync --extra dev
uv run personal-media-tracker --browser
```

Or:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
personal-media-tracker --browser
```

Useful power-user modes:

```bash
personal-media-tracker --no-open
personal-media-tracker --browser --port 8000
personal-media-tracker backup
personal-media-tracker migrate-database /path/to/old-watchtracker.sqlite3
personal-media-tracker restore /path/to/personal-media-tracker-backup.zip
personal-media-tracker setup-owner
personal-media-tracker server-readiness
```

The fixed development default is `127.0.0.1:8000`; packaged desktop mode selects a free
loopback port. Local mode now refuses a non-loopback host. Non-loopback deployment exists
only through validated server mode with authentication and HTTPS; see
[SELF_HOSTING.md](SELF_HOSTING.md).

## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run alembic upgrade head
uv build
```

Tests use temporary SQLite databases and fake provider transports. See
[BUILDING.md](../BUILDING.md) for desktop artifacts and [CONTRIBUTING.md](../CONTRIBUTING.md)
for contribution guidance.

## Local data locations

Packaged builds use platform-standard directories:

- macOS: `~/Library/Application Support/Personal Media Tracker/`
- Windows: `%LOCALAPPDATA%\Personal Media Tracker\`
- Linux: the applicable XDG data/config/cache directories

Source runs keep disposable development state under this repository's ignored `data/`
and `cache/` directories. `WATCHTRACKER_DATA_DIR`, `WATCHTRACKER_DATABASE_PATH`,
`WATCHTRACKER_CACHE_DIR`, and related settings provide explicit overrides.

At startup the app compares Alembic revisions, creates a pre-migration backup when an
existing database needs a schema change, migrates once, then runs SQLite integrity and
basic query checks.

An upgraded installation automatically continues using an existing Personal Watch
Tracker data directory when it finds the prior database or preferences there. The rename
therefore does not move, replace, or hide an existing library. The `watchtracker` command
and `WATCHTRACKER_*` environment names remain accepted for backward compatibility.

## Privacy and security

The local API validates Host headers, rejects clearly foreign browser origins on
mutations, does not enable CORS, and sends a deliberate CSP and other browser security
headers. Server mode additionally uses an Argon2id owner password, opaque expiring and
revocable sessions, Secure/HttpOnly/SameSite cookies, CSRF tokens, login backoff, exact
hosts/origins/proxy IPs, HSTS, and fail-closed HTTPS configuration. Release mode disables
FastAPI's interactive API documentation. Logs rotate locally and avoid credential values,
notes, imported rows, and full preference profiles.

Portable archives deliberately scrub owner accounts, sessions, and throttle state. They
also exclude application/provider secrets. In server mode a persistent job creates a
scheduled archive every 24 hours while running and retains 14 by default; failures leave
the live database and older backups intact and use bounded retry. Full deployment,
restore, disaster-recovery, and return-to-local instructions are in the
[shared-access guide](SELF_HOSTING.md).

Read [PRIVACY.md](../PRIVACY.md) and [SUPPORT.md](../SUPPORT.md). Please do not expose this
unauthenticated application directly to a LAN or the public Internet. Report security
problems privately through GitHub's vulnerability-reporting feature.

## Metadata attribution and provider policy

Metadata calls pass through a provider capability registry rather than application code
assuming TMDb. Search results merge only on shared external identities or strong
title/alias, media-type, and year agreement. PMT stores normalized source snapshots and
per-field provenance while keeping provider payloads and caches outside the future mobile
sync contract. See [Metadata providers](METADATA.md) and
[ADR 0008](adr/0008-provider-neutral-metadata-and-mobile-boundary.md).

This product uses the TMDB API but is not endorsed or certified by TMDB. TMDB requires
attribution for its data and images; its approved logo appears in the app's About panel.
TVmaze data is used under CC BY-SA, and Wikidata structured data is CC0. Jikan is an
unofficial, read-only MyAnimeList API and publishes limits of 3 requests per second and
60 per minute. Kitsu is a second keyless anime source and prevents a Jikan outage from
emptying anime search. AniList integration is opt-in only for authorized use under its
current terms and is not shown as an unavailable setup card in public Settings. The local
cache is bounded and temporary; it is not a bulk provider archive.

Provider requirements were reviewed against the official
[TMDB FAQ/attribution page](https://developer.themoviedb.org/docs/faq),
[TVmaze API documentation](https://www.tvmaze.com/api),
[Wikidata licensing page](https://www.wikidata.org/wiki/Wikidata:Licensing),
[Kitsu API documentation](https://kitsu.docs.apiary.io/),
[AniList API terms](https://anilist.gitbook.io/anilist-apiv2-docs/docs/guide/terms-of-use)
and [rate-limit documentation](https://anilist.gitbook.io/anilist-apiv2-docs/docs/guide/rate-limiting),
and [Jikan v4 documentation](https://docs.api.jikan.moe/) on 2026-08-25. Provider terms
can change; release maintainers should recheck them.

## Contributing

Issues and pull requests are welcome. Please read [CONTRIBUTING.md](../CONTRIBUTING.md).
Personal data, credentials, databases, caches, and real exports must never be committed.

Licensed under the [MIT License](../LICENSE).
