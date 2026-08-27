# Personal Media Tracker v2.5.4

This is the recommended desktop release. PMT Server remains an optional, separately
packaged beta; the normal desktop application remains an account-free local library.

## Daily tracking and metadata

- Media tiles can now show compact watched/released episode counters with direct minus and
  plus controls. Progress remains private to the current library, is consistent with the
  title's episode detail view, and can be hidden under **Settings → General → Appearance**.
- Released totals exclude future and undated/TBA episodes whenever schedule data is
  available. Completed titles retain a useful default until the owner explicitly changes
  episode progress.
- Verified Kitsu anime matches now support keyless episode schedules and confirmed air
  dates alongside TVmaze and optional TMDb TV schedules. PMT caches results locally and
  repeated library checks reuse fresh schedules instead of repeatedly calling providers.
- Watching now offers All active & planned, Watching, Rewatching, and Plan to watch scopes.

## Lists and notifications

- Lists are separated into **My lists** and **Shared lists**. A personal list can be shared
  as a versioned PMT list file and imported elsewhere as a read-only snapshot.
- Portable shared-list files contain only list-level title metadata and optional shared
  notes. They do not include personal ratings, tags, viewing history, ranking evidence,
  credentials, sessions, or unrelated library entries.
- Notifications are restored to the main navigation and combine release events with
  shared-list activity. Alerts can be opened, marked read, or dismissed.
- External notification delivery through Apprise is not included yet. It remains the next
  planned integration slice rather than an advertised capability of this release.

## Interface and packaging

- Settings now follows a compact adaptive layout inspired by desktop preference panels: a
  vertical section rail at normal widths becomes horizontal tabs on smaller windows.
  Controls and copy are denser, while long sections scroll inside the stable dialog frame.
- The General settings page fits a standard 1280 × 720 viewport without scrolling and
  retains usable responsive layouts down to narrow phone-sized browser access.
- French coverage includes the new episode, list, notification, and Settings controls.
  Simplified Chinese remains explicitly marked beta.
- Linux packages now refuse root/sudo desktop installation, verify that extracted files
  belong to one PMT version, stage replacements safely, and restore the previous install
  if replacement fails.

## PMT Server Beta

The server package remains beta and separate from the normal desktop application. Existing
multi-user accounts, shared lists, jobs, backups, SQLite, and optional PostgreSQL behavior
remain available for private testing. Keep verified backups and update server and clients
together.

## macOS installation note

Unless the release assets explicitly say they are Developer ID signed and notarized,
macOS may require manual approval in **System Settings → Privacy & Security**. This cannot
be bypassed safely in application code; signing and notarization require Apple credentials.
