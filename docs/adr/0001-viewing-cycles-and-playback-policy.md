# ADR 0001: Viewing cycles and playback evidence

Status: Accepted for the Desktop/Web compatibility layer

Date: 2026-08-27

## Decision

PMT stores provider playback as evidence and applies it through one viewing reducer.
Adapters may not increment `view_count`, infer a complete series from an aggregate
progress number, or start a rewatch.

The durable user-history records are:

- a `ViewingCycle` for the initial watch or an explicitly started rewatch;
- a `ViewingEvent` or `EpisodeViewing` for an accepted completion/replay occurrence;
- a `PlaybackBookmark` for meaningful incomplete progress;
- a `ProviderProgressClaim` for imported aggregate state; and
- a `ViewingCorrection` for an explicit user correction or undo.

The existing scalar counters remain compatibility projections while version 2 of the
platform contract is adopted. The occurrence and cycle records are authoritative for
new behavior.

## Policy constants

```text
completion_threshold = 0.90 (user-selectable later from 0.80 through 0.95)
noise_floor_seconds  = min(120, max(30, duration_seconds * 0.02))
resume_floor_seconds = min(120, max(30, duration_seconds * 0.05))
minimum_active_time  = min(600, duration_seconds * 0.25)
cross_provider_duplicate_window = 6 hours
```

A pause never completes media. Start/progress events can only update a bookmark. A
generic terminal event above the completion threshold still requires meaningful active
time; otherwise it is reviewable. A provider-specific strong completion may be accepted
without active-time data, with its lower evidence detail retained.

## Cycles and rewatches

The first accepted completion lazily creates an initial cycle. Rewatch is an explicit
action with title, season, or episode-range scope. Its target episode IDs are snapshotted
when it starts. New episodes do not move that target silently.

Replaying an already completed episode outside an active rewatch creates replay activity
only. It does not reset lifetime coverage or increase a whole-series rewatch count.

## Dedupe and authority

Exact provider event and session keys are permanently idempotent. Strongly matched
cross-provider completions within six hours merge provenance by default. Manual
corrections and explicit PMT actions take precedence over provider snapshots. Aggregate
tracker progress remains a claim and never manufactures episode occurrences or dates.

## Unknown dates and deletion

An unknown watch date remains `null`; migration and import never replace it with today.
New deletions use tombstones. The additive migration can be downgraded because existing
compatibility columns and legacy history tables are preserved throughout this phase.

## Golden timelines

`contracts/viewing-policy/v1/timelines.json` is the executable behavior specification.
Python and future clients must produce the same decisions and compatibility projections
for every scenario in that file.
