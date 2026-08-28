# Changelog

All notable changes follow semantic versioning.

## 2.6.0 — 2026-08-27

- Fixed followed-series schedule syncs so the media tile receives episode totals
  immediately, and changed tile episode/favorite actions to replace only the affected
  tile instead of refreshing the entire library.
- Made an explicit first series follow create one nearest-upcoming in-app release alert;
  Apprise remains optional external delivery and automatic library discovery stays quiet.
- Added an account-free Docker preview and an optional official Apprise API sidecar while
  keeping the sidecar manager and PMT port bound to loopback.
- Centered native dialogs consistently on Linux and switched Windows/Linux desktop bundles
  to an explicitly verified Qt backend, with Linux software rendering for broader driver
  compatibility and a packaged-backend release check.
- Paused new PMT Server Beta setup/container publication behind an explicit repository
  release flag while its completed multi-user and integration work remains in private soak.
- Marked the published v2.5.4 Windows and Linux native packages as known-unstable; macOS is
  the only currently recommended native v2.5.4 package.
- Added an additive viewing-cycle and completion-occurrence model so manual history,
  provider claims, and playback observations follow one deduplicating policy without
  treating short playback or aggregate progress as invented viewing history.
- Added the versioned `pmt.platform-sync` v2 portable-data contract with deterministic
  records, stable origins, tombstones, unknown-date preservation, an idempotent import
  ledger, forward-compatible record handling, and explicit secret/cache exclusions.

## 2.5.4 — 2026-08-27

- Added compact episode progress controls to TV and episodic-anime tiles, backed by
  persistent progress counts and individual episode-viewing records when schedule rows
  are available. Future and undated episodes are excluded from released totals, and the
  tile controls can be hidden in Appearance settings.
- Added keyless Kitsu episode schedules for verified anime, including locally cached air
  dates, released-episode totals, Active Shows support, and safer full-library checks that
  reuse fresh schedules instead of repeatedly calling providers.
- Reworked Watching into All active & planned, Watching, Rewatching, and Plan to watch
  scopes, with a compact responsive selector that remains readable at narrow widths.
- Split Lists into personal and shared collections. A list can now be exported as a
  versioned PMT shared-list file and imported as a read-only snapshot without importing
  another person's ratings, notes, tags, history, or ranking evidence.
- Restored the Notifications destination in the normal local application and combined
  release events with shared-list activity. Release alerts support read and dismiss state;
  external Apprise delivery remains planned rather than implied by this release.
- Redesigned Settings around a compact adaptive frame: a restrained vertical section rail
  on desktop becomes horizontal tabs on smaller windows, controls and copy are denser, and
  the General page fits a standard 1280 × 720 viewport without scrolling.
- Improved episode-aware Insights so explicit compact progress and released known episodes
  contribute without inventing watch dates or counting future/TBA episodes.
- Hardened Linux installation with root refusal, archive-version verification, staged
  replacement, rollback on failed installation, and an automated release-workflow install
  check.
- Expanded French coverage for the new episode, list, notification, and Settings surfaces;
  Simplified Chinese remains explicitly beta.
- Added migration, API, isolation, release-tracking, native-packaging, and responsive
  browser regression coverage for the new behavior.

## 2.5.3 — 2026-08-26

- Separated the regular desktop client from PMT Server Beta: the standalone server owns
  the server console, process controls, accounts, and backups, while the normal app keeps
  its account-free local library and offers an optional connection under Access & Devices.
- Moved the standalone Server console shortcut beside Account, Notifications, and Settings,
  and fixed all four controls to stay centered and in bounds when the sidebar is minimized.
- Added automatic installed-app reconnection through an OS-vault device token and a
  two-minute, one-use browser handoff. A configured app opens the saved server account
  without a password; if Tailscale or the server is unavailable, it opens the untouched
  local library instead. Signing out revokes the linked native session.
- Rebuilt Access & Devices around a disabled-until-configured PMT Server mode switch,
  a plain-language Tailscale guide, separate pause and forget actions, and an in-server
  return path for reviewing or disconnecting the installed client. Disconnecting or
  stopping a server never deletes accounts, libraries, lists, or backups.
- Removed the ineffective in-app conversion back to local-only mode and the redundant
  authenticated server-account recovery panel. Standalone server lifecycle actions now
  live only in its packaged control script; known-password changes remain in the console.
- Added a host-only `recover-server-account` control for a forgotten server-account
  password. Local access to the private server setup is the verification factor; recovery
  revokes that account's sessions and leaves all users and libraries unchanged.
- Restored the Mac title-bar drag region while any popup is open by giving native windows
  a managed dialog layer that blocks background controls without covering the pywebview
  drag surface; browser dialogs retain their standard modal behavior.
- Rebuilt server sign-in and host-only recovery as a responsive landscape layout, with a
  clear separation between host status, credentials, and recovery confirmation.
- Fixed reopening a running server-hosting desktop app: a duplicate macOS launch now
  activates the existing native window instead of opening its protected loopback address
  in a browser. An intentionally headless server reports a clear conflict and never leaks
  an unusable local URL to Safari.
- Preserved access to personal libraries migrated from older Shared Access releases: when
  the historical server-owner account already owns media, the native app opens that library
  normally and keeps the Server console available. New dedicated server accounts remain
  management-only, and the compatibility path does not move or rewrite existing records.
- Fixed rapid app-icon appearance changes being saved out of order by cancelling stale
  debounced writes, so the newest colour and accent-following choice always wins.
- Updated the release performance fixture for required multi-user ownership, restoring
  the 300/3,000-title benchmark as a functioning tag gate.
- Fixed regular-user password changes appearing inert by reporting progress and errors in
  the visible Account dialog, resetting sensitive fields on failure, and retaining the
  existing all-session revocation after a successful change.
- Fixed native Import & Export actions replacing the macOS/Linux application window with
  raw CSV or JSON: packaged local windows now use the native save dialog, do not navigate
  when that bridge is unavailable, and permit only the local pywebview RPC mechanism that
  those save dialogs require. Shared-server browser CSP remains strict.
- Made Linux desktop bundles select their included Qt backend directly instead of probing
  for unavailable GTK bindings, and suppressed native-only Permissions-Policy warnings
  for directives older embedded engines do not recognize.
- Replaced the generic remote-server identity failure with distinct guidance for an
  unavailable port-8000 server, an incorrectly configured Tailscale hostname, and a
  local-only PMT instance; local libraries can no longer be mistaken for server authority.
- Disabled **Download in App** for unsigned, ad-hoc, or Gatekeeper-unapproved macOS
  installations. Those builds keep **Open the Release**; in-app replacement is offered
  only when macOS accepts the running app's signature.
- Fixed Shared Access startup after converting a packaged local app: loopback health and
  readiness probes remain accepted even when the only public trusted host is the private
  Tailscale hostname, preventing the launcher from timing out and shutting down a healthy
  server.
- Fixed rejected sign-ins remaining on **Signing in…** in Safari by retaining stable form
  references across the asynchronous request and always restoring the submit button.
- Hardened the guided server installer so it waits for container health, leaves Tailscale
  consent visible, verifies the private HTTPS route before opening it, and reports local
  PMT and Tailscale Serve status with plain next-step guidance.
- Added the optional headless PMT Server Beta runtime and version-matched
  multi-architecture container release path, while keeping account-free embedded local
  mode as the default.
- Generalized single-owner authentication into private multi-user accounts with secure
  one-time server-account setup, expiring invitation/recovery tokens, server-account
  controls for regular-user sign-in, and separately revocable browser and native-device
  sessions.
- Added server identity/capability negotiation, short-lived native access tokens with
  rotating refresh tokens, entry record versions, idempotent offline mutation requests,
  structured stale-edit conflicts, a durable device cache/outbox, reconnect handling,
  conflict review controls, and a tenant-scoped change cursor.
- Added catalog-based shared lists with explicit owner/editor/viewer memberships, safe
  collaboration activity and inbox notifications, and per-viewer library state that never
  exposes another person's ratings, notes, tags, history, or ranking evidence.
- Replaced process-only periodic work with a database-leased durable job runner covering
  server backups, release checks, and scheduled integrations, including idempotent
  coalescing, bounded retries, pause/resume, and redacted status APIs.
- Added optional PostgreSQL 15 deployment support, dialect-safe migrations, a private
  Compose database service, `pg_dump`/`pg_restore` recovery archives, and a dedicated CI
  migration/runtime/restore job. SQLite remains the recommended household default.
- Added a guided PMT Server Beta setup bundle with a Mac double-click installer,
  automatic secret generation, Tailscale address discovery, existing-install protection,
  one-time setup-code cleanup, and simple start/stop/status/backup/log controls.
- Split scheduled server disaster recovery from portable exports: server snapshots retain
  password hashes but remove live sessions/tokens, restore into an isolated database for
  verification, apply bounded retention, and record safe administrative audit events.
- Implemented the multi-user foundation with shared catalog-owned episode schedules,
  immutable user ownership on private data, per-user uniqueness and preferences, and a
  fail-closed request principal.
- Scoped libraries, histories, lists, ratings/refinements, imports, integrations, release
  state, statistics, Insights, profiles, calendars, and personal exports to the current
  principal; restricted server operations and filesystem details to the server account.
- Added deterministic single-user backfill and guarded rollback migrations, including
  SQLite cascade protection and a rich synthetic 2.5.2-era preservation fixture.
- Added two-user IDOR/export tests and shared-schedule tests proving that catalog and
  provider episode rows are reused while notes, ratings, artwork, progress, events, and
  preferences remain private.

## 2.5.2 — 2026-08-26

- Fixed modal and subpage help tips so they render in the active dialog layer, disappear
  immediately after the pointer leaves or the dialog closes, and remain reachable by
  keyboard; added browser coverage for title-detail and Metadata Settings help.
- Made a manual **Check library now** release scan cover every eligible verified TV/anime
  entry instead of inheriting the background scheduler's batch cap, so newly added ongoing
  shows can appear in Active Shows without first opening their episode tab.
- Rebalanced the Watching toolbar so Watching, Both, and Plan to watch remain complete at
  constrained desktop widths.
- Isolated explicit `--data-dir` commands and synthetic tests from a developer's real
  `.env` Shared Access mode, preventing local server configuration from contaminating
  disposable libraries and test databases.
- Added detailed native-iOS setup guidance and a consolidated multi-user server,
  recommendation-system, notifications, deployment, authentication, sharing, and provider
  integration implementation plan. These are planning documents and do not enable hosted
  accounts, cloud sync, or recommendation processing in this release.

## 2.5.1 — 2026-08-25

- Completed the French application-shell catalog across primary pages, settings, imports,
  metadata, rankings, Insights, accessibility labels, and Shared Access; added regression
  coverage for future French copy while keeping Simplified Chinese explicitly beta.
- Updated the private Tailscale Serve workflow with current CLI syntax, a reversible Mac
  and iPhone browser test, and a roadmap decision that future native Apple work prioritizes
  iCloud/CloudKit while Shared Access becomes an advanced secondary option.
- Recoloured the packaged PMT icon to `#111010` with `#24CD09` lettering, added compact
  icon colour controls with an accent-following option, and added an optional full-colour
  poster blend for media tiles.
- Added an honest interactive release-era alternative when Insights has no watch dates,
  and tightened ranking badges so their position numbers are smaller and clearer.
- Refreshed already-complete TV and anime metadata when a newly available provider can
  add a verified episode-schedule identity, and made episode support read the
  provider-neutral identity ledger directly.
- Fixed Rankings, Watching, and Library controls at half-window and narrow sizes, with
  separate non-overlapping filter rows and the complete Plan to watch label.
- Replaced the long project overview with a concise setup-and-preview README and current
  synthetic screenshots demonstrating the library, rankings, insights, and appearance
  system.

- Generalized metadata access behind a capability registry, added keyless TVmaze and
  Kitsu support plus limited Wikidata enrichment alongside Jikan and optional TMDb, and
  isolated partial provider failures so one unavailable catalog no longer discards
  successful results.
- Added conservative cross-provider result clustering, external-identity persistence,
  normalized source snapshots, per-field provenance, and provider-neutral artwork and
  episode-schedule selection without changing user-owned ratings, notes, or history.
- Simplified Lists into sortable summaries with Library-style detail pages, optional
  navigation pinning for up to five lists, and clearer distinction between Watching and
  Active Shows.
- Replaced the List title multi-select with an accessible live-search picker, moved pinned
  lists below Quick Add, preserved episode-list position during single-episode changes,
  and fixed clipped Watching scope labels.
- Removed unavailable provider setup cards from release-facing Settings, added sparse
  metadata corroboration during refresh, allowed the official keyless-provider artwork
  origins, and strengthened metadata and artwork coverage across the release sample set.
- Improved episode Insights by treating a completed show's known episodes as watched
  until the owner records explicit episode progress, while continuing to avoid invented
  watch dates.
- Added a tested, versioned logical mobile-sync contract and architecture decision record
  for future iOS/CloudKit work. No Apple dependency, entitlement, public sync endpoint, or
  change to the desktop release process is included.
- Rebuilt Insights around shared URL-restored filters, honest dated/undated coverage,
  previous-period comparisons, an accessible activity timeline, rating and genre
  distributions, library breakdowns, deterministic callouts, and title drill-downs.
- Simplified the main workspace with a three-way Watching scope, compact Active Shows
  schedule link, searchable Library toolbar, full live-filtered Rankings, a master-detail
  episode browser, and a consolidated Metadata settings page.
- Added a device-local optimized workspace background image with opacity and optional
  colour tint controls, faster top-layer save notifications, calendar detail selection,
  and more balanced appearance controls.
- Replaced accent presets with one persistent custom color, compacted General settings,
  and made season episode drawers use the full release-panel width at normal and narrow
  Mac window sizes.
- Added the additive provider-neutral integration foundation: external identities,
  connections, protected credential references, cursors, run/event history, conflicts,
  webhook credential hashes, replay protection, backoff/pause, and a privacy-first
  integration persistence foundation. Real provider adapters remain gated and unavailable
  and are not presented as setup choices in public Settings.
- Added a packaged-macOS **Download in App** update path with visible progress, SHA-256,
  bundle identity/version and code-signature checks, rollback-safe detached replacement,
  and relaunch; other environments continue to open the GitHub release.

## 2.1.6 — 2026-08-22

- Made season episode lists open as compact, toggleable extensions attached to the
  selected season card, with a right-side desktop layout and immediate narrow-screen
  stacking.
- Reorganized title dates into one vertical column and personal rating/view count into
  a second column, retaining only the explicit minus and plus controls for numeric input.

## 2.1.5 — 2026-08-22

- Made metadata resolution accept compatible single-result aliases and clearly dominant
  small result sets while retaining year/type conflict and duplicate-identity safeguards;
  enrichment now reports aggregate skip reasons instead of unexplained failures.
- Preserved Library page and scroll position after edits, added visible Library refresh
  state, made completion banners dismissible/transient, and aligned compact sort/show
  controls and larger dashboard headings.
- Reworked title details with immediate provider facts, explicit numeric steppers, compact
  status/date controls, a wider artwork-connected layout, and season cards that open an
  animated episode drawer.
- Added expandable/icon-only and reversible sidebar navigation preferences, compacted
  General settings, fixed modal help bubbles, and merged Privacy with About.
- Added safe round-trip import for PMT's own Obsidian vault ZIP format; arbitrary vault
  notes and unsupported media types are never guessed into the movie/TV/anime library.

## 2.1.3 — 2026-08-21

- Added bounded popularity tie-breaking for up to four exact or strongly title-similar
  metadata results, while retaining year compatibility and manual review for weak matches.
- Added TMDb TV/movie fallback results to anime-scoped searches when configured, preserving
  the library entry's anime classification when one of those matches is attached.
- Ranked anime-native providers before TMDb fallback results and carried provider popularity
  evidence through search normalization for clearer manual and automatic resolution.

## 2.1.2 — 2026-08-21

- Fixed post-import metadata processing so exact, unambiguous title/year matches are
  automatically verified while ambiguous or fuzzy matches remain in the review queue.
- Scoped unresolved-title searches to their imported media type, preventing movie and TV
  matches from obscuring anime-provider results and avoiding unnecessary provider traffic.
- Clarified import and metadata controls to distinguish safe automatic matching from manual
  confirmation, while retaining Jikan fallback and AniList's public-build restrictions.

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
