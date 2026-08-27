# Multi-user server, recommendations, notifications, and integrations plan

Status: orders 1–12 implemented as a release candidate; orders 13–25 remain proposed.
PostgreSQL remains beta until its containerized CI and a release-candidate restore drill
pass; SQLite remains the recommended server default.

Prepared: 2026-08-26
Baseline: Personal Media Tracker 2.5.2 planning baseline, FastAPI, SQLAlchemy, Alembic,
SQLite, and a vanilla web UI

Implementation note: the ownership schema, shared schedule cache, request principal,
tenant-scoped services/exports, threat model, ADRs, and synthetic migration/isolation
fixtures are in place. Multi-user password accounts, headless bootstrap, invitations and
recovery, revocable browser/native sessions, the server artifact, checked recovery,
connection onboarding, OS-vault tokens, a durable client cache/outbox, entry/list conflict
handling, catalog-based shared lists, collaboration activity/inbox, database-leased jobs,
and optional PostgreSQL deployment are implemented. The Python remote client is the
cross-platform reference used by the desktop connection UI and tests; a native Swift iOS
interface is still future work and will consume the same versioned contract.

## Executive recommendation

PMT should evolve its existing authenticated Shared Access mode into an optional
multi-user home server. The server should have its own headless install artifact, while
remaining a runtime profile of the same FastAPI/domain codebase rather than a separately
developed service. PMT should not copy Yamtrack's Django architecture or make an account
mandatory for the desktop application.

The resulting product should have two explicit operating modes:

1. **Personal local mode** — the current account-free desktop experience. A built-in
   local profile owns the data; the app binds to loopback; no login is shown.
2. **Shared server mode** — one always-on PMT process owns the database and serves the
   same web application to authenticated users over HTTPS. Each person has a private
   library, ratings, history, refinements, integrations, and notification settings.
   Lists can be shared deliberately with viewer or editor permission.

The release may therefore contain two artifacts with the same version and migration
head: the normal Personal Media Tracker desktop package and a headless **PMT Server**
image/package. This is packaging and process separation, not a fork. The desktop can run
its embedded local server or connect as a client to an existing PMT Server; it must never
open or copy the remote server's database file.

Accepted client/server boundary for the beta: the normal application always presents its
personal local library unless the user explicitly enables a saved PMT Server connection.
The server console appears only on the standalone server installation, where the server
account manages people, metadata fallback, backups, and readiness. A client-side
disconnect pauses that device and preserves its securely stored session; forgetting a
server removes only that device's token/cache/outbox. Stopping the standalone service
makes every account unavailable but leaves all accounts, private libraries, lists, and
backups in the server database. Tailscale reachability is a separate network state and
never determines whether data exists. An enabled desktop connection opens the saved
server account through a short-lived, one-use native-to-browser session handoff; if that
server is unreachable at startup, the client opens its untouched local library instead.

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

The sequence matters. Multi-user ownership and authorization must ship before shared
lists, notifications, media-server events, or periodic imports. Adding adapters first
would make their records globally owned and require a risky second migration later.

## What PMT already has

PMT is not starting from zero:

| Existing foundation | Current state | Reuse |
| --- | --- | --- |
| Shared Access | One authenticated owner can use the same server from multiple devices over HTTPS/Tailscale/Caddy. | Keep the networking and fail-closed readiness model. |
| Authentication | Argon2id password hashes, opaque hashed sessions, expiry/revocation, CSRF, login throttling, Secure/HttpOnly cookies. | Generalize owner records to users and roles. |
| Docker | Non-root multi-architecture container, guided setup bundle, SQLite/PostgreSQL Compose, health checks, and optional Caddy profile. | Harden release-candidate recovery and upgrades before widening support. |
| Release tracking | Subscriptions, normalized episodes, release events, calendar, scheduler leases, and deduplication. | Split shared schedule data from per-user subscriptions and add delivery rules. |
| Integration foundation | Provider definitions, secret references, cursors, runs, idempotent events, conflicts, retry/backoff, and audit summaries. | Add user ownership, a durable scheduler, OAuth callbacks, and real adapters. |
| Provider identities | TMDb, TVmaze, AniList, MAL, Kitsu, and other external IDs can be attached to catalog records. | Resolve imported/playback events by stable IDs before titles. |
| Lists | Catalog-based personal/shared lists, owner/editor/viewer memberships, activity, notifications, and pinned navigation. | Extend only after real household beta feedback. |
| Recommendation signals | Personal ratings, status, history, tags, normalized metadata, advanced-rating evidence, and explainable ranking infrastructure. | Add a recommendation-specific contract that consumes these signals without changing their meaning. |
| Portability | Everything archives, provider-neutral logical snapshots, migrations, and integrity checks. | Add per-user export plus separate server disaster recovery. |

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
- Existing 2.5.1 databases migrate to one local/admin user without changing title IDs,
  ratings, histories, or dates.
- Existing clients and the desktop UI continue to work during staged development. New
  server behavior stays behind capability/configuration gates until isolation tests pass.
- Every profile chooses one authoritative library backend at a time: embedded local PMT,
  a self-hosted PMT Server, or a future CloudKit-backed library. Two authorities never
  accept writes for the same profile without a separately designed reconciliation system.
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
Mac/iPhone/browser clients
          |
       HTTPS
          |
  Caddy or Tailscale Serve
          |
  FastAPI application
    |       |        |
  auth   domain    background worker
    |       |        |          |
    +-------+--------+----------+
            |
  SQLite (small/single process)
        or PostgreSQL
            |
  shared catalog + private user records
       |                    |
  provider adapters    recommendation contract
  Apprise / webhooks       |              |
                      built-in       optional local
                      baseline       recommender worker
```

The browser clients do not open or synchronize a SQLite file. They make authenticated
requests to the one authoritative PMT server. This is already how Shared Access behaves;
multi-user support changes ownership and authorization, not the basic network model.

### Process and distribution model

Use one source tree and one schema migration history with explicit runtime roles:

- **`pmt local`**: current desktop behavior; embedded loopback server, local database,
  account-free local principal
- **`pmt server`**: headless authoritative service; no native window, admin bootstrap,
  authentication, jobs, integrations, backups, and browser UI
- **remote client profile**: desktop or mobile UI pointed at one versioned PMT Server API;
  local storage is a cache/outbox and never becomes a second source of truth

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

Keep these server-global because they describe media rather than a person's relationship
to media:

- `catalog_items`
- `external_identities`
- `catalog_metadata_sources`
- provider metadata cache/provenance
- `season_records` and `episode_records` after they are moved to `catalog_item_id`

Change `CatalogItem.entry` to `CatalogItem.entries`. Remove the global uniqueness of
`WatchEntry.catalog_item_id` and replace it with a uniqueness rule on
`(user_id, catalog_item_id)`. A deleted entry is retained/resurrected rather than creating
multiple rows for the same user's title.

Move schedule ownership from `WatchEntry` to `CatalogItem`:

- `SeasonRecord.catalog_item_id -> catalog_items.id`
- `EpisodeRecord` remains under a season
- `SeriesTrackingSubscription` remains per-user through `entry_id`
- `EpisodeViewing` remains per-user through `entry_id`
- `ReleaseEvent` remains per-user because read/dismiss/delivery state is personal

This lets one provider schedule fetch serve every subscribed user without moving globally
unique season/episode records between their entries.

### User and authentication tables

Add:

- `user_accounts`
  - UUID primary key
  - normalized unique username
  - optional unique normalized email
  - display name
  - nullable password hash (OIDC-only accounts are allowed)
  - role: `admin` or `member`
  - state: `invited`, `active`, `disabled`
  - locale, timezone, created/updated/password-changed timestamps
- `user_sessions`
  - `user_id`, token hash, CSRF hash, expiry, last seen, revoked timestamp
  - optional safe device label and user-agent hash, never raw browser history
- `external_auth_identities`
  - `user_id`, provider slug, OIDC issuer, stable subject, limited claims snapshot
  - unique `(issuer, subject)`; email is never sufficient identity proof
- `user_invitations`
  - hashed single-use token, creator, role, expiry, accepted timestamp
- `oauth_login_states`
  - short-lived hashed state/nonce/PKCE verifier and intended return path

Migrate `OwnerAccount` to the first admin `UserAccount`; migrate existing active sessions
or deliberately revoke them and require one sign-in after upgrade. Revoking is safer and
simpler, and should be communicated in the migration screen.

### User-owned domain records

Add `user_id` directly to every ownership root:

- `watch_entries`
- `media_lists`
- rating comparisons and refinement runs
- import previews and import history
- integration connections
- notification endpoints/rules/inbox records
- calendar-feed tokens
- per-user settings that should follow a login

Child records may derive ownership from an entry or connection, but service methods must
still receive a `Principal` and validate the root owner. For especially sensitive tables,
use composite foreign keys containing `user_id` so an implementation error cannot connect
one user's child row to another user's parent.

Update uniqueness rules that are currently global:

- list name: `(owner_user_id, normalized_name)`
- viewing source key: `(user_id, source, source_key)`
- rating pair: `(user_id, entry_low_id, entry_high_id)`
- refinement active run/draft: user-scoped
- calendar tokens and integration dedupe keys: owner/connection scoped

### Shared-list model

Replace `MediaListItem.entry_id` with `catalog_item_id`. A shared list is a collection of
titles, not a collection of the owner's private tracking rows.

Add:

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

Create one request-scoped `Principal` abstraction:

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
  the scheduler/admin layer.
- Every list operation passes through a policy function such as
  `require_list_permission(principal, list_id, "edit")`.

Add a central authorization policy module rather than repeating conditional checks in UI
handlers. Minimum permissions:

| Resource/action | Member | List editor | List owner | Admin |
| --- | --- | --- | --- | --- |
| Own library/settings/integrations | Full | Full | Full | Own only by default |
| View shared list | If member | Yes | Yes | Only if member or support mode is explicitly audited |
| Add/remove shared list items | No | Yes | Yes | Not implicitly |
| Manage memberships | No | No | Yes | Emergency audited action only |
| Invite/disable server users | No | No | No | Yes |
| Read another user's ratings/notes/history | No | No | No | No normal UI/API path |

Admin must mean server administration, not silent access to private diaries. If an
emergency data-repair feature is ever required, make it explicit, audited, and disabled by
default.

### Concurrent edits

Multiple devices introduce lost-update risk even with one user. Add an integer `version`
to `WatchEntry`, `MediaList`, and membership-sensitive records. Return it as an ETag or
payload field and require `If-Match`/expected version for edits. A stale edit returns
`409 conflict` with current safe state so the UI can offer reload or deliberate overwrite.

Start with refetch-on-success and bounded polling. Later, add Server-Sent Events that carry
only invalidation messages (`entry_changed`, `list_changed`, `notification_added`) and make
the client refetch authorized data. Do not put notes or credentials in event payloads.

## Accounts and login flows

### Local credentials

Generalize the current owner login instead of replacing it:

- first server setup creates the dedicated server account
- default registration policy is `invite_only`
- optional `closed` and `open` modes are server-account settings; `open` requires explicit warning
- invitations expire and are stored only as hashes
- password minimum remains at least 12 characters with Argon2id hashing
- login errors remain generic and throttled by account/IP-derived keyed hashes
- password changes revoke that user's sessions; a server-account disable revokes all of that user’s
  sessions and scheduled integrations
- session UI lists device label, last seen, expiry, and revoke button

Email should remain optional for a local household server. Password-reset email is not
required for the first release; an admin can issue a short-lived recovery invitation.

### OIDC and social authentication

Do **not** add `django-allauth` to PMT. It is tied to Django's ORM, middleware, sessions,
admin, and templates; adopting it would mean a backend rewrite for one feature family.

Use a FastAPI/Starlette-compatible OAuth/OIDC client such as Authlib behind a small
`IdentityProviderAdapter`. Implement one generic OIDC provider first:

- configuration is server-admin/environment owned: issuer/discovery URL, client ID,
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

### Existing Shared Access evolution

Keep the current HTTPS, exact host, trusted proxy, Tailscale Serve, Caddy, readiness, and
fail-closed startup checks. Rename the UI concept from single-owner “Shared Access” to an
optional “Shared Server” only after multi-user isolation is ready.

The server installation has no dependency on a logged-in desktop session or open native
window. Its first browser visit performs one-time server-account setup using either a
single-use bootstrap token printed to the host console or a host-local setup endpoint.
After bootstrap, the setup credential is invalidated. Service status, migrations,
capabilities, backup health, and API compatibility are visible without exposing secrets.

Split settings by scope:

- **server account:** access mode, origin/hosts/proxies, database, registration policy,
  provider application credentials, job intervals, backup policy
- **user account:** locale, timezone, content defaults, integrations, notification rules
- **device/local storage:** theme, sidebar state, density, and other device appearance
- **shared server metadata:** TMDb credential and keyless metadata providers; users should
  not each need to register metadata API credentials

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
- an admin-only disaster backup is distinct from a portable user export
- restore is tested into an empty server in CI; PostgreSQL remains beta until that gate
  and a release-candidate Compose recovery drill pass

The SQLite server profile must ship before PostgreSQL. It uses WAL, transactional writes,
online snapshots, bounded retention, integrity checks, and restore verification. A full
backup is not created after every edit. The WAL provides immediate durability, while
scheduled snapshots and a non-sensitive audit/change journal provide disaster recovery
and traceability without unbounded storage growth.

## Native mobile, home-network sync, and future iCloud boundary

The future iOS onboarding flow should ask where the user's authoritative library lives:

1. **This device/local** — useful for a standalone preview or later migration.
2. **Connect to PMT Server** — discover a server on the LAN or enter its HTTPS URL, verify
   its identity/certificate and API compatibility, then sign in or redeem an invitation.
3. **iCloud library** — a later, separate CloudKit-backed mode, unavailable until its data
   model, migration, privacy, conflict, and recovery behavior are implemented.

For a PMT Server profile, iCloud contains no canonical PMT library data by default. The
device keeps an encrypted/bounded cache for offline reading and a durable outbox of user
edits. Authentication tokens belong in Keychain, server identity pinning belongs in the
device connection profile, and server credentials or database backups do not belong in
iCloud key-value storage. Device-only appearance preferences may later use Apple's
preference synchronization, but that is independent of library synchronization.

When the device is on its home network—or connected through an explicitly configured
private route such as Tailscale—it sends idempotent outbox operations to the PMT Server.
Each operation carries the account, device ID, request ID, base record version, and client
timestamp. The server remains authoritative, returns the resulting version, and rejects a
stale mutation with a structured conflict. The client never writes directly to SQLite.

If CloudKit is eventually offered, it is an alternative backend for users without a PMT
Server, not a mirror automatically layered over the server. Moving between CloudKit and a
self-hosted server is an explicit, resumable migration/export operation with counts,
conflict review, rollback, and a cutover point after which only the selected destination
accepts writes.

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
- admin/user job status surfaces redact payloads and credentials

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

Do not add recommendations to the 2.5.x stability patch line. Record the contracts now,
complete user ownership and durable jobs first, and ship recommendations behind a beta
capability gate after at least one stable multi-user foundation release.

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

Add recommendation tables only after `user_accounts` and user-scoped catalog ownership
exist:

- `recommendation_engine_configs`
  - installation-scoped engine slug, enabled/beta state, endpoint secret reference,
    capabilities, timeout, safe resource limits, and health state
- `user_recommendation_preferences`
  - `user_id`, selected engine, enabled modes, excluded statuses, maturity filters,
    discovery/novelty preference, advanced-processing consent, and feedback retention
- `recommendation_candidate_snapshots`
  - catalog item, source, source identity, discovery reason, bounded source score,
    fetched/expiry times, metadata revision, and provenance
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
- candidate snapshot uniqueness scoped by catalog item/source/source identity
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
3. Add user-owned recommendation tables after multi-user ownership is available.
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

Add:

- `notification_endpoints`
  - `user_id`, label, adapter type, protected secret reference, enabled, verified time,
    failure state
- `notification_rules`
  - `user_id`, event types, lead times, quiet hours, timezone, endpoint IDs
- `notification_inbox`
  - user-scoped in-app event, read/dismiss state, safe structured payload
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
- admin-only backup/job failure

Do not send every list edit externally by default. Keep collaboration activity in-app and
let users opt into a digest later.

### Apprise

Define a notification adapter interface, then provide:

1. embedded Apprise Python library in an optional `notifications`/server extra for the
   easiest Compose setup
2. optional Apprise API adapter for administrators who already run a separate Apprise API
   service

Apprise destination URLs contain credentials and must live in `SecretStore`, never the
database, logs, exports, test snapshots, DOM, or API responses. Validate allowed schemes,
bound message length, exclude notes/ratings/refinement text, and provide a “Send test”
operation. Document that arbitrary notification destinations create outbound network
traffic and should be limited to trusted server users.

Apprise does not replace native mobile push. A future iOS app would need APNs or local
notifications as another adapter.

## Integration platform completion

### Shared adapter contract

Extend the existing provider registry rather than build each integration directly into
routes. Every adapter must support:

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
Store OAuth authorization state server-side, keep access/refresh tokens in per-user secret
namespaces, rotate single-use refresh tokens atomically, and show expiry/reconnect state.

The self-hosting operator will generally need to register an OAuth application and set its
client ID/secret because callback URLs are installation-specific. Setup UI should generate
the exact callback URL and never pretend this burden can be eliminated.

### Media-server user mapping

Jellyfin/Plex/Emby connections are often server-wide while playback identities are
per-person. Model this explicitly:

- an admin creates the media-server connection
- `integration_user_bindings(connection_id, remote_user_id, pmt_user_id)` maps selected
  remote users to PMT users
- unbound remote users are ignored and visible only as redacted setup candidates
- one remote user cannot map to multiple PMT users on the same connection
- normal users cannot change the server token or another user's binding

### Jellyfin — first playback adapter

Jellyfin is the best first media-server vertical slice because its official Webhook plugin
can target selected users and notification types without requiring a commercial PMT
service.

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

First release:

- authorization-code or device-code setup
- pull watch history, ratings, watched progress, and watchlist
- rotate Trakt's single-use refresh token atomically
- incremental pagination/checkpoints and periodic schedule
- dry-run counts and conflict preview
- no push, scrobble, deletion, or remote mutation

Add optional push only after explicit direction controls, loop prevention, rollback tests,
and provider-specific conflict rules are complete.

### AniList and Kitsu

These can follow Trakt but may deliver an earlier read-only beta because PMT already stores
AniList/Kitsu/MAL identities.

- start with public/read-only list import where provider policy permits it
- add authenticated private-list access separately
- normalize each user's score format into PMT's 1–10 decimal scale while retaining raw
  source values
- map current/completed/planning/paused/dropped/repeating status explicitly
- import progress, repeats, start/end dates, and score without inventing watch dates
- respect AniList's current rate limit/degraded limit and expose reconnect before token
  expiry where refresh is unavailable
- add a planned Kitsu account-import definition; Kitsu is currently metadata support, not
  a completed PMT tracking adapter

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

Settings → Access & Devices becomes two layers:

- personal local mode explanation and activation path
- admin-only Shared Server panel: users, invitations, registration policy, OIDC, database,
  backup health, workers, and server-wide provider credentials

Do not expose server administration to ordinary users. Normal users get Account, Sessions,
Integrations, and Notifications settings.

### Accounts

- profile/avatar monogram and account switch/sign-out control
- session/device list with revoke actions
- invitation acceptance and first-password flow
- disabled-account and expired-invitation states
- OIDC buttons only for providers the server account configured successfully

### Shared lists

- private/shared visibility indicator
- member avatars/monograms and owner/editor/viewer badges
- share dialog by exact username or invitation
- activity summary and conflict feedback
- “Add to my library” on untracked shared-list titles
- no private rating/note shown on a shared list unless the viewer is looking at their own
  data

### Notifications

- in-app inbox with unread count, filters, mark read/dismiss
- rule editor organized by Releases, Collaboration, Integrations, and System
- endpoint cards with protected destination summary, Send test, last success, and pause
- timezone/quiet-hour preview

### Integrations

- available adapters only; planned providers remain hidden from ordinary setup
- connection wizard: prerequisites → authorization/token → user mapping/capabilities →
  dry run → enable schedule
- explicit Pull only/Push only/Both labels; start with Pull only
- last run, next run, safe counts, reconnect/pause, and conflict queue

## API additions

Keep existing endpoints during migration, then establish a versioned boundary suitable for
native/mobile clients and server capability negotiation:

```text
/api/v1/me
/api/v1/server/capabilities
/api/v1/server/readiness
/api/v1/sync/push
/api/v1/sync/pull
/api/v1/auth/sessions
/api/v1/admin/users
/api/v1/admin/invitations
/api/v1/admin/identity-providers
/api/v1/lists/{id}/members
/api/v1/lists/{id}/activity
/api/v1/recommendations/readiness
/api/v1/recommendation-runs
/api/v1/recommendation-runs/{id}
/api/v1/recommendation-results/{id}/feedback
/api/v1/me/recommendation-profile
/api/v1/notifications
/api/v1/notification-endpoints
/api/v1/notification-rules
/api/v1/integrations/connections
/api/v1/integrations/oauth/{provider}/start
/api/v1/integrations/oauth/{provider}/callback
/api/v1/webhooks/{provider}/{public_id}
```

Web browser authentication continues using Secure cookies plus CSRF. Native-client support
is now a concrete requirement, but bearer/device tokens should land only with the remote
client boundary in order 8. Tokens need narrow scopes, rotation/revocation, device
identity, secure Keychain storage, short access-token lifetime, and separate tests from
browser sessions. Passwords are exchanged only with the authenticated server and are not
stored by the client.

## Migration and release strategy

### Database migration sequence

Use small reversible Alembic revisions rather than one giant migration:

1. add `user_accounts`; create/backfill the legacy local/admin user
2. add nullable `user_id` to ownership roots; backfill and validate
3. add new user-scoped unique indexes; remove incompatible global indexes
4. remove `WatchEntry.catalog_item_id` global uniqueness and add user/catalog uniqueness
5. move season records to catalog ownership and verify episode/viewing counts
6. add sessions/identities/invitations and replace owner session tables
7. add list membership/activity and migrate list items to catalog references
8. add recommendation preferences/runs/results/feedback/evaluation records
9. add notification inbox/outbox/endpoints/rules
10. add media-server user bindings and scheduled-job leases
11. make required ownership columns non-null after validation

Each upgrade should write aggregate validation counts only, take a safety backup on SQLite,
and refuse to continue if ownership cannot be proven. Test upgrades from real historical
schema versions using synthetic fixtures, never a personal database.

### Feature gates

- schema can ship before UI only if local mode behaves identically
- multi-user server activation remains hidden until route-isolation tests are complete
- list sharing remains hidden until catalog-based list migration is complete
- recommendations remain hidden until candidate coverage, baseline comparisons,
  explanations, exclusions, and per-user deletion pass; the advanced engine remains a
  separately gated beta
- adapters stay unavailable until real fixture contracts and disconnect behavior pass
- PostgreSQL stays beta until upgrade, backup, restore, and Compose smoke tests pass
- direct social presets stay beta independently of generic OIDC

Do not label the next build 3.0 solely because tables were added. A 3.0 designation makes
sense when multi-user Shared Server, migration/rollback, user isolation, shared lists,
backups, and at least one notification and integration path are stable together.

## Testing and security gates

### Mandatory multi-user tests

- two users can track the same catalog item independently
- each sees only their entries, histories, rankings, comparisons, imports, integrations,
  notifications, exports, and calendar feed
- guessed UUIDs for every resource return 404/403 without revealing existence
- an admin cannot read another diary through ordinary member routes
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
- per-user portable export round trip and admin disaster recovery

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
| 1 | Architecture contracts, threat model, synthetic legacy fixtures | 4/10 | ADRs define shared/private data, admin powers, migration/rollback, and provider boundaries. |
| 2 | Shared catalog and catalog-owned episode schedule refactor | 9/10 | Two synthetic users can follow the same series without duplicate/moved episode records. |
| 3 | User ownership schema and legacy single-user backfill | 10/10 | Existing database migrates to one user with identical aggregate and record-level data. |
| 4 | Request principal and tenant-scoped service/API refactor | 10/10 | Complete two-user IDOR/isolation matrix passes for every route and export. |
| 5 | Multi-user local password auth, admin, invitations, recovery, and sessions | 9/10 | Invite-only server supports create/login/disable/recover/revoke without weakening local mode. |
| 6 | Headless PMT Server runtime, admin bootstrap, OCI image, and Compose lifecycle | 7/10 | The same build runs without a desktop session, survives restart, reports compatibility/readiness, and completes secure first-run setup. |
| 7 | SQLite server backup/restore, retention, audit journal, and recovery verification | 7/10 | Scheduled online backups restore into an empty test instance and never include live sessions or secrets. |
| 8 | **Implemented:** versioned native-client API, server connection profiles, and device sessions | 8/10 | Reference client verifies identity/capabilities, signs in, rotates/revokes device tokens, and never opens the server database. |
| 9 | **Implemented:** optimistic concurrency, idempotent outbox sync, reconnect behavior, and offline policy | 9/10 | Replays apply once, stale entry/list mutations become reviewable conflicts, and reconnect tests retain queued work. |
| 10 | **Implemented:** shared lists, memberships, roles, activity, and list notifications | 9/10 | Owner/editor/viewer rules, catalog list items, per-viewer state, UI, and API isolation tests pass. |
| 11 | **Implemented:** durable database-leased job runner and integration scheduler | 8/10 | Jobs coalesce, lease, retry, pause/resume, repeat after restart, and expose redacted status. |
| 12 | **Implemented (PostgreSQL beta):** dialect support, Compose override, backup/restore | 8/10 | SQLite tests pass locally; PostgreSQL migration/runtime/dump/restore runs in dedicated containerized CI before release. |
| 13 | Recommendation domain, privacy preferences, and bounded candidate acquisition | 8/10 | Candidate provenance/coverage, user isolation, retention, deletion, and DTO contracts pass. |
| 14 | Built-in lightweight recommendation baseline | 7/10 | Exclusions, deterministic scores, explanations, diversity, and trivial-baseline comparisons pass. |
| 15 | Optional advanced recommendation worker extraction and hardening | 9/10 | No duplicate library, hard-coded user/taste data, unsafe artifacts, or direct PMT DB access remains. |
| 16 | Recommendation UI, feedback separation, shadow evaluation, and beta rollout | 8/10 | Standard fallback, honest confidence, feedback semantics, accessibility, and cohort gates pass. |
| 17 | In-app notification inbox, transactional outbox, Apprise delivery | 7/10 | Dedupe/retry/quiet-hours/test-delivery pass; secrets are absent from all outputs. |
| 18 | Per-user OAuth connection framework for tracking providers | 8/10 | State/PKCE/token rotation/reconnect and per-user credential isolation pass. |
| 19 | Jellyfin webhook vertical slice and remote-user mapping | 7/10 | Synthetic completed movie/episode events update only the mapped PMT user once. |
| 20 | Trakt read-only history/list/rating import plus periodic pulls | 8/10 | Dry run, cursor, refresh-token rotation, conflict policy, and scheduler pass. |
| 21 | AniList and Kitsu read-only/authorized imports | 7/10 | Status/progress/repeat/date/score mappings and rate-limit behavior pass. |
| 22 | MyAnimeList and Simkl read-only imports | 8/10 | OAuth, terms gates, cursors, mappings, and disconnect/reconnect pass. |
| 23 | Plex and Emby playback adapters | 8/10 | Versioned fixtures, subscription prerequisites, identity mapping, and dedupe pass. |
| 24 | Generic OIDC login | 8/10 | Invite/linking policy and complete OIDC security matrix pass with a real test IdP. |
| 25 | Optional Google/GitHub/Discord login presets | 6/10 | Each provider has isolated config, callback, claims, linking, and regression tests. |

Steps 2–5 are the critical path and should not be parallelized as independent feature
branches. Recommendation contract work may begin during step 1, but recommendation schema
or implementation must wait for tenant ownership; the advanced engine waits for the
durable job runner in step 11. After step 5, OIDC research, PostgreSQL portability,
recommendation evaluation fixtures, and notification adapter work can proceed in parallel
only if all branches use the accepted ownership model.

## Suggested release groupings

1. **Internal foundation release:** orders 1–4; no advertised multi-user UI.
2. **Shared Server foundation:** orders 5–7; invite-only auth, headless SQLite deployment,
   and tested recovery before remote native clients are advertised.
3. **Remote client beta:** orders 8–9; versioned device sessions, offline outbox, and
   conflict-safe reconnection.
4. **Household collaboration and reliability:** orders 10–12; shared lists, durable jobs,
   and optional PostgreSQL.
5. **Recommendation beta:** orders 13–16; standard engine first, advanced worker optional
   and off by default.
6. **Notifications and first automation:** orders 17–20; Apprise, OAuth framework,
   Jellyfin, and Trakt pull.
7. **Import breadth release:** orders 21–23.
8. **Federated login release:** orders 24–25 after core account recovery and isolation have
   had at least one stable release in real self-hosted use.

## Feasibility conclusions

- **Central household server:** highly feasible because the network/security shell already
  exists; data ownership is the expensive part.
- **Individual accounts:** feasible but the highest-risk change in this proposal.
- **Shared lists:** feasible after catalog/list schema refactoring; should not share private
  watch-entry records.
- **In-app and Apprise notifications:** highly feasible; release events and provider
  definitions already exist.
- **SQLite and PostgreSQL Compose:** feasible. SQLite remains simpler; PostgreSQL requires
  real migration/backup tests, not only installing a driver.
- **OIDC:** feasible and valuable. Generic OIDC is a better PMT target than claiming direct
  support for 100 providers.
- **Jellyfin:** high feasibility and best first playback adapter.
- **Plex/Emby:** feasible with clearer paid/plugin/version prerequisites and more fixture
  research.
- **Trakt/AniList/Kitsu/MAL/Simkl periodic imports:** feasible on the existing integration
  foundation, but each is a real product slice with OAuth, rate limits, terms, mappings,
  and conflict behavior—not a single generic “import API” task.
- **Standard recommendations:** highly feasible after tenant ownership and candidate
  acquisition. PMT already holds high-value personal signals and normalized metadata.
- **Advanced local recommendations:** feasible but should remain optional. The prototype
  supplies valuable algorithms and tests, while its duplicate application shell,
  hard-coded user assumptions, heavy dependencies, and artifact handling require a
  deliberate extraction rather than a merge.
- **Native iOS recommendations:** feasible through the PMT API and cached results. Directly
  embedding the Python ML stack in iOS is neither necessary nor recommended.

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
- [AniList API and current rate limits](https://docs.anilist.co/guide/rate-limiting)
- [Kitsu API documentation repository](https://github.com/hummingbird-me/api-docs)
- [SQLAlchemy PostgreSQL/psycopg support](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html)
- [PostgreSQL `pg_dump`](https://www.postgresql.org/docs/current/app-pgdump.html)
- [Docker Compose profiles](https://docs.docker.com/compose/how-tos/profiles/)
