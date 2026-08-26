# Integrations

Personal Media Tracker's integration layer is local-first infrastructure for optional
provider connections. Version 2.2 introduces the provider-neutral foundation, but does
not present unfinished adapters as setup choices in public Settings. A provider becomes
visible and configurable only after its adapter and offline contract tests ship together.

## Privacy boundary

Every connection, recurring pull, webhook, notification destination, and outbound change
is opt-in. The integration layer may handle verified title identities, viewing history,
ordinary personal ratings, status, and episode progress when a provider explicitly
supports them. It does not send PMT notes, tags, technical scores, rubric answers,
comparisons, confidence values, or private reflections.

Credentials never enter SQLite. Connection rows contain only a random secret namespace;
the credential itself uses PMT's existing protected secret store:

- a user-only local configuration file by default;
- the operating-system credential vault only after explicit opt-in; or
- a namespaced `WATCHTRACKER_SECRET_...` environment override for server deployments.

Credentials are excluded from backups, portable exports, API responses, run/event logs,
diagnostics, and update archives. Disconnecting clears the registered credential fields.

## Architecture

Adapters declare only capabilities they implement, such as `pull_history`,
`pull_ratings`, `receive_playback_event`, or `send_notification`. Adapters translate a
provider's wire format into normalized records. The shared coordinator—not an adapter or
button handler—owns identity resolution, idempotency, cursors, short database
transactions, failure backoff, pausing, conflict records, and safe audit summaries.

Migration `0009` adds:

- provider-neutral external identities while retaining the existing TMDB, AniList, and
  MyAnimeList compatibility columns;
- connection configuration and opaque secret references;
- per-capability cursors and provider versions;
- run/event ledgers without raw provider payload retention;
- visible integration conflicts; and
- hashed, revocable webhook-credential records for the future inbound contract.

New and updated catalog records mirror their verified compatibility IDs into the identity
ledger. Resolution prefers a stable ID. The only fallback is one exact normalized
title/year/type match. Fuzzy titles, popularity, and provider list position never attach an
integration event. Contradictions and unmatched items enter review. A soft-deleted title
remains a tombstone and is not silently recreated.

## Run and conflict semantics

- Only one run for a connection/capability/direction can be active. Concurrent triggers
  coalesce onto the active run.
- Network work completes before a short atomic SQLite write. A cursor advances only after
  that write commits.
- Provider event IDs are preferred for replay protection; otherwise PMT hashes the
  connection, identity, event kind, target, and payload digest.
- Repeat deliveries are recorded as skips rather than duplicated mutations.
- Retry guidance is retained, delays use bounded exponential backoff, and a connection is
  automatically paused after five consecutive failures.
- Run and event views expose aggregate counts and safe summaries only. Raw payloads and
  bearer credentials are not retained.
- Outbound directions remain off by default. Technical ranking data is never an outbound
  capability.

## Provider order and prerequisites

| Slice | Initial direction | Main prerequisite | Current 2.2 state |
| --- | --- | --- | --- |
| Generic PMT playback contract | Inbound | Scoped webhook token and reachable PMT URL | Foundation only |
| Jellyfin | Inbound | Jellyfin Webhook plugin and selected user | Foundation only |
| Trakt | Export import, then pull | Export file or registered OAuth application | Foundation only |
| AniList | Pull | AniList authorization; annual reauthorization | Foundation only |
| Simkl | Pull | Simkl authorization | Foundation only |
| MyAnimeList | Pull | Official MAL API client; Jikan is metadata-only | Foundation only |
| Plex | Inbound | Plex Pass and reachable webhook URL | Foundation only |
| Emby | Inbound or bounded pull | Compatible server notification mechanism | Foundation only |
| Kodi | Inbound | Generic endpoint automation | Foundation only |
| Apprise API | Outbound notifications | Reachable Apprise API instance | Foundation only |

Pull and dry-run preview ship before recurring sync. Provider mutation is a separate gate
and stays disabled by default. “Two-way” will mean explicit field-level direction and
conflict handling, never blind last-write-wins.

## Local-only and Shared Access

Local-only mode listens on loopback. A player on the same Mac can eventually call an
enabled inbound endpoint, but a NAS or media server cannot call `127.0.0.1` on this Mac.
Remote webhooks require the existing authenticated Shared Access configuration and a URL
the provider can actually reach. PMT never opens network access automatically. See
[Self-hosting and shared access](SELF_HOSTING.md).

Scheduled work runs only while PMT is open. The foundation does not require Docker,
Redis, a background worker, a provider plugin written by PMT, or a cloud relay.

## Recovery

Pausing retains configuration and history while stopping scheduled work. Resume only
after a successful connection test. Disconnecting removes the connection, its cursor/run/
event/conflict records, webhook credentials, and registered secrets; it does not remove
library titles or viewing history already accepted through an explicit sync.

Database migration continues to create a pre-migration SQLite backup. Downgrading from
`0009` removes only the integration foundation tables and leaves the compatibility ID
columns and core library intact. Restore or move a complete PMT installation with the
Everything archive; reconnect providers afterward because credentials are deliberately
not portable.
