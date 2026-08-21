# Changelog

All notable changes follow semantic versioning.

## Unreleased

## 2.1.1 — 2026-08-21

- Reduced ranking-refinement repetition with capped adaptive comparison samples, Back
  navigation, per-question and per-title memory skips, 1–5 half-step evidence, and a
  single-title technical-refinement path from Quick Add.
- Added an image-forward Quick Add confirmation step, compact glass-style dashboard and
  Library controls, artwork-connected entry details, clearer episode setup guidance, and
  a theme-matched native desktop window background.
- Replaced the first-use release-check dialog with an Active Shows switch, removed the
  Library list layout, added an onboarding skip control, and introduced data-only locale
  packs so translations can grow without adding language branches throughout the UI.
- Matched the framed macOS title bar to the active application background while preserving
  native traffic-light controls and title-bar dragging.
- Added a vault-ready Obsidian Markdown ZIP export and a Simplified Chinese beta interface.

## 2.1.0 — 2026-08-13

- Rebuilt advanced ranking refinement as a resumable focused/full two-stage workflow with
  visible progress, improved structured questions, future-Insights evidence, and no
  automatic rating replacement or rewatch-count inflation.
- Redesigned Ranking entries as image-forward, information-button-only tiles with larger
  score blocks, stable long-title layout, colored deltas, and compact bottom-aligned
  evidence markers. A single Technical-page explainer now includes the bounded equation
  and replaces per-tile explanations.
- Reworked Library tiles around larger artwork, two compact horizontal genre signals,
  left-aligned viewing-count chips, and a narrower desktop navigation rail.
- Fixed custom accent colors being cleared by unrelated clicks, writable packaged server
  configuration, entry action placement/state, and mixed-language UI after changing the
  interface language. Application shortcuts now start blank and are user-configurable.
- Rewrote Access & Devices setup in plain language, clarified that HTTPS addresses must be
  created and routed before entry, and moved proxy ports/IPs into an advanced section.
- Moved primary desktop navigation into an existing-style PMT left rail with Library,
  Currently Watching, Active Shows, Rankings, and Insights while preserving the responsive
  top fallback. Calendar appears as an indented Active Shows subpage only when relevant.
- Consolidated theme, import, export, backup, restore, and migration controls in Settings.
- Added off-by-default advanced rating tools with versioned guided drafts, explicit score
  decisions, short taste-comparison sessions, undo, explainable technical rankings,
  deterministic scoring, stable filters, full backup coverage, and private JSON export.
- Kept Currently Watching limited to titles explicitly marked Watching. Active Shows now
  means a verified library series with a provider-confirmed episode in the next 60 days,
  and never claims streaming availability. The PMT home action returns to the exact top.
- Added opt-in TMDB-backed series following with normalized season/episode records,
  explicit episode progress, Up Next, a first-use manual/automatic check choice, visible
  check state, safe backoff, freshness/error states, a month calendar, and local `.ics`
  export. The notifications button is retained as an explicit under-development preview.
- Added optional fail-closed single-owner server mode with local preflight/activation,
  Argon2id owner setup, opaque revocable sessions, CSRF and login backoff, exact
  host/origin/proxy trust, HTTPS enforcement, automated retained backups, Tailscale/native
  Linux/Docker deployment examples, and tested return-to-local behavior.
- Added explicit one-time creation and revocation of read-only server calendar feed URLs;
  feed tokens never enter portable backups or access logs.
- Portable archives now preserve all rating and episode/release data while deliberately
  scrubbing server authentication state and continuing to exclude all application and
  provider secrets.

## 2.0.2 — 2026-08-12

- Fixed CI verification when optional desktop dependencies are not installed.
- Fixed horizontal header overflow on narrow Linux browser windows.
- Made the cross-platform browser verification resilient to equivalent Chromium
  selectable-text style values.
- Clarified the difference between installing a packaged Linux release and running a
  Git clone from source.

## 2.0.0 — 2026-08-12

- Renamed the product to Personal Media Tracker with PMT monograms, backward-compatible
  legacy data-directory discovery, archive compatibility, and legacy CLI support.
- Added English/French interface selection, custom accent colours, adjustable background
  intensity, optional full-colour mode, and a dedicated keyboard-shortcuts page.
- Expanded French localization across generated Insights labels, activity dates, status text,
  number formatting, and Settings help; interface language changes now redraw the active view.
- Added an optional media-artwork colour treatment for individual Library cards and included
  that preference in full-library transfers.
- Widened and contained Settings, made its privacy reminder dismissible, fixed clipped
  help bubbles, and prevented dialog overscroll from moving the underlying page.
- Kept Add Media on the current Library or Insights page, fixed top navigation offsets,
  centred the Export control, made meaningful text selectable, and compacted/rebalanced
  Insights layouts.

- Added a desktop launcher with automatic local-server startup, ephemeral loopback ports,
  health waiting, clean shutdown, browser fallback, and single-instance locking.
- Added platform-standard data/config/cache/log/backup directories for packaged builds.
- Added automatic pre-migration backup and post-migration integrity checks.
- Added one-click online backup, validated restore, safety backup, and existing-database import.
- Added checksummed full-library export, read-only migration previews, hash-bound import,
  portable preference transfer, and legacy version 1 archive compatibility.
- Added owner-only local credential storage by default, with OS Keychain access available
  only as a clearly warned opt-in or deliberate one-time migration.
- Added Host/origin validation, CSP/security headers, release-mode docs disabling, safer URLs,
  rotating local logs, and hardened ZIP/CSV resource limits.
- Added first-run onboarding and expanded General, Appearance, Metadata, Data & Backup,
  Privacy, and About settings.
- Replaced the oversized library Quick Add panel with a focused shortcut/dialog, added
  clearer sort direction labels, and added 24/48/96-title page density controls.
- Added interactive taste, rating, media-mix, status, completion, rewatch, monthly, and
  weekday visualizations while minimizing secondary format/signal/coverage diagnostics.
- Added six accent palettes plus a custom background-tint picker that adapt to light/dark
  mode, explicit settings save states, verified effective-timezone feedback, metadata
  locale choices, and honest AniList status.
- Added contextual help to Settings and a privacy-aware, copyable conversion prompt for
  normalizing arbitrary media lists into previewable CSV without making AI a requirement.
- Disabled WebView caching for local API data so a first-page library cannot remain stale
  or blank until the page-size selector changes.
- Documented affinity/confidence calculations in-app and preserved small non-zero affinity
  percentages instead of rounding them to 0%.
- Added manual GitHub update checking and provider attribution/policy documentation.
- Added reproducible dependency locking, CI/release workflows, and cross-platform desktop builds.
- Preserved all rating, viewing, identity, import, taxonomy, statistics, and export invariants.

## 1.0.0 — 2026-08-11

- Initial local-first tracker handoff release.
