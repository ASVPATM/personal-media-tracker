# Insights calculations

The Insights page is a read-only view of the active local library. Its filters are
applied once on the server so the overview, timeline, rating curve, genre ratings,
breakdowns, callouts, and drill-downs all describe the same scope.

## Scope and filters

- **All time** includes dated and undated stored viewings. Undated records contribute
  to appropriate totals but are never assigned an invented date.
- **This year**, **90 days**, **30 days**, and **Custom** use inclusive dates in the
  interface and half-open boundaries internally.
- Media type, exact genre, current library status, and first/rewatch filters combine.
- Non-all-time scopes include only titles with a title or episode viewing in that
  period. Planned titles therefore never inflate period activity.
- Filters live in the URL and are restored after refresh. Library search, sorting,
  and pagination parameters remain separate.

The previous-period comparison uses the immediately preceding range of equal length.
All-time metrics deliberately have no comparison because there is no equivalent prior
all-time period.

## Definitions

- **Titles watched:** distinct active library entries with at least one title or
  episode viewing in scope.
- **Title viewings:** stored title-level viewing events plus an undated remainder when
  an imported `view_count` is greater than the number of dated events.
- **Episodes watched:** stored episode-viewing records. Provider air dates do not count.
- **Estimated watch time:** movie runtime multiplied by movie viewings, plus stored
  episode runtimes for TV and anime. A catalog episode runtime is used only as the
  fallback for a stored episode viewing. Unknown runtimes are omitted and the interface
  reports how many viewing records had usable runtime evidence.
- **Average and median rating:** personal ratings across distinct watched titles in the
  current scope. Planned titles are excluded, rewatches do not weight a title more
  heavily, and technical ranking scores are not used.
- **Repeat viewings:** title rewatches plus repeated viewings of the same stored episode
  in scope. The rewatch callout links to titles with title-level repeat records.
- **Genre ratings:** the visible value is the raw personal-rating average and includes
  the rated-title sample size. A small confidence adjustment is used only for ordering;
  a genre needs at least three rated titles before it can be called a favourite.

A title with several genres contributes once to each genre, so genre rows should not be
added together as though they were mutually exclusive.

## Incomplete data

The timeline reports dated and undated event counts and its date coverage. Undated
imported history appears in all-time totals but is excluded from timelines and dated
comparisons. PMT does not infer watch dates, viewing time of day, runtimes, or provider
availability.

When a scope has no dated activity, the interface offers an optional interactive
release-era view. It groups watched titles by their metadata release decade and opens
the matching titles on selection. This is library context, not a substitute or inferred
date for when anything was watched.

The dashboard uses automatic weekly, monthly, or yearly aggregation according to the
selected span. Each chart value opens the matching title drawer, making deterministic
callouts and aggregate values directly inspectable.

## Implementation choices

The initial implementation uses accessible HTML/CSS bars and a focusable SVG timeline,
with no charting dependency. Requests are debounced and stale requests are cancelled.
No new database indexes or aggregate cache were added without measurements: PMT remains
a single-owner local application, and the current eager-loaded calculation preserves the
existing SQLite model and viewing semantics. Benchmark query plans before introducing
either optimization.

The workspace background image is unrelated to Insights data. It is optimized and kept
in the device-local configuration directory, excluded from portable backups and exports,
and never sent to a provider.
