# Personal Media Tracker

Your private place to track movies, television, limited series, and anime.

Personal Media Tracker keeps your library on your own device. Add titles, record
ratings and rewatches, keep notes, and explore your viewing habits without creating
an account or sending your personal history to a central service.

## What you can do

- Track movies, TV, limited series, and anime in one library.
- Record ratings, dates, statuses, notes, tags, and rewatches.
- Search with optional metadata providers or add titles manually.
- Import existing lists and safely move a complete library between installations.
- Explore interactive insights about ratings, genres, activity, and viewing patterns.
- Choose light, dark, custom accent, background, and media-artwork themes.
- Use English, or try the work-in-progress French interface.

French support is still being completed. Some generated Insights sentences and
timestamps may remain in English for now.

## Download

Open the [latest release](https://github.com/ASVPATM/personal-media-tracker/releases/latest)
and choose the download for your operating system. Packaged builds include the app and
its Python runtime.

- **macOS:** open the DMG or ZIP and move Personal Media Tracker to Applications.
- **Windows:** extract the ZIP and open `Personal Media Tracker.exe`.
- **Linux:** extract the archive and run `install-linux.sh`, or launch
  `personal-media-tracker` directly. Some distributions may need a system WebView;
  browser mode is also available.

The first-run guide helps you search, import a list, or start with manual entries. A
TMDB token is optional and is only needed for movie and TV metadata search.

## Private by design

Your database stays on your device. There is no Personal Media Tracker account,
telemetry, advertising, or automatic upload of your library. Exports and backups happen
only when you request them. Read the concise [privacy notice](PRIVACY.md) for details.

## Learn more

- [Technical guide](docs/TECHNICAL_GUIDE.md) — source setup, architecture, imports,
  storage locations, backups, security, and developer commands.
- [Migration guide](MIGRATING.md) — move an existing library without losing data.
- [Building desktop releases](BUILDING.md)
- [Support](SUPPORT.md) and [security reporting](SECURITY.md)

Personal Media Tracker is an original project by
[ASVPATM](https://github.com/ASVPATM), released under the [MIT License](LICENSE). The
copyright and license notice must remain with copies or substantial portions.

*Coming next: broader interface-language support and thoughtful improvements to the
personal-ratings system.*
