# Personal Media Tracker v2.6.0

This release stabilizes daily tracking, portable data, notifications, and desktop
packaging. macOS is the recommended native build. Windows and Linux native packages now
use a verified packaged Qt runtime but remain previews pending wider hardware testing;
Docker/browser mode is recommended on those platforms. PMT Server remains a separate beta
and no new server package is published with this release.

## Tracking and history correctness

- Following a series updates its media tile immediately and creates one clear upcoming
  in-app release alert when schedule data is available.
- Episode and favorite controls update only the affected tile, avoiding stale counters and
  unnecessary full-library refreshes.
- Viewing cycles now distinguish initial watches, rewatches, episode replays, bookmarks,
  aggregate provider claims, and durable completion occurrences.
- Short playback, pauses, and aggregate episode counts no longer manufacture watched
  history. Duplicate completions merge their provenance instead of creating rewatches.
- Manual undo and list removal use tombstones so an older portable snapshot cannot silently
  restore deleted history or memberships.

## Portable data and integrations

- Added the `pmt.platform-sync` v2 contract with deterministic records, stable origin IDs,
  per-record versions, tombstones, unknown-date preservation, and an idempotent import
  ledger.
- Portable snapshots explicitly exclude credentials, sessions, raw provider payloads,
  runtime caches, delivery state, and private development tools.
- Provider progress and playback now pass through the same reviewable reducer used by
  manual history. A completion accompanied by a repeat count is counted only once.
- Notification rules, optional Apprise delivery, provider authorization, read-only tracker
  adapters, and media-server playback adapters remain guarded integration previews. They
  are not a promise of production provider availability.

## Desktop and Docker

- Added an account-free, loopback-only Docker preview plus an optional official Apprise API
  sidecar. See `docs/DOCKER.md` before importing important data.
- Windows and Linux native packages now include and explicitly verify their Qt backend;
  Linux also uses safer software-rendering defaults for broader driver compatibility.
- Native dialogs center consistently instead of opening partly outside the usable window.
- PMT Server Beta setup bundles and container publication are disabled unless explicitly
  enabled after separate soak testing.

## Safety notes

Keep a current **Everything archive** before upgrading. The database migration is additive,
but portable exports and backups remain the recovery boundary for important libraries.

Unless a macOS asset explicitly says it is Developer ID signed and notarized, macOS may
require manual approval in **System Settings → Privacy & Security**. This cannot be safely
bypassed in application code.
