# Changelog

All notable changes follow semantic versioning.

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
