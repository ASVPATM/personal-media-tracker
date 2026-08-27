# ADR 0009: Shared catalog and private user state

Status: accepted

Date: 2026-08-26

## Decision

PMT has one installation-wide catalog and strictly user-owned tracking records.

Shared facts are limited to normalized media identity and provider data:

- catalog items, external identities, provider metadata/provenance;
- seasons and episodes attached to a catalog item.

Private state includes:

- library status, personal rating, notes, tags, dates, artwork choice, and history;
- episode progress and release notification state;
- rating assessments, comparisons, and refinement runs;
- lists, imports, preferences, integrations, credentials, and calendar tokens.

`WatchEntry` is the boundary between those layers. A catalog title may have many watch
entries, but only one active/deleted entry for a `(user_id, catalog_item_id)` pair. A
provider schedule is fetched and stored once on `CatalogItem`; each user records progress
against that schedule through their own entry.

API compatibility keeps `catalog_item.poster_override_url` in entry responses, but the
value is populated from the current user's `WatchEntry`. It is not catalog data.

## Authorization contract

Every request receives a `Principal`. Routes do not accept a user ID for choosing whose
private data to load. Services either receive that principal or a `trusted_user_id` from a
bounded scheduler/admin path. A missing or ambiguous principal fails closed.

Administrators do not gain an ordinary API path to another user's private records.
Server administration and diary access are separate powers.

Provider adapters may read shared catalog identity and metadata. Their connections,
secrets, cursors, imported changes, conflicts, and audit records are owned by the user who
connected them. A provider result must never select a tenant from request payload data.

## Consequences

- Two users can track the same title without duplicating provider schedules.
- Shared provider refreshes may update catalog facts visible to both users.
- A catalog deletion would affect every user and is therefore not a member action.
- Shared lists are not included here; their later schema must reference catalog items and
  must never expose the list owner's watch entry.
- Multi-user account management remains gated until the authentication work in order 5.
