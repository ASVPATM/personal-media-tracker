# ADR 0004: One application server owns cross-device history

Status: Accepted

## Context

The same library may eventually be used from macOS, Linux, and browser-capable devices.
Copying a live SQLite file between computers creates locking, ordering, and corruption
risks; SQLite WAL does not operate across network filesystems.

## Decision

Cross-device access uses one FastAPI process that owns one database on host-local
storage. Every client uses the authenticated HTTPS API. SQLite is supported for a
single-owner, low-concurrency, single-process deployment; multiple workers and live
database-file synchronization are rejected. A database URL seam documents a later
PostgreSQL path if measured concurrency requires it.

Full archive backup/restore is the supported host-move mechanism. Tailscale or a reverse
proxy may provide the private HTTPS network boundary, but the application will not
automate third-party accounts or networking.

## Consequences

The host must stay awake and reachable. Two hosts must never concurrently own copies of
the same live database. Server activation is an explicit, reversible Settings workflow
that creates a backup first and requires a restart; it does not move or rewrite the
owner's media data.
