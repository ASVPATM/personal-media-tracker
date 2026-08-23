# Expansion implementation plan and work log

This file records the staged implementation authorized by
the owner's expansion specification. The source prompt remains a private, ignored
planning artifact and is not modified or included in distributions.

## Verified baseline

- Repository: `main` at tagged release `v2.0.2` (`1ff6117`).
- Existing user change at start: only the untracked expansion prompt.
- Python 3.11+; FastAPI, SQLAlchemy, Alembic, SQLite, vanilla HTML/CSS/JavaScript.
- Baseline on 2026-08-13: Ruff check and format-check passed; 81 non-browser tests and
  one Playwright browser test passed.
- Reference screens: the synthetic, tracked images under `docs/screenshots/`.
- PMT is MIT licensed. Yamtrack is AGPL-3.0; no Yamtrack code, assets, prose, or visual
  expression may be copied.

## Compatibility contracts

- `WatchEntry.personal_rating` remains nullable, 1–10, and limited to tenths.
- Existing scalar create/edit/filter/sort/review/import/CSV/statistics/profile behavior
  stays authoritative. Technical rankings are additive and never feed Insights.
- Provider refresh owns provider metadata, not ratings, notes, history, answers,
  comparisons, or manual corrections.
- Full database archives are authoritative for transfer. CSV remains intentionally
  narrower. Credentials and server/session secrets never enter backups.
- Default local mode stays loopback-only, unauthenticated, and single-instance.

## Milestones

- [x] Milestone 0: baseline, contracts, six ADRs, migration/API plan.
- [x] Milestone 1A: left navigation and relocated existing controls.
- [x] Milestone 1B: optional advanced assessments, comparisons, Rankings, portability,
  accessibility, performance fixture, and browser flow.
- [x] Milestone 2: normalized series/season/episode tracking and manual/startup sync.
- [x] Milestone 2B: bounded scheduler, internal release-event storage, month calendar,
  local ICS snapshot. The public notifications UI is deferred.
- [x] Milestone 3: fail-closed authenticated single-owner server mode and operations docs.
- [ ] Milestone 4: deferred; mobile/PWA requires separate owner authorization.

## Additive migration sequence

1. `0004`: rating assessments and canonical pair comparisons.
2. `0005`: series subscriptions, seasons, episodes, episode viewings, and release events.
3. `0006`: single-owner account, revocable session, and login-throttle state. Scheduler
   lease/notification state is fully represented by `0005`.
4. `0007`: revocable, read-only iCalendar feed tokens once authenticated server routing
   exists.
5. `0008`: resumable focused/full rating-refinement progress with explicit comparison and
   assessment stages.

Migrations are nullable/additive, cascade from existing user-owned entries where
appropriate, and do not backfill or reinterpret scalar ratings.

## Refinement follow-up — 2026-08-13

- Replaced standalone suggestion entry points with one focused/full refinement workflow,
  staged progress, a v2 evidence rubric, and persistent run state for future Insights.
- Kept scalar ratings authoritative and made stored rewatches context-only rather than an
  automatic ranking bonus.
- Fixed custom-accent persistence, writable packaged server configuration, macOS keyboard
  navigation, entry-action state/placement, and Currently Watching information order.
- Verification: 106 non-browser tests and the full Playwright browser journey pass.

## Metadata-resolution follow-up — completed for 2.1.5

Implemented with bounded evidence rules and synthetic regression coverage; no personal
library data was used.

- Correct provider matches are still being left unresolved when a search returns exactly
  one result. A single result should be attached automatically when its detail request
  succeeds and its media type and known release year do not contradict the imported entry;
  a title alias alone should not prevent that attachment.
- When several results remain, the provider's first-ranked result is often correct. Define
  and test a bounded policy that can accept the first result when it clearly leads on title
  relevance, compatible year, provider ranking, and popularity. Do not rely on popularity
  or list position alone when evidence conflicts.
- Record safe aggregate skip reasons in enrichment status—no results, ambiguous ranking,
  conflicting year/type, duplicate provider identity, detail failure, or provider outage—so
  a correct candidate is not reported merely as an unexplained unresolved title.
- Add regression coverage for a correct single non-identical alias, a clearly dominant first
  result, a contradictory single result that must remain unresolved, duplicate-identity
  protection, detail-fetch failure, and anime searches using TMDb fallback while preserving
  the anime classification.
- Validate with synthetic equivalents of the remaining import shapes. Never read, copy, or
  modify the owner's real library as a test fixture.

Completion note: compatible single aliases and clearly leading small result sets can now
resolve after a successful detail lookup. Contradictions remain unresolved, and enrichment
aggregates no-result, ambiguity, year/type conflict, duplicate identity, detail failure, and
provider-outage reasons. Anime TMDb fallback continues to preserve anime classification.

## API boundary

Existing entry and scalar routes remain unchanged. Additive namespaces are
`/api/ratings/*`, `/api/rankings`, `/api/series/*`, `/api/releases/*`, and later
`/api/auth/*` plus `/api/server/readiness`. Server-side services validate every answer,
derive every score, own optimistic concurrency, canonicalize comparison pairs, and
redact private reflection. PWA/service-worker routes are out of scope.

## Quality boundary

Each milestone is considered complete only after formatter, lint, unit/integration,
migration, browser E2E, and a primary local browser flow pass. No test may be weakened or
skipped to make a milestone pass. The repository is not committed, tagged, pushed, or
published as part of this implementation task.

## Milestone 1 verification — 2026-08-13

- Desktop navigation now uses the existing PMT visual language in a left rail; the narrow
  fallback remains a top layout rather than introducing the deferred mobile bottom bar.
- Theme stays exclusively in Settings → Appearance. Import, all five exports, backups,
  restore, and legacy migration stay in Settings → Data & Backup.
- Advanced ratings default off. Guided drafts, completion history, short comparisons,
  undo, personal/technical modes, filters, explanations, and private structured export
  are implemented without changing scalar-rating or Insights semantics.
- Verification: Ruff check, 92 non-browser tests, and the full Playwright browser journey
  pass. The deterministic 1,000-title ranking fixture remains under its two-second guard.

## Milestone 2 verification — 2026-08-13

- Verified TMDB TV identities can be followed without changing title status. Normalized
  seasons/episodes, explicit episode viewing, confirmed bulk actions, progress, Up Next,
  specials preference, spoiler concealment, and freshness/failure state are complete.
- Manual, on-start, and bounded periodic polling share one idempotent sync path. Provider
  fetches finish before atomic writes; stable IDs update in place; removed/rescheduled
  records, unknown dates, partial/malformed responses, cache retention, lock ownership,
  shutdown, and exponential backoff are covered by deterministic fixtures.
- Active Shows owns compact upcoming information, a month calendar, explicit episode
  actions, and a local one-year `.ics` snapshot. Its notifications button clearly marks
  the alert interface as under development. Air dates are never called streaming
  availability and JustWatch data is not fetched.
- Verification: 97 non-browser tests at the release boundary and the full Playwright flow
  passed, including follow, sync, mark watched, Up Next, the month calendar, and the
  deferred notification state.

## Milestone 3 verification — 2026-08-13

- Local mode remains unauthenticated and loopback-only. Shared access requires an explicit
  local preflight, safety backup, owner setup, restart, exact HTTPS origin/host/proxy
  configuration, and a strong persisted secret; unsafe startup fails before serving data.
- Passwords use `pwdlib`'s recommended Argon2id profile. Random opaque sessions are stored
  only as keyed hashes and use Secure/HttpOnly/SameSite cookies; mutations require a
  per-session CSRF token. Sessions expire/revoke, password changes revoke all sessions,
  bootstrap locks after one owner, and login failures receive generic bounded backoff.
- Portable archives scrub all owner/session/throttle records and exclude application and
  provider secrets, including calendar feed tokens. Server restores require returning to
  local-only first. A persistent
  daily backup job retains a bounded set and records safe retry state on disk failures.
- Access & Devices exposes local/server state, readiness remediation, activation, password,
  revoke, sign-out, and return-to-local controls. Native Linux, Tailscale Serve, Docker/
  Caddy, backup/restore, disaster recovery, and host-move procedures are documented.
- Verification: 105 non-browser tests and the expanded full Playwright journey pass. The
  server-focused suite covers fail-closed configuration, owner lockout, unauthorized read
  denial, login cookies, CSRF, password/session lifecycle, expiry, throttling, host/origin/
  HTTPS rules, activation file permissions, credential-scrubbed archives, and scheduled
  backup retention. Ruff, JavaScript syntax, package build, pinned container build and
  health smoke test, Compose configuration, dependency audit, and a 3,000-title synthetic
  performance gate also pass.
