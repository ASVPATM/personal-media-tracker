# Personal Media Tracker

[![CI](https://github.com/ASVPATM/personal-media-tracker/actions/workflows/ci.yml/badge.svg)](https://github.com/ASVPATM/personal-media-tracker/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/ASVPATM/personal-media-tracker)](https://github.com/ASVPATM/personal-media-tracker/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-345b4c.svg)](LICENSE)

A private, local-first home for your movies, television, limited series, and anime.

[Download the latest release](https://github.com/ASVPATM/personal-media-tracker/releases/latest)
or [run it from source](#run-from-source).

## TL;DR

Personal Media Tracker keeps your library, ratings, watch history, episode progress,
rewatches, and viewing insights on your own computer. It needs no PMT account, ads,
telemetry, or required cloud service. Metadata search works without keys for TV and
anime; an optional TMDb token improves movie coverage and adds another series source.

![The Personal Media Tracker library with poster cards, compact controls, and a dark green colour theme](docs/screenshots/Library.png)

## What you can do

- Keep movies, TV, and anime in one searchable, filterable library.
- Record status, a personal 1–10 rating, dates, rewatches, notes, tags, and favorites.
- Follow verified series, browse seasons, mark episodes watched, and view announced air
  dates without treating them as streaming-availability claims.
- Use direct personal ratings or enable optional guided technical refinement.
- Explore local Insights with date, media, genre, status, and rewatch filters.
- Import CSV, Letterboxd ZIP, an older PMT database, or a PMT Obsidian vault ZIP.
- Export CSV, Obsidian Markdown, calendar snapshots, and checksummed portable backups.
- Personalize light/dark mode, accent and background colours, artwork tinting, navigation,
  shortcuts, and the English, French, or Simplified Chinese (beta) interface.
- Optionally self-host one authenticated PMT server for access from desktop browsers.

## What it looks like

### Rankings

Rank directly from your personal scores. Optional refinement adds explainable evidence
without silently replacing those scores.

![Personal Media Tracker Rankings with live filters and image-forward ranked tiles](docs/screenshots/Rankings.png)

### Insights

All charts use the same visible filters and distinguish known viewing dates from imported
counts whose dates are unknown.

![Personal Media Tracker Insights with summary cards, a viewing timeline, and taste charts](docs/screenshots/Insights.png)

### Make it yours

Appearance changes save automatically. Theme, accent, background strength, background
mode, optional workspace art, subtle or full-colour poster blends, and PMT icon colours
can be combined freely.

![Personal Media Tracker Appearance settings in a custom blue and coral colourway](docs/screenshots/Appearance.png)

## Install a packaged release

Open the [latest GitHub release](https://github.com/ASVPATM/personal-media-tracker/releases/latest)
and download the package for your computer.

| Platform | Package | Install |
| --- | --- | --- |
| macOS | Apple Silicon DMG or ZIP | Open it and move **Personal Media Tracker** to Applications. |
| Windows | x64 ZIP | Extract it and open `Personal Media Tracker.exe`. |
| Linux | x64 archive | Extract it and run `install-linux.sh`, or launch the included executable. |

Check the release notes for signing/notarization status and compare downloads with the
published `SHA256SUMS.txt`. A supported signed macOS installation can download a verified
update inside the app after **Settings → Privacy & About → Check for updates**; other
installs open the release page.

## First setup

1. Start with the built-in keyless providers or add an optional TMDb read-access token.
2. Search for a first title, add one manually, or preview an import.
3. Review **Settings → Data & Backup**, create a backup, and note the displayed data
   location before importing a large history.

TVmaze supplies keyless TV search and schedules. Jikan and Kitsu supply keyless anime
metadata. TMDb improves movie/TV coverage, artwork, and series identity matching when
configured. Ambiguous or contradictory results stay available for manual review rather
than being guessed. See [Metadata providers](docs/METADATA.md) for exact behavior.

## Run from source

Python 3.11 or newer is required.

```bash
git clone https://github.com/ASVPATM/personal-media-tracker.git
cd personal-media-tracker
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
personal-media-tracker --browser
```

Browser mode still runs PMT locally. For the native desktop window, install the desktop
extra and launch without `--browser`:

```bash
python -m pip install -e ".[desktop]"
personal-media-tracker
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.

## Privacy, data, and recovery

The default app binds only to your computer and stores its database locally. It has no
telemetry or central PMT account. Provider searches contact only the relevant metadata
services. Shared access is opt-in and should not be enabled until its security guide is
understood.

Use **Settings → Data & Backup** to reveal the active data folder, create an online SQLite
backup, export a portable Everything archive, or validate a restore. Do not synchronize
the live SQLite file through iCloud Drive, Dropbox, Syncthing, NFS, or SMB; move verified
backup archives instead.

## Documentation

- [Technical guide](docs/TECHNICAL_GUIDE.md) — architecture, storage, developer setup,
  imports, and recovery.
- [Shared-access guide](docs/SELF_HOSTING.md) — optional authenticated remote access.
- [Migration guide](MIGRATING.md) — safely move or restore an existing library.
- [Building releases](BUILDING.md) — desktop packaging commands and artifacts.
- [Changelog](CHANGELOG.md), [support](SUPPORT.md), [privacy](PRIVACY.md), and
  [security policy](SECURITY.md).

## Development checks

```bash
uv sync --locked --extra dev --extra browser
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

## Attribution and license

This product uses the TMDB API but is not endorsed or certified by TMDB. Anime metadata
may come from Jikan/MyAnimeList or Kitsu, TV data from TVmaze under CC BY-SA, and limited
identity data from Wikidata under CC0. Artwork and provider data remain subject to their
respective terms.

Personal Media Tracker is an original project by
[ASVPATM](https://github.com/ASVPATM), released under the [MIT License](LICENSE).
