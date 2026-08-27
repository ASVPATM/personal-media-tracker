# Multi-user server, recommendations, notifications, and integrations plan

Status: orders 1–12 shipped in v2.5.3. The v2.5.4 stability release adds the local
notification center and release-event groundwork without claiming external delivery;
orders 13–25 remain planned under the revised personal-app/server split below. PMT Server
and PostgreSQL remain beta while they receive real-install soak time, although their
automated migration, runtime, backup, restore, container, and release gates now pass.
SQLite remains the recommended server default.

Prepared: 2026-08-26; architecture and order revised on 2026-08-27
Baseline: Personal Media Tracker 2.5.4, FastAPI, SQLAlchemy, Alembic, SQLite/PostgreSQL,
the vanilla web UI, and the separate PMT Server Setup Beta distribution

Implementation note: the ownership schema, shared schedule cache, request principal,
tenant-scoped services/exports, threat model, ADRs, and synthetic migration/isolation
fixtures are in place. Multi-user password accounts, headless bootstrap, invitations and
recovery, revocable browser/native sessions, the server artifact, checked recovery,
connection onboarding, OS-vault tokens, a durable client cache/outbox, entry/list conflict
handling, catalog-based shared lists, collaboration activity/inbox, database-leased jobs,
and optional PostgreSQL deployment are implemented. The Python remote client remains a
security/compatibility reference for the beta server connector; it is not the template for
the future Swift/iCloud personal application.

## Current implementation checkpoint

This document is now a forward plan from the public v2.5.4 tag, not a description of work
still expected in the 2.5.2 codebase.

| Area | v2.5.4 state | Remaining work |
| --- | --- | --- |
| Orders 1–4 | Released: architecture decisions, catalog-owned schedules, immutable user ownership, request principals, and tenant-scoped services/exports. | Continue expanding the hostile two-user route matrix whenever a new domain is added. |
| Orders 5–7 | Released in PMT Server Beta: password accounts, dedicated server account, invitations/recovery, revocable sessions, headless setup, SQLite backup/restore, retention, and audit records. | Field-soak upgrades/recovery on real always-on hosts; keep the normal desktop account-free. |
| Orders 8–9 | Released in PMT Server Beta: API capability/identity checks, saved server profiles, OS-vault device sessions, one-use browser handoff, local fallback, durable cache/outbox, idempotency, and conflict handling. | A native Swift client remains future work; the Python client is the reference implementation. |
| Orders 10–11 | Released in PMT Server Beta: catalog-based shared lists, owner/editor/viewer roles, activity/inbox events, and database-leased jobs. | Extend the existing inbox and scheduler instead of creating parallel systems for recommendations or integrations. |
| Order 12 | Released as PostgreSQL beta: dialect-safe migrations/runtime, Compose override, `pg_dump`/`pg_restore`, and containerized CI. | Keep the beta label until real-install upgrade/restore soak and operator documentation are proven outside CI. |
| Notifications groundwork | The main navigation now has one Notification center combining release events and the user-scoped collaboration inbox. | Order 13 adds rules, endpoint secrets, a transactional delivery outbox, quiet hours, and optional Apprise delivery. |
| Integration groundwork | Per-user connections, protected secrets, cursors, runs, idempotent events, conflicts, retry/backoff, provider definitions, and scheduled jobs exist. | No advertised provider has a live production adapter yet; OAuth, user bindings, and provider fixtures remain orders 14–19. |
| Recommendations | Not started intentionally; the normal package has no recommendation-system dependency or recommendation tables. | Deferred to orders 20–23 so notification and import/playback integrations can stabilize first. |
| OIDC/social login | Not started. | Orders 24–25 remain last, after server-account recovery and isolation have real-world soak time. |

### Product decisions incorporated after the original plan

- The normal desktop package never becomes a household server and never exposes the
  Server console. Hosting and lifecycle controls belong only to the separate PMT Server
  Setup Beta package.
- The personal desktop/iOS product and PMT Server Beta are now separate product paths.
  Existing experimental remote-server client code remains compatibility-only; new
  personal-app work must not make a server account or server availability a prerequisite.
- PMT has two product-facing server account types: the dedicated **server account** and a
  **regular user**. The database values `admin` and `member`, `require_admin` policy name,
  and `/api/v1/admin/*` route prefix remain internal compatibility terms; they do not
  introduce a third administrator persona.
- A fresh dedicated server account has no personal media library. It manages people,
  shared metadata fallback, readiness, jobs, and backups. Historical owner libraries are
  preserved only for migration compatibility.
- A normal desktop starts in its untouched, account-free local library. Account and Server
  console navigation stay hidden. Future personal-device synchronization targets
  CloudKit/iCloud, not a mandatory PMT Server profile.
- **Personal Tailscale access** is a separate, account-free way to reach the currently open
  local desktop library. It is not PMT Server mode, does not create users, and is not an
  authoritative synchronization backend.
- The already-built saved PMT Server connection/session code remains an experimental beta
  compatibility path while the product split is completed. Do not extend it into the
  default personal-app or future iCloud onboarding flow.
- Metadata credentials resolve at the narrowest scope available: an individual credential
  is encouraged first, while a server-account credential may provide an optional shared
  fallback and keyless providers remain available. Secrets never enter user exports.
- v2.5.3 is the completed stability checkpoint for orders 1–12. Notifications and
  integrations now precede recommendation-domain work in the next development lines.

## Executive recommendation

v2.5.3 evolved the former authenticated Shared Access work into an optional multi-user
home server. The server has its own headless install artifact while remaining a runtime
profile of the same FastAPI/domain codebase rather than a separately developed service.
PMT does not copy Yamtrack's Django architecture or make an account mandatory for the
desktop application.

The codebase now supports two deliberately separate products, with a third personal-sync
backend planned later:

1. **PMT Personal, local mode** — the current account-free desktop experience. A built-in
   local profile owns the data; the app binds to loopback; no login is shown. Personal
   Tailscale access exposes this same running library privately and creates no account or
   second database.
2. **PMT Server Beta** — a separate, optional always-on installation with its own database,
   accounts, browser UI, jobs, backups, and server console. It is not started, stopped, or
   administered by the normal personal application.
3. **PMT Personal, iCloud mode (future)** — native Apple clients use one CloudKit-backed
   personal library. This is an alternative authority selected through an explicit
   migration, not a mirror of a local or PMT Server database.

The release contains two artifacts with the same version and migration head: the normal
Personal Media Tracker desktop package and a headless **PMT Server Beta** image/package.
This is packaging and process separation, not a source-code fork. Shared domain/provider
contracts can remain in one repository, but release UI and lifecycle stay separate. The
normal desktop always has a usable embedded local library; its future sync work targets
iCloud. PMT Server remains independently usable through its authenticated browser product.

Accepted boundary after the 2026-08-27 revision: the normal application presents its
personal local library regardless of PMT Server state. Personal Tailscale reachability is
only a private route to that currently running local library and never determines whether
data exists. The standalone server account manages server people, metadata fallback,
backups, and readiness inside the PMT Server product. Stopping it makes its browser
accounts temporarily unavailable but leaves its database and backups intact. Existing
saved-server profiles are retained for backward compatibility while their eventual
migration or retirement is designed; they are not the foundation for iCloud sync.

This preserves PMT's main differentiators—private/local operation, detailed personal
ratings, ranking refinement, metadata reliability, and user-controlled data—while adding
the household/server capabilities that make Yamtrack attractive.

Recommendations should become a first-class PMT domain, but the advanced recommendation
prototype must not be merged as a second application or made a required desktop
dependency. PMT should bake in the recommendation contracts, a lightweight deterministic
baseline, the user interface, explanations, feedback, and evaluation records. The
embedding/collaborative engine should be extracted into an optional, replaceable local
worker or Docker service. This lets PMT use a stronger engine where it makes sense without
forcing Streamlit, NumPy, SciPy, scikit-learn, sentence-transformers, model downloads, or
pgvector into every desktop or future iOS installation.

The required sequence through ownership, authorization, shared lists, and durable jobs is
complete. New notifications and provider adapters come next and must run against an
explicit authority: the built-in local principal in PMT Personal or a tenant principal in
PMT Server. Recommendations follow those integrations. Adding a shortcut/global owner in
a later adapter would be a regression.

## What PMT already has

PMT is not starting from zero:

| Existing foundation | Current state | Reuse |
| --- | --- | --- |
| Remote access | Account-free Personal Tailscale access can expose an open local app; saved PMT Server profiles use HTTPS, identity checks, device sessions, and local fallback. | Keep these two paths visibly separate and fail closed on host/proxy/identity errors. |
| Authentication | Dedicated server account plus regular users, Argon2id hashes, browser/native sessions, expiry/revocation, invitations/recovery, CSRF, throttling, and Secure/HttpOnly cookies. | Add OIDC only after the local account model has field soak; do not add login to local mode. |
| Docker | Non-root multi-architecture container, guided setup bundle, SQLite/PostgreSQL Compose, health checks, and optional Caddy profile. | Field-soak recovery/upgrades before removing the server/PostgreSQL beta labels. |
| Release tracking | Catalog-owned normalized schedules, per-user subscriptions/viewings/events, calendar, scheduler leases, and deduplication. | Add user-configurable delivery rules in order 13. |
| Integration foundation | User-owned provider definitions, secret references, cursors, runs, idempotent events, conflicts, retry/backoff, audit summaries, and durable scheduling. | Add OAuth callbacks, server-to-remote-user bindings, fixture-backed live adapters, and disconnect/reconnect flows. |
| Provider identities | TMDb, TVmaze, AniList, MAL, Kitsu, and other external IDs can be attached to catalog records. | Resolve imported/playback events by stable IDs before titles. |
| Lists | Catalog-based personal/shared lists, owner/editor/viewer memberships, activity, notifications, and pinned navigation. | Extend only after real household beta feedback. |
| Recommendation signals | Personal ratings, status, history, tags, normalized metadata, advanced-rating evidence, and explainable ranking infrastructure. | Add a separate recommendation contract and schema; no recommendation implementation is currently bundled. |
| Portability | Per-user portable exports, Everything archives, provider-neutral logical snapshots, migrations, integrity checks, and separate server disaster recovery. | Extend export/deletion policy explicitly for each new recommendation, notification, and integration table. |

The most important baseline constraints addressed by orders 1–12 were:

- the one-to-one catalog/watch-entry relationship and globally unique entry catalog ID;
- episode schedules attached to a person's entry rather than the shared catalog;
- globally named, entry-based lists without explicit memberships;
- private roots without immutable user ownership;
- one owner session treated as every authorized request; and
- SQLite-only disaster recovery despite a database URL seam.

Migrations 0012–0015 and the tenant-scoped services now remove those constraints. They
remain documented here because they explain the chosen migration order and rollback
guards; they are no longer statements about the release-candidate schema.

## Product and compatibility contracts

These constraints should be accepted before implementation:

- Local mode remains the default and requires no account, network, external identity
  provider, Redis, or PostgreSQL.
- Server mode remains self-hosted. PMT does not operate a hosted account service.
- Metadata and provider schedule caches may be shared by all server users. Ratings,
  statuses, history, notes, tags, refinements, integrations, credentials, and notification
  preferences are always private to one user unless a specific list is shared.
- Sharing a list never shares private notes, ratings, ranking evidence, watch history, or
  integration credentials.
- Existing pre-multi-user databases migrate to one immutable local principal without
  changing title IDs, ratings, histories, or dates. A historical owner account is
  preserved for compatibility but does not make the normal desktop a server console.
- Existing clients and the desktop UI continue to work during staged development. New
  server behavior stays behind capability/configuration gates until isolation tests pass.
- Every library chooses one authoritative backend at a time: embedded local PMT, a
  standalone PMT Server database, or a future CloudKit-backed personal library. Two
  authorities never accept writes for the same library without a separately designed
  migration/reconciliation system.
- The standalone server package is the only supported way to create or operate PMT Server.
  The personal desktop cannot toggle itself into a server host. Its existing remote-server
  connector is compatibility-only and must not gain new personal-app dependencies.
- Product UI exposes only a dedicated server account and regular users. Internal
  `admin`/`member` values and admin-prefixed routes are authorization implementation
  details and must not leak back into onboarding language.
- External imports are pull-only first. Push/synchronization is a separate later feature
  because it can overwrite data in another service.
- Provider deletion never silently deletes PMT history. It creates a reviewable conflict
  or detaches the remote link.
- Recommendations are advisory. Generating, dismissing, or evaluating a recommendation
  never changes a library entry unless the user explicitly chooses an action such as
  **Add to list**, **Plan to watch**, or **Not interested**.
- PMT remains the only source of truth for the library. A recommendation engine receives a
  versioned, minimum-necessary read model and returns catalog identities and evidence; it
  does not edit PMT tables or maintain a competing canonical CSV.
- The standard recommendation engine remains available without a model download. Advanced
  local recommendations are optional per installation and opt-in per user on a shared
  server. No user is required to expose private history to another process or provider.
- Recommendation histories, profiles, feedback, and evaluation data are private user data.
  Shared lists do not become shared training data, and household collaborative learning is
  out of scope unless every contributing user later gives explicit consent.
- A remote recommendation provider, if ever added, must disclose exactly which fields
  leave the server and require separate user consent. Local operation is the default.
- Yamtrack is AGPL-3.0 and PMT is MIT. Feature ideas and public protocols can be studied,
  but Yamtrack code, templates, test fixtures, assets, and prose must not be copied.

## Target architecture

```text
PMT Personal                                  PMT Server Beta (separate install)
Mac app today                                authenticated browser clients
  |                                                     |
embedded FastAPI + SQLite                      HTTPS / Tailscale / reverse proxy
  |                                                     |
Personal Tailscale (remote view only)          headless FastAPI + jobs + auth
  |                                                     |
future native iOS/macOS ---- CloudKit          SQLite or PostgreSQL
          (one personal authority)              (one server authority)
                 \                               /
                  shared provider contracts
             metadata · imports · playback · alerts
                      |                    |
                  Apprise adapters    recommendation contract
```

The two products share tested domain contracts and provider adapters, not a live database
or an implicit sync relationship. Browser clients of PMT Server never open its SQLite
file. Personal Tailscale access routes to the already-running local app and does not turn
that app into PMT Server. Future CloudKit synchronization must be designed independently
of server sessions, caches, and outboxes.

### Process and distribution model

Use one source tree and one schema migration history with explicit runtime roles:

- **`pmt local`**: current desktop behavior; embedded loopback server, local database,
  account-free local principal
- **`pmt server`**: headless authoritative service used by the standalone package; no
  personal native window, dedicated server-account bootstrap, authentication, jobs,
  integrations, backups, and a browser-based server console
- **existing remote client profile**: frozen beta compatibility surface, not the target
  personal/iCloud architecture; maintain security and data safety but do not make new
  personal features depend on it
- **future native personal client**: Swift UI over local/CloudKit repositories conforming
  to the same domain contracts, with no Python runtime or PMT Server account requirement

Ship the first server artifact as a multi-architecture OCI image plus Docker Compose for
Linux/NAS/home-server hosts. Add native `launchd`, `systemd`, Windows-service, or NAS app
packages only when measured demand justifies their separate lifecycle and support cost.
All artifacts must report the same PMT semantic version, API compatibility version, and
Alembic migration head.

- **SQLite profile:** one application process, in-process scheduler/worker, WAL mode,
  busy timeout, and local-volume storage. Appropriate for a person or small household.
- **PostgreSQL profile:** application plus PostgreSQL, with the option to run one separate
  worker. PostgreSQL support does not automatically authorize multiple web workers; all
  leases and integration locks must first become database-backed.
- Redis should not become a mandatory dependency. Add it only if measured requirements
  later justify distributed pub/sub or a larger job queue.

## Data ownership and schema design

### Shared catalog layer

Migrations 0012–0013 keep these server-global because they describe media rather than a
person's relationship to media:

- `catalog_items`
- `external_identities`
- `catalog_metadata_sources`
- provider metadata cache/provenance
- `season_records` and `episode_records`, now owned through `catalog_item_id`

`CatalogItem.entry` is now `CatalogItem.entries`. The global uniqueness of
`WatchEntry.catalog_item_id` was replaced with a uniqueness rule on
`(user_id, catalog_item_id)`. A deleted entry is retained/resurrected rather than creating
multiple rows for the same user's title.

Schedule ownership is now split as follows:

- `SeasonRecord.catalog_item_id -> catalog_items.id`
- `EpisodeRecord` remains under a season
- `SeriesTrackingSubscription` remains per-user through `entry_id`
- `EpisodeViewing` remains per-user through `entry_id`
- `ReleaseEvent` remains per-user because read/dismiss/delivery state is personal

This lets one provider schedule fetch serve every subscribed user without moving globally
unique season/episode records between their entries.

### User and authentication tables

v2.5.3 implements:

- `user_accounts`
  - UUID primary key
  - normalized unique username
  - optional unique normalized email
  - display name
  - nullable password hash (OIDC-only accounts are allowed)
  - internal role: `admin` for the one dedicated server account or `member` for regular
    users; UI never presents a separate administrator account type
  - state: `invited`, `active`, `disabled`
  - locale, timezone, created/updated/password-changed timestamps
- `user_sessions`
  - `user_id`, token hash, CSRF hash, expiry, last seen, revoked timestamp
  - optional safe device label and user-agent hash, never raw browser history
- `account_invitations`
  - hashed single-use token, creator, role, expiry, accepted timestamp

Orders 24–25 later add `external_auth_identities` and `oauth_login_states` with stable
`(issuer, subject)` identity and short-lived state/nonce/PKCE data. Email is never
sufficient identity proof.

Migrate a historical `OwnerAccount` into the compatibility local principal without moving
its media. A fresh standalone server creates one dedicated server account whose internal
role is `admin`; regular accounts use `member`. Existing sessions may be migrated only
when their owner is unambiguous, otherwise revoke them and require one clearly explained
sign-in after upgrade.

### User-owned domain records

Migration 0013 added `user_id` directly to existing ownership roots:

- `watch_entries`
- `media_lists`
- rating comparisons and refinement runs
- import previews and import history
- integration connections
- collaboration inbox records
- calendar-feed tokens
- per-user settings that should follow a login

Future notification endpoint/rule and recommendation records follow the same ownership
rule. Child records may derive ownership from an entry or connection, but service methods
still receive a `Principal` and validate the root owner. For especially sensitive future
tables, prefer composite foreign keys containing `user_id` so an implementation error
cannot connect one user's child row to another user's parent.

Global uniqueness was replaced with tenant/owner-scoped rules:

- list name: `(user_id, name)` with normalized validation in the service
- viewing source key: `(user_id, source, source_key)`
- rating pair: `(user_id, entry_low_id, entry_high_id)`
- refinement active run/draft: user-scoped
- calendar tokens and integration dedupe keys: owner/connection scoped

### Shared-list model

Migration 0015 replaced `MediaListItem.entry_id` with `catalog_item_id`. A shared list is a
collection of titles, not a collection of the owner's private tracking rows.

It added:

- `media_list_memberships(list_id, user_id, role, invited_by, accepted_at)`
  - role: `owner`, `editor`, or `viewer`
  - one owner; owner cannot be removed without explicit ownership transfer
- `media_list_items(list_id, catalog_item_id, added_by_user_id, position, note?, added_at)`
  - the optional list-item note is shared and must be visibly separate from private entry
    notes
- `media_list_activity(list_id, actor_user_id, action, safe payload, created_at)`
  - bounded retention for collaboration history and notifications

When rendering a shared item, left-join the current user's `WatchEntry` to show their own
status/rating. If they do not track it, show “Add to my library.” Never fall back to the
owner's entry.

## Principal, authorization, and API isolation

v2.5.3 uses one request-scoped `Principal` abstraction:

```text
Principal
  user_id
  role
  authentication_method
  session_id
  is_local_mode
```

- In local mode, middleware supplies the migrated/built-in local principal without a login.
- In server mode, middleware resolves a user session and supplies its principal.
- Route handlers never accept an owner/user ID to decide whose private records to access.
- Service constructors take `Principal` or an explicit trusted `user_id` supplied only by
  the scheduler/server-account layer.
- Every list operation passes through a policy function such as
  `require_list_permission(principal, list_id, "edit")`.

The central `authorization.py` policy module enforces these minimum permissions rather than
repeating conditional checks in UI handlers:

| Resource/action | Regular user | List editor | List owner | Server account (internal `admin`) |
| --- | --- | --- | --- | --- |
| Own library/settings/integrations | Full | Full | Full | No personal library on a fresh standalone server |
| View shared list | If member | Yes | Yes | Only if member or support mode is explicitly audited |
| Add/remove shared list items | No | Yes | Yes | Not implicitly |
| Manage memberships | No | No | Yes | Emergency audited action only |
| Invite/disable server users | No | No | No | Yes |
| Read another user's ratings/notes/history | No | No | No | No normal UI/API path |

The internal `admin` role means the dedicated server account, not silent access to private
diaries. If an emergency data-repair feature is ever required, make it explicit, audited,
and disabled by default.

### Concurrent edits

Multiple devices introduce lost-update risk even with one user. v2.5.3 adds integer
versions to `WatchEntry` and `MediaList` and requires expected versions through the sync
contract. A stale edit returns `409 conflict` with current safe state so the client can
reload, rebase, discard, or deliberately retry. Add versions to future membership-sensitive
records when their mutation contract needs independent concurrency.

Start with refetch-on-success and bounded polling. Later, add Server-Sent Events that carry
only invalidation messages (`entry_changed`, `list_changed`, `notification_added`) and make
the client refetch authorized data. Do not put notes or credentials in event payloads.

## Accounts and login flows

### Local credentials

v2.5.3 generalized the historical owner login for the standalone server:

- first server setup creates the dedicated server account
- registration is invite-only; finding or reaching a server never permits open signup
- invitations expire and are stored only as hashes
- password minimum remains at least 12 characters with Argon2id hashing
- login errors remain generic and throttled by account/IP-derived keyed hashes
- password changes revoke that user's sessions; disabling a regular user revokes that
  user's sessions and scheduled integrations
- session UI lists device label, last seen, expiry, and revoke button

Email remains optional for a local household server. A regular user can receive a
short-lived recovery invitation from the server account. Recovery of the server account
itself is a host-local control-script action that revokes its sessions; it is not a
guessable security-question or ordinary browser flow.

### OIDC and social authentication

Do **not** add `django-allauth` to PMT. It is tied to Django's ORM, middleware, sessions,
admin, and templates; adopting it would mean a backend rewrite for one feature family.

Use a FastAPI/Starlette-compatible OAuth/OIDC client such as Authlib behind a small
`IdentityProviderAdapter`. Implement one generic OIDC provider first:

- configuration is server-account/environment owned: issuer/discovery URL, client ID,
  protected client secret, scopes, and display name
- authorization-code flow with state, nonce, PKCE, exact callback URL, and short expiry
- validate issuer, audience, signature, nonce, and token times
- map only stable `(issuer, sub)` to a PMT identity
- default auto-provisioning off; an existing invitation or explicit account link is needed
- linking requires a current session plus password/identity reauthentication
- unlinking the last login method requires setting another method first

Generic OIDC lets self-hosters connect Authentik, Authelia, Keycloak, Pocket ID, or another
identity broker, which can itself expose many social providers. After OIDC stabilizes,
optional direct presets can be added for:

1. Google OIDC
2. GitHub OAuth 2.0
3. Discord OAuth 2.0

“100+ providers” should not be a PMT acceptance criterion. Each direct provider still
requires an application registration, callback URL, secret management, claim mapping,
terms review, and regression testing. Generic OIDC plus a few well-supported presets gives
most of the benefit without turning authentication into the entire project.

## Central server and deployment

### Implemented remote-access separation

v2.5.3 keeps the HTTPS, exact-host, trusted-proxy, Tailscale Serve, Caddy, readiness, and
fail-closed startup checks, but separates three concepts that were previously conflated:

1. the normal account-free local desktop;
2. optional Personal Tailscale access to that currently open desktop; and
3. an optional saved connection to a separately installed PMT Server Beta.

The normal app cannot host or administer PMT Server. Its PMT Server switch is a connection
state that activates only after a standalone server is verified; Personal Tailscale access
has its own setup and does not require a PMT username or password.

The server installation has no dependency on a logged-in desktop session or open native
window. Its first browser visit performs one-time server-account setup using either a
single-use bootstrap token printed to the host console or a host-local setup endpoint.
After bootstrap, the setup credential is invalidated. Service status, migrations,
capabilities, backup health, and API compatibility are visible without exposing secrets.

Settings are split by scope:

- **server account in the standalone console:** origin/hosts/proxies, database,
  registration policy, provider application credentials, job intervals, and backup policy
- **user account:** locale, timezone, content defaults, integrations, notification rules
- **device/local storage:** theme, sidebar state, density, local-library settings, Personal
  Tailscale access, and the saved remote-server profile
- **shared server metadata:** optional server-account TMDb credential and keyless metadata
  providers, used as fallback; an individual credential remains preferred when configured

### SQLite profile

- remains the default Compose and desktop database
- exactly one application process owns the local volume
- suitable for a small trusted household
- never place the database on NFS/SMB/Dropbox/iCloud/Syncthing
- retain online SQLite backups and integrity checks

### PostgreSQL profile

The `server` dependency extra now includes `psycopg[binary]`. An explicit
`WATCHTRACKER_DATABASE_URL_OVERRIDE=postgresql+psycopg://...` selects PostgreSQL, while
engine setup and migrations branch only where the dialect actually differs. CI provisions
a temporary PostgreSQL service and exercises upgrade, downgrade/upgrade, runtime writes,
custom-format dump verification, and restore into an empty database.

Offer either a Compose override or profiles:

- `docker compose up -d` → SQLite, simplest household install
- `docker compose -f compose.yaml -f compose.postgres.yaml up -d` → PostgreSQL

The PostgreSQL service needs a health check, private network, named volume, non-default
password from an ignored environment file/secret, and no host-published database port.

Implemented backup behavior:

- portable per-user exports remain database-neutral and exclude auth/provider secrets
- SQLite server disaster snapshots use the existing online backup path
- PostgreSQL server backups use `pg_dump`/`pg_restore`, with credentials passed through
  the process environment rather than arguments
- a server-account-only disaster backup is distinct from a portable user export
- restore into an empty PostgreSQL server now passes in CI and the v2.5.3 release gate;
  PostgreSQL remains beta for real-host upgrade/restore soak rather than a missing
  automated gate

The SQLite server profile shipped as the recommended default alongside the PostgreSQL beta
option. It uses WAL, transactional writes, online snapshots, bounded retention, integrity
checks, and restore verification. A full
backup is not created after every edit. The WAL provides immediate durability, while
scheduled snapshots and a non-sensitive audit/change journal provide disaster recovery
and traceability without unbounded storage growth.

## Native mobile, Personal Tailscale, and future iCloud boundary

The initial native iOS product should support the personal path only:

1. **Local preview/import** — a device-owned library useful during development and for
   validating the Swift data/domain layer.
2. **iCloud library** — the eventual CloudKit-backed authority shared by a person's Apple
   devices, enabled only after migration, privacy, conflict, quota, deletion, and recovery
   behavior pass.

Connecting the native personal app to PMT Server is no longer on the critical iOS path.
PMT Server continues as a separate browser/server product and could receive a dedicated
client later if real demand justifies supporting a second synchronization authority.

Personal Tailscale remains the near-term account-free remote-access option: it opens the
currently running desktop web UI over the user's tailnet. It does not synchronize a second
copy, run while the desktop service is stopped, create users, or place PMT data in iCloud.

CloudKit should contain the canonical personal library only after an explicit opt-in
migration. Credentials stay in Keychain; provider secrets, PMT Server sessions/databases,
and disaster backups do not belong in CloudKit key-value storage. Device-only appearance
preferences may use Apple preference synchronization separately. Moving between local,
CloudKit, and a standalone server remains an explicit, resumable import/export migration
with counts, conflict review, rollback, and one write authority after cutover.

## Durable jobs and scheduling

The shared durable job service is now implemented for server backups, release checks, and
scheduled integration pulls:

- `scheduled_jobs`: kind, owner/scope, due time, state, lease owner/expiry, attempts,
  last safe error, idempotency key
- database compare-and-swap leasing; no correctness dependence on in-memory locks
- bounded concurrency globally and per provider
- exponential backoff with provider `Retry-After`
- pause after repeated failures and notify only once per pause episode
- graceful shutdown releases/lets leases expire
- server-account/user job status surfaces redact payloads and credentials

For a small SQLite server, the worker runs in process. PostgreSQL can run the same worker
in process or the explicit `personal-media-tracker worker` command; database
compare-and-swap leases prevent duplicate claims.

## Recommendation system architecture

### Product decision

PMT should support more than one recommendation implementation behind a stable contract:

1. **Standard local engine** — included with PMT, deterministic, lightweight, and usable
   without downloading a model or running another service.
2. **Advanced local engine** — an optional service/worker extracted from the existing
   recommendation prototype. It adds sentence embeddings, taste-profile clusters,
   collaborative signals, diversification, and offline evaluation.
3. **Future engine adapters** — optional local or remote implementations that satisfy the
   same contract. They remain unavailable until privacy, terms, failure, and evaluation
   gates pass.

The recommendation page and API are part of PMT; the advanced implementation is not.
Turning the advanced engine off must immediately fall back to the standard engine without
affecting the library. On a shared server, the server account decides which engines are
installed and each member decides whether their data may be processed by an optional
engine.

Recommendations were intentionally excluded from the completed 2.5.x stability line.
Ownership, isolation, durable jobs, and the v2.5.3 checkpoint satisfy their technical
prerequisites, but notifications and real import/playback adapters have higher immediate
user value and will test the shared provider boundary first. Begin the recommendation
domain at order 20, keep it behind a disabled capability gate, and do not expose a
Recommendations page until orders 20–21 meet their data-quality and baseline gates.

### Existing prototype assessment

The existing private Python prototype is useful architecture input and contains working
implementations of:

- manual/Letterboxd ingestion and title resolution
- provider metadata caching and catalog discovery
- sentence-transformer and deterministic hashing embeddings
- positive, negative, rewatch, unfinished, and cluster profiles
- content, catalog-edge, public-quality, popularity, and MovieLens candidate signals
- item-KNN and SVD collaborative experiments
- hybrid ranking modes and MMR diversification
- stored explanations, risk flags, feedback, and model-versioned runs
- leave-one-out, rating-error, rank-correlation, and separation evaluation

It is not a drop-in PMT module. Before reuse, remove or replace:

- its Streamlit application, standalone FastAPI routes, CLI library editor, imports,
  metadata settings, and CSV source of truth, all of which duplicate PMT
- its independent `items`, interactions, library versions, jobs, and user tables
- every `user_id=1` default or hard-coded query
- personally selected, title-specific cluster anchors and handoff-derived defaults
- automatic rewatch preference bonuses that conflict with PMT's current evidence contract
- feedback actions that silently convert “looks good” into a watchlist mutation
- synchronous jobs and process-local coordination
- direct filesystem-relative model lookup
- untrusted `joblib`/pickle loading; only PMT-created, version-validated safe artifacts may
  be loaded
- metadata recursion and dataset assumptions that could make a normal household install
  unexpectedly large

The private repository must not become a Git dependency of the public PMT package. Extract
only generalized, reviewed code into an explicitly licensed component, with synthetic
fixtures and no personal exports, caches, model artifacts, handoff documents, `.env`, or
private repository history.

### Core package layout

The lightweight PMT repository should own this package:

```text
src/watchtracker/recommendations/
  __init__.py
  contract.py          # request/result/capability protocols
  policy.py            # privacy, eligibility, minimum-signal rules
  candidates.py        # bounded provider-neutral candidate assembly
  baseline.py          # dependency-light standard engine
  service.py           # authorization, runs, feedback, engine selection
  explanations.py      # safe evidence and user-facing reason codes
  evaluation.py        # baseline comparisons and quality gates
  adapters/
    local_worker.py    # optional internal HTTP client
```

The optional advanced implementation should live in a separately installable project
within the repository or a separately released repository with an independent dependency
lock and container image:

```text
services/recommender/
  pyproject.toml
  Dockerfile
  pmt_recommender/
    api.py
    contracts.py
    feature_store.py
    embeddings.py
    profiles.py
    collaborative.py
    rank.py
    diversify.py
    evaluate.py
    artifacts.py
  tests/
```

Keeping it outside the main wheel prevents advanced dependencies from entering the normal
DMG, Windows bundle, Linux archive, or future native client. The two components share JSON
schemas and golden fixtures, not Python ORM classes or database access.

### Core database model

The `user_accounts`, user-scoped catalog ownership, and leased-job prerequisites now exist.
Order 20 adds the recommendation tables in its then-current migration without changing existing
library rows:

- `recommendation_engine_configs`
  - installation-scoped engine slug, enabled/beta state, endpoint secret reference,
    capabilities, timeout, safe resource limits, and health state
- `user_recommendation_preferences`
  - `user_id`, selected engine, enabled modes, excluded statuses, maturity filters,
    discovery/novelty preference, advanced-processing consent, and feedback retention
- `recommendation_catalog_candidates`
  - server-global catalog item, source, source identity, bounded source score,
    fetched/expiry times, metadata revision, region/language, and public provenance only
- `recommendation_candidate_snapshots`
  - `user_id`, input revision, filters, source-coverage counts, created/expiry times, and a
    state; this is private because eligibility can reveal a person's taste anchors
- `recommendation_candidate_snapshot_items`
  - snapshot, catalog item, discovery reason code, bounded source score, and source
    references; no note, rating, username, email, or provider credential
- `recommendation_runs`
  - UUID, `user_id`, engine/model/contract versions, mode, filters, input revision,
    candidate count, state, timestamps, duration, and safe failure code
- `recommendation_results`
  - run, catalog item, rank, normalized score, confidence, novelty/diversity diagnostics,
    explanation JSON, feature-provenance JSON, and eligibility snapshot
- `recommendation_feedback`
  - `user_id`, optional run/result, catalog item, explicit action, bounded reason code,
    optional rating recorded after watching, and timestamp
- `user_taste_profile_versions`
  - `user_id`, engine/model version, input revision/hash, minimum-signal counts, protected
    artifact reference or safe summary, created/expired times
- `recommendation_evaluation_runs`
  - user/engine/model version, evaluation method, parameters, aggregate metrics, comparison
    baseline, sample size, and timestamp

Never store raw model vectors in portable user exports by default. They are derived data
and can reveal preferences. An Everything disaster backup may include encrypted local
artifacts only when the server account explicitly selects them; restore must validate the
engine/model version before reuse.

Recommended uniqueness and retention rules:

- one result per `(run_id, catalog_item_id)` and one rank per run
- idempotent feedback key for a client request to prevent double submission
- one current engine preference per user
- global candidate provenance unique by source/source identity/region and per-snapshot item
  uniqueness on `(snapshot_id, catalog_item_id)`
- retain recent displayed runs and feedback; compact expired undisplayed candidates
- deleting a user cascades or cryptographically erases their profiles, results, feedback,
  worker pseudonym, and engine secrets

### Engine contract

Use a versioned, implementation-neutral contract. The PMT service constructs requests
after authorization; browsers and native clients never call the optional worker directly.

```json
{
  "contract_version": "1.0",
  "request_id": "uuid",
  "subject": "opaque-worker-user-id",
  "mode": "discovery",
  "limit": 20,
  "input_revision": 184,
  "filters": {
    "media_types": ["movie", "tv", "anime"],
    "exclude_statuses": ["watched", "watching", "not_interested"],
    "max_runtime_minutes": null,
    "minimum_confidence": 0.35
  },
  "signals": [
    {
      "catalog_id": "uuid",
      "rating": 8.5,
      "status": "completed",
      "view_count": 1,
      "favorite": false,
      "technical_score": null,
      "technical_score_allowed": false
    }
  ],
  "candidates": [
    {
      "catalog_id": "uuid",
      "metadata_revision": 12,
      "title": "Example",
      "media_type": "movie",
      "year": 2024,
      "genres": ["drama"],
      "keywords": ["mystery"],
      "overview": "...",
      "public_score": 7.8,
      "popularity": 42.0,
      "external_ids": {"tmdb_movie": "123"}
    }
  ]
}
```

The response contains only catalog IDs supplied in the request:

```json
{
  "contract_version": "1.0",
  "request_id": "uuid",
  "engine": "advanced-local",
  "model_version": "hybrid-1",
  "input_revision": 184,
  "results": [
    {
      "catalog_id": "uuid",
      "rank": 1,
      "score": 0.84,
      "confidence": 0.71,
      "reason_codes": ["genre_affinity", "similar_to_high_rating"],
      "anchor_catalog_ids": ["uuid"],
      "risk_codes": ["limited_feedback"]
    }
  ]
}
```

Contract rules:

- reject unknown versions, duplicate catalog IDs, non-finite scores, oversized text, and
  results not present in the candidate request
- normalize scores to `[0, 1]`; UI percentages are presentation, not cross-run probability
- explanation codes are allowlisted and localized by PMT; worker prose is never rendered
  as trusted HTML
- anchors must belong to the requesting user's allowed signal set
- return a model version, input revision, and deterministic seed where applicable
- PMT applies exclusions again after the response to prevent stale watched items appearing
- timeout/failure returns the standard engine or cached results with a visible freshness
  label; it never blocks the library

### User signals and semantics

Use signals conservatively and transparently:

- personal rating is the primary explicit preference signal
- status distinguishes completed, watching, planned, paused, dropped, and not interested
- a favorite is positive evidence but not a substitute for a rating
- watch count and rewatch history are context only by default; users may separately opt in
  to treating repeated viewing as preference evidence
- started/dropped content is not automatically a genre dislike
- notes and free-form tags are excluded from embedding by default because they may contain
  sensitive text; a future opt-in must preview exactly what will be processed
- advanced technical ratings remain distinct from personal enjoyment; using them is an
  explicit recommendation preference and the explanation must identify that signal
- ranking-refinement answers may provide dimension-level signals only after a versioned
  mapping is documented; unanswered or “do not remember” responses are missing data, not
  neutral scores
- undated viewings remain usable as preference evidence but never acquire invented dates

Create a minimum-data policy rather than generating false precision:

- 0–2 useful rated/completed titles: show provider/editorial discovery and ask for more
  feedback; no predicted rating
- 3–9: low-confidence content baseline with broad diversity
- 10–24: normal personalized baseline
- 25+: advanced profiles may become eligible

These numbers must be calibrated with synthetic and voluntary test data before release;
they are initial safety thresholds, not product claims.

### Candidate supply

A model cannot recommend unseen titles if PMT's catalog contains only the user's library.
Candidate acquisition is therefore a separate, bounded subsystem—not an accidental side
effect of metadata search.

The current `MetadataProvider` protocol supports search, detail, artwork, and schedules;
it does not expose discovery/recommendation feeds. Order 20 adds a separate
`RecommendationCandidateSource` protocol so provider discovery does not distort title
verification or import behavior. Candidate sources resolve identities through the existing
metadata ledger and may create catalog-only records, but they never create `WatchEntry`
rows or alter a user's status.

Initial candidate sources:

- exact provider “similar” or “recommendation” edges for highly rated catalog anchors
- bounded popular/trending/discover pages by media type and region
- public anime recommendations/trending where provider policy permits
- items already present in a shared server catalog but not in the current user's library
- optional server-account-imported IMDb/MovieLens data after terms acceptance

Candidate rules:

- stable external IDs first; never merge by embedding or title alone
- fetch a small number of pages per source and stop recursive graph expansion
- store source, fetched time, expiry, region, and provider terms/provenance
- resolve candidates through the existing metadata identity ledger
- keep low-information stubs out of ranking until minimum title/type/identity evidence and
  sufficient metadata exist
- do not claim streaming availability from recommendation or popularity data
- deduplicate across providers before feature generation
- apply content/maturity, media type, status, runtime, language, year, and hidden-title
  filters before sending candidates to an optional worker
- show candidate coverage and missing-metadata counts in diagnostics

Candidate refresh is a scheduled job with provider-specific limits. It should prioritize
stale candidates that are reachable from a user's strongest anchors rather than importing
an entire provider catalog.

### Standard local engine

The included engine should require only PMT's existing dependencies. It provides a useful,
auditable fallback using normalized scalar features:

- effective genre and subgenre overlap
- keyword overlap with low caps so provider keyword volume cannot dominate
- language/country and media-format affinity
- creator/studio affinity only when reliable identities exist
- bounded similarity/recommendation edge weights
- Bayesian-adjusted public-quality prior
- bounded popularity/obviousness and recency signals
- explicit negative/dropped/not-interested evidence
- user-selected novelty versus familiarity preference
- runtime/episode-commitment fit for the **Tonight** mode
- deterministic MMR-style diversification across genres, formats, and anchor titles

Weights live in a versioned configuration object, not scattered constants. The engine
emits a feature snapshot and reason codes for every result. The first implementation must
be compared against two trivial baselines—provider popularity and genre overlap—and must
beat or intentionally trade against them on documented metrics before it is called
personalized.

Do not display “84% likely you will enjoy this” unless calibration demonstrates that
meaning. Prefer **Match score within this set**, a separate confidence label, and concise
reasons such as “Shares two genres with titles you rated highly.”

### Advanced local engine extraction

The optional worker can reuse generalized parts of the prototype in stages:

1. deterministic hashing embeddings for offline/low-resource validation
2. sentence-transformer embeddings with a server-account-approved model
3. weighted positive and negative user profiles
4. automatically derived taste clusters rather than title-name anchor lists
5. collaborative MovieLens signals where exact IDs exist
6. model-mode weighting, finish/rewatch diagnostics, and diversification
7. per-user feedback adaptation and offline evaluation

Hardening requirements:

- every function requires an explicit opaque subject; no default user
- the worker cannot query PMT's database or filesystem
- artifacts are namespaced by subject, model, embedding type, and input revision
- artifact formats use JSON, NumPy NPZ with `allow_pickle=False`, safetensors, or another
  reviewed non-executable format; never accept uploaded pickle/joblib files
- model downloads require an explicit server-account action, expected model identifier,
  license notice, checksum where available, size estimate, and removable cache
- CPU, memory, candidate count, text length, runtime, and concurrent-run limits are
  configured and enforced
- embedding input excludes notes, credentials, integration payloads, and shared-list prose
- log only counts, timings, model version, and safe error codes
- deterministic seed and dependency/model versions accompany evaluation runs
- stale artifacts are rebuilt asynchronously; a request may use the last compatible model
  with a visible timestamp
- disconnect or consent withdrawal deletes the subject mapping and derived profile/artifacts

The initial collaborative implementation should be treated as a secondary signal. It maps
the user's exact MovieLens-linked movies into a pseudo-profile; it does not learn from PMT
users collectively. Anime and TV quality must not be represented as though MovieLens had
equivalent coverage.

### Optional worker protocol and security

The recommended deployment is a private HTTP service reachable only on the Compose
network or loopback. PMT is the sole client.

```text
GET    /health
GET    /internal/v1/capabilities
PUT    /internal/v1/catalog/batches
PUT    /internal/v1/subjects/{opaque_subject}/signals
POST   /internal/v1/subjects/{opaque_subject}/recommendations
POST   /internal/v1/subjects/{opaque_subject}/evaluate
DELETE /internal/v1/subjects/{opaque_subject}
```

- derive `opaque_subject` with a server secret so the worker never receives a PMT account
  ID, username, or email
- use a separate rotatable service credential in `SecretStore`
- sign requests or use short-lived service tokens; reject replayed request IDs and old
  timestamps
- bind the worker only to the private container network/loopback and do not publish its
  port
- enforce content type and request size before JSON parsing
- make catalog upserts idempotent by catalog/metadata revision
- use health/capability negotiation before selecting the engine
- circuit-break repeated failures and fall back without retry storms
- never let a worker response choose another user's subject or PMT route

The worker owns only derived feature/artifact storage. For household use, a dedicated
SQLite volume is adequate with one worker. A larger PostgreSQL deployment can use a
separate database/schema and least-privilege credential, optionally with pgvector. It must
not receive credentials that can read PMT application tables.

### Docker and desktop setup

The normal Compose path remains unchanged. Add the advanced service through an explicit
profile only after it is stable:

```yaml
services:
  tracker:
    environment:
      WATCHTRACKER_RECOMMENDER_URL: http://recommender:8090
      WATCHTRACKER_RECOMMENDER_SECRET_FILE: /run/secrets/recommender_client_secret

  recommender:
    profiles: ["recommendations"]
    image: ghcr.io/asvpatm/pmt-recommender:${PMT_RECOMMENDER_VERSION}
    expose: ["8090"]
    volumes:
      - recommender-data:/var/lib/pmt-recommender
    secrets:
      - recommender_service_secret
    deploy:
      resources:
        limits:
          memory: 4g
```

Operational behavior:

- `docker compose up -d` runs PMT without the advanced engine
- `docker compose --profile recommendations up -d` enables it
- Settings shows the model download/storage estimate before activation
- disabling the profile leaves PMT fully usable with the standard engine
- backup documentation treats worker artifacts as rebuildable cache unless the admin
  explicitly includes them
- upgrades negotiate contract/model versions and retain the previous compatible image for
  rollback

Do not bundle the advanced engine in the signed macOS DMG initially. PyTorch and model
assets can add hundreds of megabytes, extend startup/build time, complicate notarization,
and consume resources unexpectedly. If desktop demand later justifies it, ship a separate
notarized optional component with its own version, removal flow, disk estimate, and health
status. Never download and execute a Python environment silently from inside PMT.

### Recommendation UI

Add a top-level **Recommendations** page only when the standard engine is useful. It needs:

- readiness card showing signal count, metadata/candidate coverage, active engine, model
  version, last refresh, and honest limitations
- modes such as **For you**, **Discovery**, **Tonight**, **Anime**, and **Shows**, limited
  to modes that have distinct tested behavior
- filters for media type, runtime/episode commitment, year, language, maturity, streaming
  availability only when actually known, novelty, and minimum confidence
- image-forward result cards with match score, confidence, two or three reason codes,
  optional taste anchors, risk/missing-data labels, and metadata provenance
- explicit actions: Add to library, Plan to watch, Add to list, Not interested, Already
  watched, Wrong mood, Too obvious, Too long, and Refresh
- a details disclosure with model/version, score meaning, source coverage, and why an item
  may be uncertain
- a user setting to disable recommendation history, clear feedback/derived profile, change
  engine, or withdraw advanced-processing consent

Feedback and library actions must remain separate controls. **Looks useful** may tune the
model but must not silently change library status. **Plan to watch** changes the library
only after an explicit confirmation/API mutation and records a separate feedback event.

### Evaluation and rollout gates

Run the advanced engine in shadow mode before users see it. For a consented user, both
standard and advanced engines process the same immutable candidate snapshot; only the
standard results are displayed initially. Store aggregate comparison metrics without
exposing hidden recommendations to another user.

Required offline measures:

- time-aware holdout recall@10/25 and NDCG@10
- mean reciprocal rank for strong positives
- rating MAE/RMSE and Spearman only when the sample is large enough
- positive-versus-negative pairwise accuracy
- catalog coverage, genre/media coverage, intra-list diversity, novelty, and popularity
  bias
- percentage of results with usable explanations and strong identities
- result stability when irrelevant metadata changes
- cold-start cohorts and anime/TV/movie cohorts reported separately

Required online/product measures, stored locally:

- save/plan/not-interested/already-seen rates
- later watch and rating outcomes when the user chooses to connect them
- dismissal reason distribution
- generation latency, failure/fallback rate, candidate coverage, and stale-result rate

Never optimize only click or save rate. A system that repeatedly shows popular titles may
score well on clicks while failing PMT's discovery goal. Release gates should require no
regression in exclusions, privacy, explanation validity, and diversity in addition to an
accuracy improvement.

### Native iOS boundary

The future iOS application should consume PMT's versioned recommendation API and cache the
latest results. It should not embed the Python worker, pgvector, MovieLens data, or a
sentence-transformer model.

```text
GET  /api/v1/recommendations/readiness
POST /api/v1/recommendation-runs
GET  /api/v1/recommendation-runs/{id}
POST /api/v1/recommendation-results/{id}/feedback
DELETE /api/v1/me/recommendation-profile
```

Long-running generation returns `202 Accepted` with a job/run ID; the client polls or
receives an authorized invalidation event and then fetches the finished run. Cached results
show their generation time and may be viewed offline, but library-changing actions queue
through the normal sync/edit conflict path.

If PMT later supports iCloud-only operation without a home server, the native app may use a
small Swift implementation of the standard scalar baseline or sync precomputed results as
derived data. The advanced Python engine remains a server/desktop companion and must not
become a CloudKit requirement.

### Extraction and migration sequence

1. Freeze the private prototype and record synthetic golden inputs/outputs and evaluation
   metrics.
2. Define the contract, reason-code taxonomy, score semantics, privacy fields, and engine
   capability negotiation in PMT.
3. Add user-owned recommendation tables after the integration slices have stabilized
   (order 20; assign the migration number when implementation begins).
4. Implement candidate acquisition and the standard baseline entirely within PMT.
5. Copy and generalize only the embedding, profile, collaborative, ranking,
   diversification, and evaluation modules into the optional component.
6. Replace ORM entities with contract DTOs and remove all library/import/metadata UI code.
7. Remove hard-coded users, titles, paths, weights, and implicit feedback mutations.
8. Add safe artifact formats, resource limits, internal authentication, per-subject
   deletion, and contract fixtures.
9. Run standard-versus-advanced shadow evaluation on synthetic and voluntary local data.
10. Release the advanced engine as beta, off by default, with independent health,
    rollback, and uninstall controls.

## Notifications

### Data model

v2.5.4 presents release events and the tenant-scoped
`user_notifications` collaboration inbox in one Notification-center navigation page with
read/dismiss state. Order 13 extends that single surface; it must not create a second
generic inbox table or another navigation page.

Retain and extend `user_notifications`, then add:

- `notification_endpoints`
  - `user_id`, label, adapter type, protected secret reference, enabled, verified time,
    failure state
- `notification_rules`
  - `user_id`, event types, lead times, quiet hours, timezone, endpoint IDs
- `notification_outbox`
  - endpoint, event/rule, dedupe key, state, attempt count, next attempt, delivered time
- `notification_delivery_attempts`
  - bounded operational result, HTTP category, safe error code; never the destination URL

Generate the outbox row in the same transaction as the user-visible event. Delivery is
at-least-once, and a unique dedupe key makes repeats harmless.

### Event types

Initial events:

- episode/season announced or schedule changed
- upcoming release at user-selected lead times (for example 7 days, 1 day, day of)
- shared-list invitation or membership change
- periodic import completed with conflicts/errors
- integration paused after repeated failures
- server-account-only backup/job failure

Do not send every list edit externally by default. Keep collaboration activity in-app and
let users opt into a digest later.

### Apprise

Define a notification adapter interface, then provide:

1. embedded Apprise Python library in an optional `notifications`/server extra for the
   easiest Compose setup
2. optional Apprise API adapter for server operators who already run a separate Apprise
   API service

Apprise destination URLs contain credentials and must live in `SecretStore`, never the
database, logs, exports, test snapshots, DOM, or API responses. Validate allowed schemes,
bound message length, exclude notes/ratings/refinement text, and provide a “Send test”
operation. Document that arbitrary notification destinations create outbound network
traffic and should be limited to trusted server users.

Apprise does not replace native mobile push. A future iOS app would need APNs or local
notifications as another adapter.

## Integration platform completion

### Shared adapter contract

The provider registry, `IntegrationConnection`, cursor/run/event/conflict records,
`SecretStore`, coordinator, and durable scheduler are implemented. Provider definitions
remain deliberately hidden because no production adapter is registered. Extend this
foundation rather than building each integration directly into routes. Every live adapter
must support:

- per-user connection ownership
- `test_connection`
- dry-run preview before the first import
- stable external IDs first; exact title/year/type only as a bounded fallback
- cursor/checkpoint pagination
- idempotent provider event keys
- rate-limit and retry-after handling
- normalized status/score/progress/date mapping with raw provenance
- conflict output for ambiguous matches or differing populated values
- disconnect/revoke behavior
- recorded provider terms/API version

Default import policy:

- create missing PMT entries
- fill empty status/rating/dates/history fields
- do not overwrite populated PMT fields without an explicit per-connection policy
- do not delete PMT data when a remote item disappears
- retain a reversible audit event for every applied change

### OAuth for tracking providers

Provider-account OAuth is separate from PMT login identity, even when both use Authlib.
No provider OAuth callback/token lifecycle is implemented in v2.5.3; order 14 supplies it
once for orders 16–18 to reuse.
Store OAuth authorization state server-side, keep access/refresh tokens in per-user secret
namespaces, rotate single-use refresh tokens atomically, and show expiry/reconnect state.

The self-hosting operator will generally need to register an OAuth application and set its
client ID/secret because callback URLs are installation-specific. Setup UI should generate
the exact callback URL and never pretend this burden can be eliminated.

### Media-server user mapping

Jellyfin/Plex/Emby connections are often server-wide while playback identities are
per-person. Model this explicitly:

- the dedicated server account creates the media-server connection
- `integration_user_bindings(connection_id, remote_user_id, pmt_user_id)` maps selected
  remote users to PMT users
- unbound remote users are ignored and visible only as redacted setup candidates
- one remote user cannot map to multiple PMT users on the same connection
- normal users cannot change the server token or another user's binding

### Jellyfin — first playback adapter

Jellyfin is the best first media-server vertical slice because its official Webhook plugin
can target selected users and notification types without requiring a commercial PMT
service.

v2.5.3 contains the planned provider definition and generic `WebhookCredential` storage,
but no Jellyfin payload adapter, callback route, or `integration_user_bindings` table.
Those pieces remain entirely in order 15 and must not be advertised before fixture-backed
completion/deduplication tests pass.

Implementation:

- issue a revocable PMT webhook credential and show the exact callback URL/template
- accept only bounded JSON and supported playback-stop/completion events
- verify the webhook credential before parsing or logging content
- map Jellyfin user ID through `integration_user_bindings`
- resolve movie/show/episode using TMDb/TVDB/IMDb/provider IDs from Jellyfin before title
- require a documented completion threshold and ignore paused/short/duplicate sessions
- derive an idempotency key from connection, remote user, item/episode, playback session,
  and completion timestamp
- create/update the PMT viewing event through the existing integration coordinator
- unresolved identities enter the conflict queue; never guess an episode from title alone
- optionally add a bounded pull/reconciliation job after webhooks are stable

### Plex

Implement after Jellyfin because the generic inbound contract and remote-user mapping can
be reused. Plex webhooks require Plex Pass and use provider-specific multipart payloads.
Add a research/fixture spike before promising exact support.

- validate the official signature mechanism and payload limits
- map Plex account/user identity explicitly
- resolve GUIDs (TMDb/IMDb/TVDB) before titles
- support watched/scrobble events first; rating and library-presence sync later
- document the Plex Pass prerequisite clearly

### Emby

Implement from the same generic playback contract after Jellyfin/Plex fixtures exist.
Confirm the supported webhook/notification mechanism and any Premiere requirement for the
target Emby versions. If reliable completion webhooks are unavailable, provide a bounded
API pull with a cursor rather than pretending events are real-time.

### Trakt — first broad tracker import

Trakt should be the first OAuth list/history import because it covers movies and TV and
usually supplies strong external IDs.

v2.5.3 contains only the hidden Trakt capability definition and generic integration
coordinator. It does not authenticate to Trakt or import a real account yet.

First release:

- authorization-code or device-code setup
- pull watch history, ratings, watched progress, and watchlist
- rotate Trakt's single-use refresh token atomically
- incremental pagination/checkpoints and periodic schedule
- dry-run counts and conflict preview
- no push, scrobble, deletion, or remote mutation

Add optional push only after explicit direction controls, loop prevention, rollback tests,
and provider-specific conflict rules are complete.

### Kitsu and conditional AniList

Kitsu can follow Trakt and may deliver an earlier read-only beta because PMT already stores
Kitsu/MAL identities. AniList's current official terms prohibit API use in competing list
or tracker services, including use of public media data. PMT must keep AniList unavailable
in public builds unless AniList grants written permission; an environment flag is not a
substitute for permission.

- start with Kitsu read-only list import where provider policy permits it
- add authenticated private-list access separately
- normalize each user's score format into PMT's 1–10 decimal scale while retaining raw
  source values
- map current/completed/planning/paused/dropped/repeating status explicitly
- import progress, repeats, start/end dates, and score without inventing watch dates
- add a planned Kitsu account-import definition; Kitsu is currently metadata support, not
  a completed PMT tracking adapter
- retain AniList IDs only as interoperability identifiers obtained from permitted sources;
  do not call AniList or advertise an AniList connection without written authorization

### MyAnimeList

Use the official OAuth/API path for authenticated lists. Jikan remains metadata-only and
must not be presented as a way to update or privately synchronize a MAL account.

- implement PKCE/OAuth token lifecycle and operator client registration
- pull anime-list status, score, progress, repeats, and dates
- prefer MAL identity; use the existing cross-provider ledger only when exact
- retain integer MAL score provenance when mapped to PMT

### Simkl

Implement after Trakt because the media/status mapping is similar, but keep a separate
adapter and terms gate.

- use the current Simkl documentation/API version and permitted OAuth flow
- pull movies, TV, and anime history/list state with cursors
- respect commercial-use terms and document features that may require a paid Simkl tier
- do not use Simkl as a replacement metadata provider where its terms direct clients to
  original metadata sources

## UI plan

### Server administration

The separation is implemented and remains a binding UI rule:

- the normal desktop's **Settings → Access & Devices** contains Personal Tailscale access
  and the PMT Server connection profile only;
- the normal desktop has no Server console or server lifecycle controls;
- the standalone PMT Server package owns a deliberately bare server console for people,
  invitations, registration policy, future OIDC, database/readiness, backups, workers,
  and server-wide metadata/provider credentials; and
- regular users get Account, Sessions, Integrations, and Notifications surfaces only while
  connected to a PMT Server. Account navigation stays absent in account-free local mode.

### Accounts

v2.5.3 implements the profile/monogram, sign-out, session revocation, invitation
acceptance/first-password, and disabled/expired states for PMT Server users. Future work in
orders 24–25 adds OIDC buttons only for providers the server account configured
successfully.

### Shared lists

v2.5.3 implements private/shared visibility, member roles, sharing, activity, conflict
feedback, and “Add to my library” on untracked titles. Future changes must preserve the
rule that a shared list never reveals another user's private rating, note, history, or
tracking state.

### Notifications

The current working tree presents collaboration and release alerts on one Notification
center page with one unread count. Order 13 adds filters, a rule editor organized by
Releases/Collaboration/Integrations/System, protected endpoint cards,
test/last-success/pause controls, and timezone/quiet-hour preview.

### Integrations

- available adapters only; planned providers remain hidden from ordinary setup
- connection wizard: prerequisites → authorization/token → user mapping/capabilities →
  dry run → enable schedule
- explicit Pull only/Push only/Both labels; start with Pull only
- last run, next run, safe counts, reconnect/pause, and conflict queue

## API additions

The v2.5.3 versioned boundary already includes:

```text
/api/v1/me
/api/v1/server/capabilities
/api/v1/server/readiness
/api/v1/sync/push
/api/v1/sync/pull
/api/v1/auth/sessions
/api/v1/admin/users
/api/v1/admin/invitations
/api/v1/lists/{id}/members
/api/v1/lists/{id}/activity
/api/v1/notifications
```

The `admin` path segment is retained as a stable internal API name for server-account-only
operations. Remaining planned endpoints are:

```text
/api/v1/admin/identity-providers
/api/v1/recommendations/readiness
/api/v1/recommendations/preferences
/api/v1/recommendation-runs
/api/v1/recommendation-runs/{id}
/api/v1/recommendation-results/{id}/feedback
/api/v1/me/recommendation-profile
/api/v1/notification-endpoints
/api/v1/notification-rules
/api/v1/integrations/connections
/api/v1/integrations/oauth/{provider}/start
/api/v1/integrations/oauth/{provider}/callback
/api/v1/webhooks/{provider}/{public_id}
```

Web browser authentication continues using Secure cookies plus CSRF. Order 8 already
landed narrow, rotatable/revocable device sessions, device identity, OS credential-vault
storage, and separate browser/native tests. Passwords are exchanged only with the
authenticated server and are not stored by the client. Every new order must extend this
boundary rather than inventing provider-specific client authentication.

## Migration and release strategy

### Database migration sequence

Continue using small reversible Alembic revisions rather than one giant migration. The
foundation sequence is complete:

1. `0012` moved series schedules to catalog ownership.
2. `0013` added/backfilled immutable user ownership, made ownership required, replaced
   incompatible global uniqueness, and preserved the legacy local library.
3. `0014` added browser/native sessions, invitations, server identity, sync requests, and
   optimistic versions.
4. `0015` migrated lists to catalog items, added memberships/activity/inbox records, and
   added durable jobs.
5. `0016` adds cached released-episode counts and portable shared-list provenance for the
   current handoff/release line; it is not a recommendation migration.

The remaining sequence starts here:

6. `0017` (order 13) extends `user_notifications` and adds endpoint/rule/outbox/attempt
   records. It does not create a duplicate inbox.
7. Order 14 adds provider OAuth state/grant lifecycle records only after the reusable flow
   is implemented and tested.
8. Order 15 adds media-server remote-user bindings when the Jellyfin adapter is ready.
9. Order 20 adds recommendation configuration/preferences, global candidate provenance,
   private snapshots/items, runs/results/feedback/profile versions, and evaluation records.
   It does not change or backfill existing library rows.
10. Order 24 adds external login identities/OIDC state separately from provider-account
   OAuth so the two credential domains cannot be confused.

Migration numbers after `0017` are assigned when each order starts; do not reserve empty
revisions or combine unrelated future orders merely to match this list.

Each upgrade should write aggregate validation counts only, take a safety backup on SQLite,
and refuse to continue if ownership cannot be proven. Test upgrades from real historical
schema versions using synthetic fixtures, never a personal database.

### Feature gates

- schema can ship before UI only if local mode behaves identically; orders 13 and 20 use
  this rule
- standalone multi-user server activation and catalog-based list sharing have passed their
  initial route-isolation gates and ship only in PMT Server Beta
- order 20 recommendation schema/readiness may ship disabled, but recommendations remain
  absent from navigation until candidate coverage, the order 21 baseline comparisons,
  explanations, exclusions, and per-user deletion pass; the advanced engine remains a
  separately gated beta
- adapters stay unavailable until real fixture contracts and disconnect behavior pass
- PostgreSQL's automated upgrade, backup, restore, and Compose gates pass; it stays beta
  until equivalent real-host recovery and upgrade soak is documented
- direct social presets stay beta independently of generic OIDC

Do not label the next build 3.0 solely because notification or recommendation tables were
added. A 3.0 designation should reflect a stable personal-product milestone (for example,
a tested native/iCloud boundary), not require PMT Server to leave beta. Server releases
keep their own beta label and readiness criteria.

## Testing and security gates

### Mandatory multi-user tests

- two users can track the same catalog item independently
- each sees only their entries, histories, rankings, comparisons, imports, integrations,
  notifications, exports, and calendar feed
- guessed UUIDs for every resource return 404/403 without revealing existence
- the dedicated server account cannot read another diary through ordinary user routes
- viewer/editor/owner list permissions are enforced server-side
- a shared-list item displays the current viewer's tracking state only
- disabling a user revokes sessions, jobs, feeds, and integration callbacks
- local mode uses only the local principal and never shows account UI

### Authentication tests

- state/nonce/PKCE and exact redirect URI validation
- OIDC issuer/audience/signature/time validation
- identity collision and unsafe email-link prevention
- invitation expiry/replay, account disable, session rotation/revocation
- CSRF, origin, host, proxy, secure-cookie, throttle, and open-redirect regression tests

### Job/integration tests

- duplicate webhook and import pages are idempotent
- concurrent workers coalesce through database leases
- retry-after/backoff/pause and resume behavior
- provider payload and response fixtures with all secrets redacted
- score/status/date mappings and ambiguous identity conflicts
- remote deletion never erases local history
- tokens rotate atomically and never appear in logs/backups/API/DOM

### Recommendation tests

- standard engine is deterministic for a fixed input revision and seed
- watched, watching, hidden, not-interested, and disallowed-content exclusions are applied
  before and after optional-engine calls
- an engine cannot return a catalog item outside its authorized candidate snapshot
- no title-specific/user-specific constants or default user IDs remain in generalized code
- recommendation history, feedback, profiles, artifacts, and readiness are isolated across
  two users and removed when consent is withdrawn
- notes, credentials, integration payloads, and shared-list notes never enter engine DTOs
- standard/advanced contracts share golden JSON fixtures and reject incompatible versions
- safe artifact loaders reject pickle/joblib and mismatched model/input revisions
- fallback works on worker timeout, malformed response, stale result, restart, and disable
- trivial popularity and genre-overlap baselines are recorded beside personalized metrics
- cold-start, sparse-anime, TV, movie, incomplete-metadata, and no-provider fixtures have
  honest confidence and never fabricate predicted probabilities
- recommendation feedback never mutates library status without a separate explicit action

### Database/deployment tests

- full migration suite on SQLite and PostgreSQL
- SQLite single-process enforcement
- PostgreSQL transaction/concurrency tests
- Compose configuration, health checks, non-root container, private DB port
- SQLite backup restore and PostgreSQL `pg_dump` restore into empty instances
- per-user portable export round trip and server-account disaster recovery

### Release gates

- Ruff, unit, API, migration, browser, and accessibility suites
- dependency/license and container vulnerability audit
- synthetic 2-, 10-, and 100-user performance fixtures
- hostile authorization/IDOR test matrix across every route
- upgrade and rollback rehearsal from the last two stable public releases
- documentation for local mode, SQLite household server, PostgreSQL server, OIDC, backups,
  and every enabled provider

## Logical implementation order and difficulty

Difficulty is relative to this PMT codebase: **1** is a contained low-risk change and
**10** is a cross-cutting migration/security project.

| Order | Implementation slice | Difficulty | Completion gate |
| ---: | --- | :---: | --- |
| 1 | **Released v2.5.3:** architecture contracts, threat model, synthetic legacy fixtures | 4/10 | ADRs define shared/private data, server-account powers, migration/rollback, and provider boundaries. |
| 2 | **Released v2.5.3:** shared catalog and catalog-owned episode schedule refactor | 9/10 | Two synthetic users can follow the same series without duplicate/moved episode records. |
| 3 | **Released v2.5.3:** user ownership schema and legacy single-user backfill | 10/10 | Existing databases migrate to one immutable local principal with identical aggregate and record-level data. |
| 4 | **Released v2.5.3:** request principal and tenant-scoped service/API refactor | 10/10 | Two-user IDOR/isolation coverage passes for implemented routes and exports; every future domain extends it. |
| 5 | **Released in PMT Server Beta v2.5.3:** password auth, dedicated server account, regular users, invitations, recovery, and sessions | 9/10 | Invite-only server supports create/login/disable/recover/revoke without weakening account-free local mode. |
| 6 | **Released in PMT Server Beta v2.5.3:** headless runtime, server-account bootstrap, OCI image, guided setup, and Compose lifecycle | 7/10 | The server runs without a desktop session, survives restart, reports compatibility/readiness, and completes secure first-run setup. |
| 7 | **Released in PMT Server Beta v2.5.3:** SQLite backup/restore, retention, audit journal, and recovery verification | 7/10 | Scheduled online backups restore into an empty test instance and exclude live sessions/secrets. |
| 8 | **Released in PMT Server Beta v2.5.3:** versioned native-client API, server profiles, and device sessions | 8/10 | Reference client verifies identity/capabilities, signs in, rotates/revokes device tokens, and never opens the server database. |
| 9 | **Released in PMT Server Beta v2.5.3:** optimistic concurrency, idempotent outbox sync, reconnect behavior, and offline policy | 9/10 | Replays apply once, stale entry/list mutations become reviewable conflicts, and reconnect tests retain queued work. |
| 10 | **Released in PMT Server Beta v2.5.3:** shared lists, memberships, roles, activity, and collaboration inbox | 9/10 | Owner/editor/viewer rules, catalog list items, per-viewer state, UI, and API isolation tests pass. |
| 11 | **Released in PMT Server Beta v2.5.3:** durable database-leased jobs and integration scheduler | 8/10 | Jobs coalesce, lease, retry, pause/resume, repeat after restart, and expose redacted status. |
| 12 | **Released in PMT Server Beta v2.5.3 (PostgreSQL beta):** dialect support, Compose override, backup/restore | 8/10 | SQLite and PostgreSQL migration/runtime/dump/restore/container release gates pass; real-host soak remains. |
| 13 | **Next—implementation ready:** notification rules, transactional outbox, quiet hours, and optional Apprise delivery | 7/10 | In-app dedupe/read state, retry, quiet-hours, test-delivery, opt-in, and secret-redaction gates pass in local and server principals. |
| 14 | Per-user provider authorization and connection UX | 8/10 | OAuth state/PKCE/token rotation/reconnect, manual-token alternatives, and credential isolation pass without requiring PMT Server. |
| 15 | Jellyfin watched-history vertical slice | 7/10 | Poll/webhook capability selection and synthetic completed movie/episode events update only the mapped PMT user once. |
| 16 | Trakt read-only history/list/rating import plus periodic pulls | 8/10 | Dry run, cursor, refresh-token rotation, conflict policy, and scheduler pass. |
| 17 | Kitsu read-only account import; AniList only if written authorization is obtained | 7/10 | Status/progress/repeat/date/score mappings, provider-policy gate, and rate-limit behavior pass. |
| 18 | MyAnimeList and Simkl read-only imports | 8/10 | OAuth/terms gates, cursors, mappings, and disconnect/reconnect pass. |
| 19 | Plex and Emby playback adapters | 8/10 | Versioned fixtures, prerequisites, remote-user mapping, identity mapping, and dedupe pass. |
| 20 | Recommendation domain, privacy preferences, and bounded candidate acquisition | 8/10 | Candidate provenance/coverage, local/server isolation, retention, deletion, DTO contracts, and no-library-mutation rules pass. |
| 21 | Built-in lightweight recommendation baseline | 7/10 | Exclusions, deterministic scores, explanations, diversity, and trivial-baseline comparisons pass. |
| 22 | Optional advanced recommendation worker extraction and hardening | 9/10 | No duplicate library, hard-coded user/taste data, unsafe artifacts, or direct PMT DB access remains. |
| 23 | Recommendation UI, feedback separation, shadow evaluation, and beta rollout | 8/10 | Standard fallback, honest confidence, feedback semantics, accessibility, and cohort gates pass. |
| 24 | Generic OIDC login | 8/10 | Invite/linking policy and complete OIDC security matrix pass with a real test IdP. |
| 25 | Optional Google/GitHub/Discord login presets | 6/10 | Each provider has isolated config, callback, claims, linking, and regression tests. |

The former critical path through orders 2–12 is complete. Order 13 can now begin directly
from the restored Notification center. Its schema and service reuse the existing local or
tenant principal, release/collaboration events, secret resolution, and leased jobs. Order
14 establishes the reusable authorization boundary before any OAuth-backed importer.
Playback and tracker adapters ship one vertical slice at a time. Recommendation work moves
to orders 20–23; the advanced worker follows the built-in baseline instead of running in
parallel with it.

## Suggested release groupings

1. **Completed in v2.5.3:** orders 1–4, internal ownership/isolation foundation.
2. **Completed in PMT Server Beta v2.5.3:** orders 5–7, invite-only auth, headless SQLite
   deployment, and tested recovery.
3. **Completed in PMT Server Beta v2.5.3:** orders 8–9, device sessions, offline outbox,
   and conflict-safe reconnection.
4. **Completed in PMT Server Beta v2.5.3:** orders 10–12, shared lists, durable jobs, and
   PostgreSQL beta. Continue server field soak independently of the PMT Personal roadmap.
5. **Next minor line—Notifications:** order 13; finish the unified inbox, rules/outbox,
   quiet hours, and optional Apprise delivery without changing personal local defaults.
6. **First real integrations:** orders 14–16; connection authorization, Jellyfin, and
   Trakt read-only import.
7. **Integration breadth:** orders 17–19; anime tracker imports, then Plex/Emby.
8. **Recommendation beta:** orders 20–23; lightweight domain/baseline first, optional
   advanced worker off by default, then the user-visible evaluation-gated page.
9. **Federated login release (server product only):** orders 24–25 after core account recovery and isolation have
   had at least one stable release in real self-hosted use.

## Order 13 execution packet — next work

Order 13 is ready to start after the current handoff/release. The Notification-center
navigation page already combines release and collaboration alerts. This order turns that
in-app inbox into one reliable notification domain and adds strictly opt-in external
delivery through Apprise. It runs for the account-free local principal as well as regular
PMT Server users, but the two products configure and execute it independently.

### Outcome

At completion, a user can keep all alerts in PMT or add one or more named Apprise
destinations, send a safe test, select event types and lead times, set quiet hours in their
own timezone, and see delivery state without exposing destination credentials. Creating an
eligible event and its outbound work is transactional; delivery is retryable and deduped.
The personal desktop sends only while its local service is running. The standalone server
can deliver continuously through its existing leased worker.

### Explicit non-goals

- no account, PMT Server, Tailscale, or external destination is required for the local
  in-app inbox;
- no APNs/mobile push claim; future native iOS notifications use an Apple-specific adapter;
- no notification for every list edit and no private notes, ratings, tags, ranking evidence,
  credentials, or raw provider payloads in a message;
- no arbitrary unauthenticated webhook endpoint and no destination URL in logs, exports,
  DOM, database plaintext, or API responses;
- no recommendation work and no Jellyfin/Trakt/Plex adapter in this order; and
- no change to which database is authoritative for PMT Personal or PMT Server.

### 13.1 Unify the inbox contract without rewriting history

Add `src/watchtracker/notifications/` with a versioned event DTO, policy/rule evaluator,
inbox aggregator, destination adapter protocol, and delivery service. The read model may
initially aggregate existing `ReleaseEvent` and `UserNotification` rows, but it exposes one
stable shape: ID, source kind, event type, safe title/message, effective/created dates,
read/dismiss state, resource link, and delivery summary.

Use one navigation page and one unread badge. Preserve old release and collaboration API
routes for compatibility during this order, while adding a versioned unified route. Marking
read/dismissed must authorize the source row through the active principal; a guessed ID
must not reveal that another user has an event.

Create an event taxonomy with at least:

- `release.episode_announced`, `release.episode_released`,
  `release.season_announced`, `release.schedule_changed`;
- `release.upcoming` with bounded 7-day, 1-day, and day-of lead-time choices;
- `collaboration.invited`, `collaboration.membership_changed`;
- `integration.completed_with_conflicts`, `integration.paused`; and
- `operations.job_paused`, restricted to the standalone server account where appropriate.

### 13.2 Migration `0017`

Add a small SQLite/PostgreSQL-safe revision after the current `0016`:

- `notification_endpoints`: owner/principal, label, adapter, protected secret reference,
  enabled/verified timestamps, last safe failure code, and optimistic version;
- `notification_rules`: owner/principal, event pattern, enabled state, lead time, quiet-hour
  start/end, timezone, endpoint binding, and in-app/external flags;
- `notification_outbox`: owner/principal, endpoint, source kind/key, rendered-safe payload,
  dedupe key, state, due/lease/attempt/delivered timestamps; and
- `notification_delivery_attempts`: outbox ID, attempt number, timing, result category,
  provider-safe receipt hash, and safe error code/message.

Destination URLs/tokens live only in `SecretStore`. The endpoint row stores an opaque
secret reference. Deleting an endpoint cancels its undelivered outbox rows and deletes the
secret after the database transaction succeeds. Deleting a user cascades through all
private rules/endpoints/outbox/attempts. Migration upgrade does not create endpoints or
turn on external delivery; downgrade refuses while an outbox item is actively leased.

### 13.3 Transactional outbox and worker behavior

Introduce one `NotificationService.emit(...)` boundary and migrate release, collaboration,
and job-pause producers to it incrementally. In the same transaction it creates or updates
the in-app event, evaluates enabled rules, and inserts uniquely deduped outbox rows. A
worker never invents a notification by scanning mutable UI state.

Register `notifications.deliver` with the existing database-leased job service. Claim in
small batches, bound concurrency globally and per destination, honor quiet hours before a
network call, classify permanent versus retryable failures, respect `Retry-After`, use
exponential backoff with jitter, and pause an endpoint after a bounded failure threshold.
An endpoint-pause event is emitted once without routing back to the failed endpoint.

Delivery is at-least-once. Each message includes a deterministic dedupe key and the outbox
unique constraint prevents duplicate jobs. A crash after the provider accepts a message
may repeat it; document this honestly and retain enough safe attempt metadata to diagnose
it. Local-mode shutdown leaves due rows durable for the next launch.

### 13.4 Apprise adapter and secret safety

Implement a narrow `NotificationAdapter` protocol, then an embedded Apprise adapter. Keep
Apprise behind a packaging extra/feature capability until wheel, DMG, Linux bundle,
license, import-time, and size checks pass; the Settings UI reports unavailable rather
than showing a dead provider when the extra is absent. The standalone Compose image may
enable the same embedded adapter. An Apprise API adapter can follow later for operators who
already run that service.

Accept only schemes explicitly reported as supported by the installed Apprise version and
maintain a denylist for local/file/command-style transports that do not fit PMT's outbound
message boundary. Parse and validate before storing, redact with a non-reversible display
hint such as adapter type plus endpoint label, and never serialize the original URL after
creation. `Send test` uses a fixed PMT message with no library data and is rate limited.

Cap titles/body length, normalize control characters, set network connect/read timeouts,
disable redirects to unsafe targets where the adapter allows it, and ensure exception text
cannot echo a destination URL. Apprise is external delivery, not a replacement for the
in-app record.

### 13.5 Versioned API and UI

Add principal-scoped endpoints such as:

```text
GET    /api/v1/notifications
PATCH  /api/v1/notifications/{source_kind}/{id}
GET    /api/v1/notification-settings
PUT    /api/v1/notification-settings
POST   /api/v1/notification-endpoints
PATCH  /api/v1/notification-endpoints/{id}
DELETE /api/v1/notification-endpoints/{id}
POST   /api/v1/notification-endpoints/{id}/test
GET    /api/v1/notification-deliveries?state=failed
```

Creation accepts a destination secret once; responses return only endpoint ID, label,
adapter/capability, verification state, enabled state, and a redacted hint. CSRF,
principal isolation, request bounds, rate limits, and structured safe errors apply.

Keep the navigation button restored for local and regular-user experiences and hidden in
the dedicated server-account console unless that console has operational alerts. Add a
compact **Delivery settings** disclosure on the Notification page instead of another large
Settings tab. Explain that in-app alerts always work locally, external alerts are optional,
the desktop must be running to send, and an always-on server schedules independently.
Every new control and failure state must be selectable in the private PMT Flow fixture.

### 13.6 File-level implementation map

| File/area | Required change |
| --- | --- |
| `src/watchtracker/models.py` | Add endpoints, rules, outbox, and bounded attempts with ownership/index constraints. |
| `src/watchtracker/migrations/versions/0017_notification_delivery.py` | Add the isolated SQLite/PostgreSQL-safe schema; no default external endpoint. |
| `src/watchtracker/notifications/` | Add contract, aggregation, rule policy, adapters, rendering, and delivery service. |
| `src/watchtracker/services/releases.py`, `lists.py`, `jobs.py` | Route event production through the transactional service without changing source semantics. |
| `src/watchtracker/services/secrets.py` | Store/delete destination secrets by opaque endpoint reference and provide redacted inspection only. |
| `src/watchtracker/schemas.py`, `app.py` | Add strict versioned API and capability fields. |
| `src/watchtracker/static/` | Finish the unified inbox, badge, compact delivery setup, quiet hours, test, and failure/retry states. |
| `pyproject.toml`, packaging workflows | Add and verify the optional Apprise capability without silently breaking public artifacts. |
| `tests/test_notifications.py` | Event aggregation, rules, quiet hours, rendering, dedupe, retry, pause, redaction, and local restart tests. |
| `tests/test_migrations_and_isolation.py` | `0016 → 0017`, clean upgrade, downgrade guard, cascade, hostile-ID, and export exclusion tests. |
| `tests/test_postgres_runtime.py` | Lease/outbox concurrency, uniqueness, retry, and deletion behavior on PostgreSQL. |
| `tests/test_browser_e2e.py` and PMT Flow fixture | Navigation, unread count, endpoint setup/test/remove, narrow layout, and accessible error states. |

### 13.7 Definition of done

Order 13 is complete only when:

- Ruff, formatting, full unit/API/migration/browser suites, SQLite/PostgreSQL concurrency,
  package builds, and dependency/license audits pass;
- the in-app inbox remains useful with no Apprise package or endpoint configured;
- local and server principals cannot read, mutate, route through, or infer one another's
  events, endpoints, rules, outbox, attempts, or secret existence;
- event and outbox creation is atomic, duplicate producers/delivery jobs coalesce, quiet
  hours survive DST/timezone changes, and restart retains pending delivery;
- destination URLs and tokens are absent from database plaintext, HTML/DOM, logs, errors,
  exports, backups that exclude secrets, and PMT Flow evidence;
- test delivery is fixed-content and rate limited; message rendering excludes all private
  diary/refinement fields and obeys hard size bounds;
- Personal Tailscale, account-free local startup, and PMT Server lifecycle remain unchanged;
- PMT Personal never requires server availability and the dedicated server console remains
  absent from its release UI; and
- the plan/checkpoint is updated before order 14 provider authorization begins.

## Deferred order 20 recommendation execution notes

Order 20 creates the private recommendation domain and a bounded supply of catalog
candidates. It does **not** rank titles, show a Recommendations navigation item, call the
advanced prototype, or add heavy ML dependencies. Those boundaries keep its migration
reviewable and let order 21 test the built-in baseline against a stable candidate snapshot.

### Outcome

At completion, local mode and every PMT Server regular user can have isolated
recommendation preferences and candidate snapshots. PMT can report honest readiness and
coverage, refresh candidates through a leased job, and delete/expire derived data. No
candidate refresh creates a library entry, changes a status/rating, or exposes another
user's anchors.

### Explicit non-goals

- no recommendation scores, result cards, feedback buttons, or navigation page;
- no sentence-transformer, NumPy/SciPy, scikit-learn, pgvector, model download, or optional
  worker process;
- no import from or runtime dependency on the private recommendation repository;
- no remote recommendation provider and no notes/free-form tags in a DTO;
- no streaming-availability claim and no invented date, identity, or metadata field; and
- no change to current title verification, import matching, ranking refinement, PMT Server
  setup, Personal Tailscale access, or the account-free local-mode startup path.

### 20.1 Contract and policy package

Create the lightweight package before routes or migrations depend on it:

```text
src/watchtracker/recommendations/
  __init__.py
  contract.py       # versioned DTOs, enums, size/range validation
  policy.py         # signal eligibility, privacy, exclusions, minimum-data state
  candidates.py     # candidate-source protocol, identity/provenance normalization
  service.py        # principal-scoped preferences, snapshots, retention, readiness
```

Contract version `1.0` must define allowlisted candidate source/reason codes, media and
status filters, input/metadata revisions, finite bounded source scores, coverage counts,
and safe failure codes. Unknown fields are rejected at the external/worker boundary but
database readers tolerate additive stored provenance fields. Python models must remain
dependency-light and JSON serializable.

The policy layer must exclude already tracked, hidden, explicitly not-interested, and
disallowed-content items both when a snapshot is created and when it is read. It can use
ratings/status/history counts to select anchors, but it sends no notes, free-form tags,
usernames, emails, credentials, shared-list notes, or raw provider payloads.

### 20.2 Migration (number assigned when order 20 starts)

Add the models described in **Core database model**, using UUID primary keys, timezone
timestamps, explicit foreign-key deletion behavior, finite/range checks where portable,
and these ownership rules:

- engine installation configuration is server-global and contains only a protected secret
  reference, never a secret value;
- user preferences, candidate snapshots/items, runs, results, feedback, taste-profile
  versions, and evaluation records are tenant-owned directly or through a tenant-owned
  parent;
- global catalog-candidate provenance contains public provider facts only and cannot store
  private anchor IDs;
- a snapshot item references a catalog item but does not create a `WatchEntry`;
- deleting a user cascades through every private recommendation row;
- deleting global candidate cache rows cannot delete catalog items or personal history;
- migration upgrade from the then-current schema performs no library backfill and records
  no personal values; and
- downgrade refuses if doing so would strand an active recommendation job, then removes
  only recommendation-domain data.

Add the migration to both the clean-database and historical synthetic upgrade fixtures.
Exercise it on SQLite and PostgreSQL; do not treat a SQLite-only pass as completion.

### 20.3 Candidate-source boundary and first sources

Add `RecommendationCandidateSource` separately from the current `MetadataProvider`
protocol. A source returns stable external identities, a bounded discovery reason/score,
region/language context, fetched/expiry times, and public provenance. The recommendation
service resolves or enriches those records through the existing identity ledger.

Implement sources in this order:

1. **Existing server catalog:** untracked catalog titles provide a deterministic offline
   and multi-user test source with no network or credential.
2. **One current keyless discovery source:** choose only after re-verifying its official
   API terms, limits, identity strength, and allowed caching at implementation time.
3. **TMDb-enhanced discovery:** optional when the effective metadata credential resolver
   finds a permitted individual token or server-shared fallback.

The first live source is not hard-coded into the domain contract. Per-source limits cap
pages, anchors, candidate count, response bytes, concurrency, and refresh frequency.
Failures return safe coverage diagnostics and preserve the last unexpired snapshot; they do
not block the library. Provider calls use the existing HTTP/cache/rate-limit controls and
never log credentials.

Schedule refreshes as a new leased job kind such as
`recommendation_candidates.refresh`. Its idempotency key includes user, filter revision,
and refresh window. A manual request coalesces with an already queued/running refresh.

### 20.4 Service and versioned API

Add only the endpoints needed by the domain foundation:

```text
GET  /api/v1/recommendations/readiness
GET  /api/v1/recommendations/preferences
PUT  /api/v1/recommendations/preferences
POST /api/v1/recommendation-candidate-refreshes
GET  /api/v1/recommendation-candidate-snapshots/{id}
DELETE /api/v1/me/recommendation-data
```

The readiness response contains signal counts, candidate counts by media/source, identity
and metadata coverage, freshness, active contract version, feature-gate state, and safe
limitations. It never returns anchors or another user's counts. Refresh returns `202` with
a job/snapshot identifier. Snapshot access is principal-scoped and guessed IDs do not
reveal existence.

Expose capability fields through `/api/v1/server/capabilities` so future Swift clients can
negotiate the contract. Keep the feature disabled by default and do not add public UI or
navigation in order 20. Any future native client needs only capability/readiness support;
result caching and feedback operations wait for orders 21–23.

### 20.5 Retention, exports, and deletion

- Expire unused candidate snapshots and global provenance on bounded schedules; retain an
  unexpired last-good snapshot through transient provider failures.
- Portable per-user exports include explicit recommendation preferences/feedback only
  after those features are user-visible. Candidate caches, profile artifacts, and engine
  secrets are derived/server data and stay out by default.
- Everything disaster backups may include database rows but never external secret-store
  values or executable model artifacts.
- `DELETE /api/v1/me/recommendation-data` requires confirmation in the eventual UI and
  removes private candidates, runs, results, feedback, profiles, and worker subject mapping
  without deleting library/catalog records.
- Consent withdrawal cancels/invalidates queued recommendation jobs before deletion.

### 20.6 File-level implementation map

| File/area | Required change |
| --- | --- |
| `src/watchtracker/models.py` | Add recommendation-domain ORM models and ownership/index constraints. |
| `src/watchtracker/migrations/versions/<next>_recommendation_domain.py` | Add the isolated schema with SQLite/PostgreSQL-safe upgrade/downgrade behavior. |
| `src/watchtracker/recommendations/` | Add contracts, policy, candidate protocol, and tenant-scoped service. |
| `src/watchtracker/schemas.py` | Add API request/response models with strict bounds. |
| `src/watchtracker/app.py` | Add principal-scoped readiness/preferences/refresh/snapshot/delete routes and capability flags. |
| `src/watchtracker/services/jobs.py` and startup wiring | Register the idempotent candidate-refresh job handler and retention cleanup. |
| `src/watchtracker/metadata/` | Reuse identity/enrichment and credential resolution; do not add discovery methods to `MetadataProvider`. |
| `tests/test_recommendation_foundation.py` | Contract, policy, two-user isolation, retention, failure, bounds, and no-library-mutation tests. |
| `tests/test_migrations_and_isolation.py` | Prior head → recommendation migration, clean upgrade, downgrade guard, deletion, export, and hostile-ID coverage. |
| `tests/test_postgres_runtime.py` | PostgreSQL migration, JSON/query, leased-refresh, and delete/cascade coverage. |
| `.github/workflows/ci.yml` | No new job unless existing PostgreSQL/browser matrices cannot exercise the new tests. |

### 20.7 Definition of done

Order 20 is complete only when all of the following are true:

- Ruff, formatting, unit, API, migration, PostgreSQL, browser regression, dependency audit,
  benchmark, and package-build checks pass;
- two users with identical filters receive independently authorized snapshots and neither
  can infer or fetch the other's snapshot, anchors, preferences, or readiness counts;
- candidate refresh never creates/updates/deletes `WatchEntry`, viewing, rating,
  refinement, list, or notification records;
- duplicate refresh requests coalesce, retries are bounded, and a provider outage leaves
  the rest of PMT usable with honest stale/coverage state;
- snapshot/source/response limits reject oversized, duplicate, unknown, non-finite, or
  identity-poor inputs;
- secrets, notes, free-form tags, usernames, emails, private list data, and raw payloads are
  absent from DTOs, logs, exports, and error responses;
- local mode remains account-free and visually unchanged; the normal desktop still cannot
  host or expose the Server console;
- the standard desktop wheel/DMG/ZIP gains no ML dependency or model asset;
- capabilities negotiate order 20 without breaking an older personal or server client; and
- the plan/checkpoint is updated to mark order 20 complete before order 21 begins.

PMT Flow does not need a placeholder Recommendations page for this hidden foundation.
When order 23 introduces user-visible recommendation elements, its private preview fixture
must include varied cold-start, sparse, movie, television, and anime sample states and make
every new control selectable. PMT Flow remains excluded from public release artifacts.

## Feasibility conclusions

- **Central household server:** implemented as a separate beta package; field reliability
  and operator simplicity, rather than basic feasibility, are now the concern.
- **Individual accounts:** implemented in PMT Server Beta with a dedicated server account
  and regular users; isolation remains a permanent release gate.
- **Shared lists:** implemented with catalog items and memberships; private watch-entry
  records remain separate.
- **In-app and Apprise notifications:** the release/collaboration inbox groundwork exists;
  rules, delivery outbox, endpoints, and Apprise are the implementation-ready order 13.
- **SQLite and PostgreSQL Compose:** implemented. SQLite remains the recommended default;
  PostgreSQL's automated migration/backup/restore gates pass but real-host support remains
  beta.
- **OIDC:** feasible and valuable. Generic OIDC is a better PMT target than claiming direct
  support for 100 providers.
- **Jellyfin:** high feasibility and best first playback adapter.
- **Plex/Emby:** feasible with clearer paid/plugin/version prerequisites and more fixture
  research.
- **Trakt/Kitsu/MAL/Simkl periodic imports:** feasible on the existing integration
  foundation, but each is a real product slice with OAuth, rate limits, terms, mappings,
  and conflict behavior—not a single generic “import API” task. AniList is blocked unless
  written permission is obtained under its current tracker restriction.
- **Standard recommendations:** tenant ownership and durable jobs are complete, but this is
  intentionally deferred until notification and integration contracts have shipped. PMT
  already holds high-value personal signals and normalized metadata.
- **Advanced local recommendations:** feasible but should remain optional. The prototype
  supplies valuable algorithms and tests, while its duplicate application shell,
  hard-coded user assumptions, heavy dependencies, and artifact handling require a
  deliberate extraction rather than a merge.
- **Native iOS recommendations:** feasible through a Swift/CloudKit-compatible contract or
  precomputed derived results. Directly embedding the Python ML stack in iOS is neither
  necessary nor recommended.

## Primary references

- [Yamtrack repository and current feature list](https://github.com/FuzzyGrim/Yamtrack)
- [Yamtrack Compose example](https://github.com/FuzzyGrim/Yamtrack/blob/dev/docker-compose.yml)
- [Authlib Starlette OAuth/OIDC client](https://docs.authlib.org/en/v1.6.8/client/starlette.html)
- [django-allauth provider model](https://docs.allauth.org/en/latest/socialaccount/providers/index.html)
- [Apprise supported services](https://appriseit.com/services/)
- [Jellyfin Webhook Plugin](https://jellyfin.org/docs/general/server/notifications/)
- [Plex webhook prerequisite](https://support.plex.tv/articles/201862428-plex-accounts/)
- [Emby notifications and webhook plugins](https://emby.media/support/articles/Notifications.html)
- [Trakt OAuth](https://docs.trakt.tv/docs/authentication-oauth)
- [Simkl API repository/current documentation notice](https://github.com/SIMKL/API)
- [AniList API terms of use](https://docs.anilist.co/guide/terms-of-use)
- [Kitsu API documentation repository](https://github.com/hummingbird-me/api-docs)
- [SQLAlchemy PostgreSQL/psycopg support](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html)
- [PostgreSQL `pg_dump`](https://www.postgresql.org/docs/current/app-pgdump.html)
- [Docker Compose profiles](https://docs.docker.com/compose/how-tos/profiles/)
