# Privacy

Personal Media Tracker is a local-first, single-user application.

- Your library, ratings, notes, tags, viewing events, import history, preferences, and
  SQLite database are stored on your computer.
- The default product has no Personal Media Tracker account or central server and does
  not upload watch history to the developer.
- Metadata searches and selected-title details contact TMDB and Jikan as needed. AniList
  requests occur only when that optional integration is explicitly enabled.
- Poster loading may contact TMDB, AniList, or MyAnimeList image/CDN domains.
- **Check for updates** contacts the official GitHub Releases API only when you press it.
- Exports and backups remain wherever you save them. The application does not upload them.
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

Local privacy still depends on the security of your computer and operating-system user
account. This document does not claim anonymity or protection from someone who already
has access to your local files.
