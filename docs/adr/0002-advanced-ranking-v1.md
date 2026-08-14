# ADR 0002: Deterministic advanced-ranking-v1

Status: Accepted

## Context

Optional rubric answers and pair comparisons can refine ordering, but must not become an
opaque replacement for a rating the owner explicitly chose. The result must also remain
fast and reproducible for imported libraries with thousands of rated titles.

## Decision

Implement a pure, uncached `AdvancedRankingService`. `advanced-ranking-v1` uses the
canonical rating as its anchor, blends rubric evidence with `min(0.30, 0.30 * coverage)`,
caps that movement at `0.75`, applies equal-and-opposite logistic comparison residuals
with scale `1.25`, shrinks sparse evidence by `n / (n + 8)`, multiplies its mean residual
by `1.5`, and caps pairwise movement at `0.75`. The final result is clamped to 1–10.

Sorting uses the unrounded technical score, then scalar rating, rubric coverage,
normalized title, and entry ID. Filters apply only after the complete score set is
calculated, so filtering never changes a score. Evidence labels describe input volume,
not truth or statistical certainty. A future formula is a new named version and new
golden fixtures; it never silently changes v1.

## Consequences

Every rated title has an immediate technical score even with no structured evidence.
No materialized cache or invalidation system is needed at current scale. Pair candidate
selection sorts existing titles and scans a bounded neighborhood; it never constructs
all possible pairs.
