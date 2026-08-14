# ADR 0007: Staged rating refinement and advanced-ranking-v2

Status: Accepted

## Context

The first advanced-rating interface exposed independent assessment and comparison tools.
That made it difficult to understand how much work remained, encouraged isolated answers,
and did not persist the owner's progress through a larger library. Automatic rating
suggestions also distracted from the contract that the owner's scalar rating is
authoritative. Stored rewatch totals are meaningful context, but using them as an
automatic quality bonus would systematically distort comfort viewing and imported counts.

## Decision

Replace the independent entry points with one resumable refinement run. The owner chooses
`focused` (up to five useful comparisons and three weakest-evidence titles) or `full`
(a broad bounded comparison target and every rated title). Comparisons are stage one;
structured title evidence and optional private reflection are stage two. Migration `0008`
stores scope, targets, completed pair/title keys, stage, and progress without changing any
existing rating, assessment, or comparison row.

Use `guided-rubric-v2` with six core dimensions: impact, distinctiveness, formula
freshness, engagement, coherence, and lasting value. Optional evidence covers consistency,
personal significance, deliberate return desire, and strengths versus flaws. At least four
core dimensions are required. The UI does not offer an automatic suggested-rating action;
completion records evidence while keeping `WatchEntry.personal_rating` unchanged.

Name the resulting lens `advanced-ranking-v2`. It retains v1's bounded deterministic
blend and stable filtering contract, but identifies the new evidence semantics. Stored
view and rewatch counts are returned and explained as `context_only`; they never enter the
technical-score formula. Historical v1 assessments remain readable and can still provide
bounded evidence until a v2 assessment supersedes them.

## Consequences

Long refinements can be paused and resumed safely, while short refinements remain useful.
Run records and dimension answers can support future Insights without inventing statistics
or retroactively interpreting scalar ratings. A full process can be lengthy by design, so
the UI must always show phase and overall progress. Existing library data and backups
remain compatible because the migration is additive and portable archives contain the
complete database.
