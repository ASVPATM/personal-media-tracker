# Multi-user foundation threat model

Status: accepted for roadmap orders 1–4

## Assets and trust boundaries

The protected assets are personal notes, ratings, dates/history, refinement evidence,
lists, import contents, integration configuration/credentials, preferences, release
state, feeds, and exports. Provider metadata and normalized schedules are shared cache
data, not authorization evidence.

Requests cross the HTTPS/browser boundary into FastAPI middleware. Middleware resolves a
session to a request `Principal`; the database session copies that principal into its
request-local context. Background services may cross the same boundary only with an
explicit trusted user ID or a documented installation-wide maintenance scope.

Local mode is a separate trust profile: exactly one active user is resolved without a
login. More than one active user in local mode is an error, not an invitation to select
the first row.

## Primary threats and controls

| Threat | Control in orders 1–4 | Required evidence |
| --- | --- | --- |
| Guessed UUID/IDOR | Ownership is included in every private root lookup; foreign IDs appear missing. | Two-user API matrix for entries, lists, ratings, runs, imports, integrations, releases, and exports. |
| Cross-user list/aggregate leak | List, stats, insights, rankings, profiles, and exports start from the principal's entries. | Distinct sentinel titles/notes never appear in the other user's response. |
| Shared catalog leaks private state | Schedules/metadata stay catalog-owned; poster selection and progress stay entry/user-owned. | Same catalog ID, one schedule, independent progress and artwork. |
| Admin silently reads diaries | Role checks authorize administration only; member services still scope to the admin's own ID. | Admin/member isolation test. |
| Missing principal falls back broadly | Request dependency requires a principal; internal fallback succeeds only with one active user. | Anonymous server request is denied; ambiguous local resolution fails closed. |
| Cross-user child mutation | Services first authorize the owning entry/list/connection/run, then mutate child rows. | Foreign event, episode, assessment, run, and connection IDs cannot be changed. |
| Export of the whole server | Personal exports are scoped; the legacy full-database portable export is admin-only and disabled in server mode. | Every personal export contains only caller sentinels. |
| Migration assigns wrong owner | Deterministic legacy user, non-null validation, refusal on ambiguous legacy owners. | Revision-0011 fixture preserves IDs/counts/values. |
| Rollback merges users | Downgrade refuses when private tables have multiple owners. | Synthetic multi-owner downgrade refusal. |
| Provider selects a victim tenant | Connection ownership comes from principal; coordinator receives only trusted owner ID. | Foreign connection run/list access fails. |

## Explicitly deferred risk

Orders 1–4 establish ownership and isolation but do not advertise multi-user setup. Order
5 must replace/generalize the legacy owner-account/session bridge, add invitation and
account lifecycle flows, and test session disable/recovery. Shared-list ACLs, concurrent
edit versions, PostgreSQL, notifications, and real provider adapters remain gated behind
their later roadmap orders.

## Review checklist

- New private tables have a direct `user_id`, or a documented and tested owned root.
- A route never uses a body/query `user_id` to select tenant data.
- Admin-only file/system operations call `require_admin`.
- Scheduler-wide work is clearly distinct from request work and re-enters services with
  the owning user ID.
- Logs contain aggregate outcomes and opaque IDs, not notes, credentials, or import rows.
- Any new export is included in the two-user isolation matrix before release.
