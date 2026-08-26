# Privacy

Personal Media Tracker is a local-first, single-user application.

- In default local-only mode, your library, ratings, notes, tags, viewing events, import
  history, preferences, and SQLite database are stored on your computer.
- The default product has no Personal Media Tracker account or central server and does
  not upload watch history to the developer.
- Optional shared access is self-hosted and explicit. One owner-chosen host stores the
  canonical database; authenticated browsers send library changes to that host over the
  HTTPS address the owner configures. The project developer does not receive that data.
- Shared access stores an Argon2id password hash and one-way session/CSRF token hashes in
  the host database. The browser receives Secure session cookies. Portable archives scrub
  owner, session, login-throttle, and calendar-feed-token records; application secrets
  remain in the host's local configuration and are not exported.
- Metadata searches and selected-title details may contact TMDB, TVmaze, Jikan, Kitsu,
  and Wikidata as needed. AniList requests occur only when an authorized developer build
  explicitly enables them.
- Poster loading may contact TMDB, TVmaze, Kitsu, Wikimedia Commons, or MyAnimeList
  image/CDN domains.
- **Check for updates** contacts the official GitHub Releases API only when you press it.
- Exports and backups remain wherever you save them. The application does not upload them.
  Server mode makes bounded scheduled local backups while its host process is running.
- The optional list-conversion prompt is only text shown in Settings. The app does not
  send a list to an AI service. If you paste a list into a third-party or local AI model,
  that model's privacy terms apply; remove private notes first when appropriate.
- TMDB credentials use an unencrypted local configuration file with user-only permissions
  by default. The operating-system credential vault is contacted only after an explicit
  vault choice or one-time migration action, and the UI warns that the operating system
  may request authentication.
  Environment overrides remain available for developer installs. Credentials are not
  included in backups or returned to the frontend.
- No telemetry, analytics, advertising SDK, remote crash reporter, or behavioral tracking
  is enabled.

Privacy still depends on the security of the local computer or chosen server host,
operating-system account, HTTPS proxy, owner password, backup destinations, and connected
devices. This document does not claim anonymity or protection from someone who already
has access to those systems or files.
