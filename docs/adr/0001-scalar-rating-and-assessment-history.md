# ADR 0001: Canonical scalar rating with optional assessment history

Status: Accepted

## Context

`WatchEntry.personal_rating` is a nullable user-owned 1–10 value in one-decimal
increments. Existing editing, filtering, sorting, imports, CSV exports, statistics, and
profiles depend on that contract. Guided questions must help without reinterpreting old
ratings or making advanced work mandatory.

## Decision

Keep `personal_rating` as the only canonical personal score. Store guided work in
additive `RatingAssessment` records with versioned answers, derived rubric values, an
optional private reflection, lifecycle state, optimistic version, and the scalar value
captured at completion. At most one draft exists for an entry and rubric version.
Reassessment supersedes the previously current completed assessment without deleting
history. Only an explicit completion choice may update the scalar.

Ordinary CSV continues to contain only the scalar. Full backups and the deliberately
private advanced-rating JSON export contain structured evidence. Ranking payloads,
diagnostics, logs, and notifications never contain reflections.

## Consequences

Old libraries migrate additively and remain immediately usable. Disabling advanced
ratings hides tools but retains evidence. Downgrading the application after creating
structured evidence may make that evidence inaccessible, so a full backup is required
before downgrade.
