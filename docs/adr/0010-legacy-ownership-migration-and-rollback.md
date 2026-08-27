# ADR 0010: Legacy ownership migration and rollback

Status: accepted

Date: 2026-08-26

## Decision

The legacy single-owner database migrates deterministically to one active admin subject.
If an owner account exists, its immutable ID and password hash are reused. Otherwise PMT
creates the built-in local subject `00000000-0000-0000-0000-000000000001` without a
password. Every legacy private ownership root is backfilled to that subject.

Migration is split into two reversible revisions:

1. `0012` moves seasons from `watch_entries` to their existing `catalog_items` and proves
   that every season has a catalog owner before dropping `entry_id`.
2. `0013` creates users/preferences, backfills all private roots, makes ownership non-null,
   replaces global uniqueness with per-user uniqueness, and moves poster overrides from
   shared catalog rows to private watch entries.

Both revisions refuse to continue when ownership cannot be proven. The application keeps
its existing pre-migration SQLite safety backup behavior.

## Preservation contract

Upgrade must retain every existing primary key and every domain value, including dates,
notes, ratings, histories, assessment evidence, schedule/episode IDs, list membership,
import state, integration state, and calendar token hashes. Only ownership columns and the
location of schedule/artwork ownership may change.

Synthetic revision-0011 fixtures—not personal data—are the regression source. Tests
compare record-level sentinel values and aggregate counts before and after upgrade.

## Rollback contract

Rollback to the single-owner schema is supported only while private records belong to at
most one user. Revision `0013` refuses downgrade when any owned root has multiple distinct
owners. Once that guard passes, `0012` can map each catalog schedule back to the sole
entry. This avoids silently merging or discarding tenants.

Rollback is a schema recovery path, not an account-deletion mechanism. Operators must
export and deliberately remove additional tenants before attempting it.
