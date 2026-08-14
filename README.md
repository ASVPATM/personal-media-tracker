# Personal Media Tracker

[![CI](https://github.com/ASVPATM/personal-media-tracker/actions/workflows/ci.yml/badge.svg)](https://github.com/ASVPATM/personal-media-tracker/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/ASVPATM/personal-media-tracker)](https://github.com/ASVPATM/personal-media-tracker/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-345b4c.svg)](LICENSE)

Your private place to track movies, television, limited series, and anime.

Personal Media Tracker is a local-first media diary for building a library, recording
ratings and rewatches, following active shows, and understanding your viewing habits.
It works without an account, telemetry, advertising, or a central cloud database.

[Download the latest release](https://github.com/ASVPATM/personal-media-tracker/releases/latest)
or [run it from source](#run-from-source).

![Personal Media Tracker library showing poster cards, filters, and the left navigation rail](docs/screenshots/Library.png)

## Why Personal Media Tracker?

- **Private by default:** your library stays on your computer unless you explicitly set
  up shared access or export it.
- **Simple when you want it:** ordinary 1–10 ratings remain the fastest and default
  rating method.
- **Deeper when you want it:** optional guided questions and short comparisons can
  refine an explainable technical ranking without replacing your personal scores.
- **Built for movies, TV, and anime:** keep one library while filtering and ranking each
  media type separately.
- **Aware of active shows:** follow verified series, mark episodes watched, see what is
  up next, and browse announced air dates.
- **Portable:** import existing lists, create checked backups, and move your complete
  library between installations.
- **Optionally self-hosted:** one authenticated server can give your Mac, Linux laptop,
  and other desktop browsers access to the same canonical history.

## Features

### Your complete media library

- Track movies, TV series, limited series, and anime together.
- Record status, personal rating, viewing dates, view count, notes, and tags.
- Record individual rewatches without losing earlier viewing history.
- Search optional metadata providers or add a title manually.
- Browse poster cards in grid or list layouts.
- Filter by media type, status, year, genre, rating range, and rating state.
- Sort by last watched, date added, personal rating, title, year, or media type.
- Keep Currently Watching separate from the complete Library.
- Soft-delete and restore entries instead of immediately destroying their history.

### Personal ratings and optional technical rankings

The normal rating remains a nullable personal score from 1–10, with one decimal place.
It continues to power existing filters, exports, and Insights.

Advanced ratings are **off by default**. When enabled in Settings, they add:

- A focused or full rating-refinement workflow.
- Short taste-comparison sessions rather than an exhaustive all-pairs exercise.
- Guided questions about impact, distinctiveness, staying power, and related evidence.
- Resumable progress for large libraries.
- Explicit decisions about whether to keep or change the original personal rating.
- A Personal/Technical Rankings switch.
- Stable movie, TV, and anime filters.
- A clear explanation of how technical scores work.
- A private structured export of assessment and comparison data.

Technical rankings stay anchored to your own 1–10 scores and apply only small, bounded
adjustments from completed assessments and comparisons. Rewatch counts provide context;
they do not automatically inflate a rating. Technical scores never silently overwrite
your personal ratings or change the existing Insights calculations.

![Personal Media Tracker technical rankings with Personal and Technical modes, filters, and ranked poster tiles](docs/screenshots/Rankings.png)

### Currently Watching, Active Shows, and episode progress

- Currently Watching contains titles you explicitly mark as Watching.
- Active Shows contains verified TV or anime entries with a provider-confirmed episode
  announced within the next 60 days.
- Following a supported series does not silently change its status.
- Browse normalized seasons and episodes.
- Mark individual episodes or a confirmed season as watched or unwatched.
- See progress, Up Next, specials preferences, and metadata freshness.
- Run a manual check or opt into bounded checks while the application is running.
- Open a dedicated month calendar for upcoming episodes.
- Download a local one-year `.ics` calendar snapshot.
- In authenticated server mode, create and revoke a read-only calendar subscription URL.

Release tracking currently uses verified TMDB TV identities. Dates represent announced
**air dates**, not guaranteed availability on a particular streaming service. A TMDB
read-access token is required for automatic movie/TV metadata and episode schedules.

### Viewing Insights

Explore interactive, privacy-preserving statistics calculated from your local library:

- Library, completion, viewing, rating, and rewatch summaries.
- Media-type and status breakdowns.
- Personal-rating distribution and tendencies.
- Monthly and weekday activity.
- Genre, subgenre, and provider-tag affinity.
- Metadata coverage and evidence labels.
- Highest-rated and most-rewatched titles.

Insights distinguish dated viewing events from imported view totals whose exact dates
are unknown. Existing Insights continue to use your personal ratings rather than derived
technical rankings.

![Personal Media Tracker Insights showing library summaries, media breakdown, watch profile, and taste explorer](docs/screenshots/Insights.png)

### Import, export, backup, and migration

- Preview supported CSV and Letterboxd ZIP imports before committing changes.
- Preserve existing personal edits through explicit conflict policies.
- Export a portable Everything archive with checksums and integrity information.
- Export the watch log as CSV.
- Export preference profiles as JSON or Markdown.
- Export advanced-rating evidence separately as private JSON.
- Create online SQLite backups from Settings.
- Validate restores and create a safety backup before replacement.
- Import a compatible older Personal Watch Tracker database.
- Create an automatic backup before database migrations.

Complete archives preserve library entries, ratings, assessments, comparisons, viewing
history, episode progress, release records, deleted entries, and portable preferences.
They deliberately exclude provider tokens, application secrets, owner credentials,
sessions, login-throttle records, and calendar-feed tokens.

### Appearance, language, and accessibility

- Light, dark, or system theme.
- Multiple accent presets plus a custom accent color.
- Adjustable background color and intensity.
- Optional full-color background mode.
- Optional poster-derived card tinting.
- English interface and work-in-progress French translation.
- Keyboard navigation, configurable shortcuts, visible focus, reduced-motion support,
  semantic dialogs, and screen-reader labels.

## Download

Open the [latest release](https://github.com/ASVPATM/personal-media-tracker/releases/latest)
and select the package for your operating system. Packaged builds include the application
and its Python runtime.

| Platform | Current package | Installation |
| --- | --- | --- |
| macOS | Apple Silicon | Open the DMG or ZIP and move Personal Media Tracker to Applications. |
| Windows | x64 | Extract the ZIP and open `Personal Media Tracker.exe`. |
| Linux | x64 | Extract the archive and run `install-linux.sh`, or launch the included executable directly. |

Check each release’s notes for signing/notarization status and use the published
`SHA256SUMS.txt` file when verifying a download.

### First run

The first-run guide lets you:

1. Configure optional TMDB metadata search.
2. Search for your first title.
3. Import an existing media list.
4. Start with a manual entry.

TMDB is optional for ordinary manual use. It is required for TMDB movie/TV search and
automatic episode schedules. Public anime fallback search is available through Jikan
without an account or API key.

## Run from source

Source installations require Python 3.11 or newer.

```bash
git clone https://github.com/ASVPATM/personal-media-tracker.git
cd personal-media-tracker
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
personal-media-tracker --browser
```

For later launches:

```bash
cd personal-media-tracker
source .venv/bin/activate
personal-media-tracker --browser
```

Browser mode still runs the application entirely on your computer. It does not upload
your library and is the simplest source-installation option on Linux distributions where
a desktop WebView is unavailable.

Windows PowerShell users can activate the environment with:

```powershell
.venv\Scripts\Activate.ps1
personal-media-tracker --browser
```

## Optional shared access

Shared access is not required. The default local-only mode remains loopback-only, needs no
account, and behaves like the ordinary desktop release.

When explicitly enabled, single-owner server mode lets several authorized desktop
browsers use the same running application and canonical database. It includes:

- Local setup preflight and explicit activation.
- Argon2id password hashing.
- Revocable, expiring sessions.
- Secure, HttpOnly, SameSite cookies.
- CSRF protection and login backoff.
- Exact Host, Origin, HTTPS, and trusted-proxy validation.
- Automatic retained backups while the server is running.
- Tailscale Serve, native Linux service, and Docker/Caddy deployment guidance.
- A tested return-to-local workflow.

Start with the [Shared-access guide](docs/SELF_HOSTING.md). The recommended first option
is a private Tailscale network plus application authentication. Public reverse-proxy
deployment is an advanced path.

Shared access does **not** synchronize SQLite files. One running application process owns
one database on local storage. Do not place the live database on Dropbox, iCloud,
Syncthing, NFS, SMB, or another network filesystem.

## Privacy and security

By default:

- Your database stays on your computer.
- No Personal Media Tracker account is required.
- There is no telemetry, advertising, behavioral analytics, or automatic upload.
- Provider searches contact only the metadata services needed for the requested action.
- Backups and exports happen only when requested, except for documented pre-migration and
  optional server-mode scheduled backups.

Read the [Privacy notice](PRIVACY.md) and [Security policy](SECURITY.md) for the complete
boundaries and reporting instructions.

## Current limitations

- The interface is desktop-focused; a dedicated mobile/PWA installation is not included.
- Offline edits and multi-device conflict synchronization are not supported.
- Shared access supports one owner and one application process, not household accounts or
  multiple SQLite workers.
- Release tracking currently depends on a verified TMDB TV identity.
- Air dates do not guarantee regional streaming availability.
- The in-app release-notification center is not yet public; Active Shows, Up Next,
  calendar, and `.ics` export are available now.
- French translation is still in progress, and some newer explanations remain in English.
- Packaged macOS releases currently target Apple Silicon; packaged Windows and Linux
  releases target x64.

## Documentation

- [Technical guide](docs/TECHNICAL_GUIDE.md) — architecture, source setup, storage,
  imports, backups, security, and developer commands.
- [Shared-access guide](docs/SELF_HOSTING.md) — Tailscale, native Linux, Docker/Caddy,
  backups, recovery, and moving hosts.
- [Migration guide](MIGRATING.md) — move or restore an existing library safely.
- [Building desktop releases](BUILDING.md) — local packaging and release artifacts.
- [Changelog](CHANGELOG.md) — versioned feature and behavior changes.
- [Support](SUPPORT.md) — help and issue-reporting guidance.
- [Security policy](SECURITY.md) — report security problems privately.
- [Contributing guide](CONTRIBUTING.md) and [Code of Conduct](CODE_OF_CONDUCT.md).

## Development and verification

Create a development environment with all test dependencies:

```bash
uv sync --locked --extra dev --extra browser
```

Run formatting, lint, and the test suite:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Run the repeatable synthetic-library performance check:

```bash
uv run python scripts/benchmark_local.py
```

CI tests Python 3.11–3.13, cross-platform launcher startup, browser E2E/accessibility,
clean migrations, package builds, and dependency vulnerabilities. Tagged releases build
and smoke-test native artifacts on macOS, Windows, and Linux before publication.

## Contributing and support

Bug reports, usability feedback, documentation improvements, and focused contributions
are welcome. Before opening an issue, read [SUPPORT.md](SUPPORT.md) and
[CONTRIBUTING.md](CONTRIBUTING.md). Do not include private library data, credentials,
tokens, backups, or logs containing personal information in a public issue.

Security problems should be reported through the private process in
[SECURITY.md](SECURITY.md), not through a public issue.

## Metadata attribution

This product uses the TMDB API but is not endorsed or certified by TMDB. Anime metadata
may be provided by Jikan/MyAnimeList where available. Provider names, artwork, and data
remain subject to their respective terms and attribution requirements.

## License

Personal Media Tracker is an original project by
[ASVPATM](https://github.com/ASVPATM), released under the [MIT License](LICENSE). The
copyright and license notice must remain with copies or substantial portions of the
software.
