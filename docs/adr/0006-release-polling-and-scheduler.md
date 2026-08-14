# ADR 0006: Bounded in-process release polling

Status: Accepted

## Context

Followed series need provider refresh, catch-up after downtime, retry/backoff, and a
single scheduler owner. The initial product is one process and does not justify Redis,
Celery, or a second worker system.

## Decision

Normalize provider seasons and episodes in additive tables. Use an idempotent sync
service for manual refresh and bounded startup catch-up. A small in-process scheduler
claims a persisted lease for periodic polling; SQLite single-instance locking ensures
one process, and the lease prevents accidental duplicate ownership. Provider and job
failures use bounded exponential backoff with jitter and preserve the last successful
data.

Air dates, provider availability claims, and metadata freshness remain distinct. A
passed air date never marks an episode watched or changes show status. Local mode offers
a downloadable iCalendar snapshot. Server mode additionally offers a revocable,
unguessable bearer URL whose feed contains only series title and air date.

## Consequences

Polling stops while the app/host is closed and catches up on next start. A durable
distributed queue remains unnecessary unless a future multi-process architecture is
approved through another ADR.
