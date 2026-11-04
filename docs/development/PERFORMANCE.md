# Local performance checks

Run from the repository root with the development dependencies installed.

```bash
uv run python scripts/benchmark_local.py
uv run python scripts/benchmark_local.py --collections-only --browser chromium --output metrics.json
uv run python scripts/benchmark_local.py --collections-only --browser webkit --output metrics-webkit.json
```

The harness uses disposable, deterministic 500- and 5,000-entry collections, never your
installed database. It includes multilingual labels, long tracklists and descriptions,
uploaded images and missing metadata. Output contains timings and counts, not library
titles, notes, tokens or request URLs. Browser scenarios block external HTTPS requests.
Full traces are not recorded by default. Keep local metrics out of Git.

Measurements separate page API/serialization, card insertion, first/all visible images,
memory/disk/stale-cache responses and foreground queue time during synthetic bulk work.
The mocked provider delay is stated in the report; it is not a real-provider benchmark.
The baseline unprojected query excludes JSON serialization, so compare it as a diagnostic,
not as a claimed complete before/after application speedup.

Reference targets are a warm page API p95 below 100 ms, cards below 250 ms and warm visible
artwork below 350 ms. These are local reference budgets, not cross-device guarantees.
Uncached images depend on the provider. Inspect cache size/request counts alongside
latency; speeding up one page by crawling the entire library is not an acceptable trade.

## Runtime limits

- Music/Books list queries omit notes, image blobs, descriptions and complete tracklists;
  detail, editing and exports still use full records.
- Adjacent-page warming starts only on Next-button hover/focus, retains at most three
  small snapshots for 15 seconds and downloads at most four covers, one at a time.
- Navigation revisions reject obsolete responses; account, query and mutation boundaries
  invalidate snapshots. Hidden tabs, open dialogs, pending visible images and detected
  data-saving connections suppress speculation. Idle/touch warming is not enabled.
- Downloaded covers: 64 images/16 MiB in memory and 512 images/128 MiB on disk, seven-day
  freshness and up to 30-day stale display with coalesced refresh.
- Public catalog JSON: 256 entries/8 MiB per provider in memory and 32 MiB/2,048 entries
  in one expendable disk cache. Search freshness is one day, ID details seven days and
  empty responses 15 minutes. Explicit retry bypasses empty responses; rate-limit errors
  are not stored as empty results. Expired details may be used for interactive display
  during an outage, never for automatic matching.
- Each catalog has one request lane. Interactive requests precede queued bulk requests;
  a waiting bulk request gets a turn after four interactive requests.
- Fill status uses aggregate counts and at most 100 review rows per response.

Settings → Music/Books → Metadata separates linked identities, genre coverage and locally
stored covers. An image URL is not counted as a successfully downloaded image. Clearing
downloaded covers never removes uploads, library records or backups. On a shared server,
only its server account can clear the common public cover cache.

`PMTMusic.diagnostics()` in the browser console exposes numeric, session-local navigation
metrics only. The authenticated cache endpoint exposes counts/bytes/timings to the local
owner or server account, not provider URLs or personal records.

## Development artifact retention

The helper defaults to report-only. Unknown, unresolved or pinned Flow evidence, private
plans, personal data, referenced artifacts and current build sets are protected.

```bash
uv run python scripts/inventory_artifacts.py --output /path/to/reviewed-manifest.json --recovery /external/path/dated-archive
```

Review the exact candidate paths and recovery destinations. Only then supply the printed
SHA-256 to archive that unchanged manifest:

```bash
uv run python scripts/inventory_artifacts.py --archive /path/to/reviewed-manifest.json --approve-sha256 REVIEWED_SHA256
```

The helper revalidates paths, ignore rules, sizes and modification fingerprints before
moving anything. It refuses protected evidence or active builds and records recovery
locations. Nothing is permanently deleted. An archive on the same disk reduces project
clutter, not total disk usage. Retention is never part of application startup or packaging.
