# Move a Personal Media Tracker library

The browser/server and desktop editions use the same core SQLite data model. The safest
move is a full-fidelity **Export everything** archive, not a CSV import.

## Recommended: export everything

1. Start the existing browser/server tracker and confirm that the library looks right.
2. Open **Settings → Data & Backup → Export everything**. This uses SQLite's online
   backup API, so it produces a consistent snapshot even while the server is running.
3. Keep the downloaded ZIP unchanged and keep the old installation as a temporary
   fallback.
4. Open the desktop app, then open **Settings → Data & Backup**.
5. Expand **Exact app-to-app transfer**, select the ZIP, and choose **Inspect migration
   file**.
6. Compare the active-title, viewing-event, and deleted-title counts with the old
   tracker. The inspection is read-only and cannot replace the current desktop library.
7. Choose **Import this verified library**. The app verifies the exact file again,
   safety-backs up the current desktop database, migrates older schemas when needed, and
   runs SQLite integrity checks before reporting success.
8. Spot-check several ratings, notes, tags, dates, and rewatches. Open Insights to confirm
   the expected totals, then create a fresh backup before retiring the old installation.

The archive preserves the complete database, including catalog metadata and provenance,
all personal fields, individual viewing events, import history, audit history, and
recoverable soft-deleted titles. It also transfers theme, timezone, language, region, and
onboarding preference. Statistics are derived from the preserved records and are
recalculated by the desktop app, so there is no separate statistics file to lose.

TMDB credentials are deliberately excluded. Configure the token once in the desktop
app's Metadata settings; it will use an unencrypted local configuration file with
user-only permissions by default. The operating-system credential vault is optional and
may trigger an authentication prompt.
Window size and position are also excluded because carrying them between displays can
place a window off screen.

## Fallback: copy the SQLite database

If the old build does not have **Export everything**, locate its database. A source run
uses `data/watchtracker.sqlite3` by default; an explicit
`WATCHTRACKER_DATABASE_PATH` overrides that location.

1. Stop the old server before manually copying the database. This avoids separating the
   SQLite file from an active `-wal` write-ahead-log file.
2. Copy—not move—the `watchtracker.sqlite3` file somewhere safe.
3. In the desktop app, use **Settings → Data & Backup → Legacy database fallback**.
4. Inspect and import through the prominent migration workflow when possible; raw `.db`
   and `.sqlite3` files are accepted there as well.

A raw database contains the full library and viewing history, but not preferences or
credentials. The app preserves an additional copy of an imported legacy database in its
backups directory.

## Recovery and troubleshooting

- An invalid archive, checksum mismatch, corrupt database, unsupported future format,
  or changed post-inspection file is rejected before replacement.
- Every successful restore/import first creates a `pre-restore-safety-*.sqlite3` copy in
  the desktop backups directory.
- A failed database replacement automatically restores that safety copy.
- Keep the original installation and migration ZIP until the desktop library has been
  verified and backed up.
- CSV remains useful for exchanging visible watch-log rows with other tools, but it is
  intentionally not the disaster-recovery or full-migration format.
