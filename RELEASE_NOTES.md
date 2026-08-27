# Personal Media Tracker v2.5.3

This is the recommended desktop release. Earlier releases remain archived so their tags,
source, and checksums stay reproducible, but fixed versions are not rebuilt under old tags.

## Stability fixes

- The normal desktop app is now clearly a personal local client. The Server console and
  lifecycle controls belong to the separate PMT Server Setup Beta package. A legacy
  server-mode setting left by an older desktop build is ignored safely, so an update
  opens the account-free local library instead of reviving the Owner sign-in screen.
- A server connection is configured once under **Settings → Access & Devices**. Later app
  launches use the securely saved device session to open that account automatically through
  a short-lived, one-use handoff. If the server or Tailscale is unavailable, PMT opens the
  separate local library instead of failing startup.
- Disconnect pauses only this installed client and keeps its saved session. Forget removes
  only the device token, local cache, and queued edits. Stopping PMT Server makes its users
  temporarily unavailable but never deletes accounts, libraries, lists, or backups.
- Access & Devices now includes the regular Tailscale connection guide, a PMT Server mode
  switch that stays disabled until a standalone server is verified, and a secure
  invitation-to-account prompt. The normal local app no longer displays Account or Server
  Console navigation until an enabled server profile actually exists; all server lifecycle
  controls now live only in the standalone console.
- Added a separate **Personal Tailscale access** switch for one-person use. It exposes the
  current account-free local library only to the private tailnet while PMT is open, refuses
  to replace an unrelated Serve route, never enables Funnel, and keeps native-only actions
  unavailable to remote browsers.
- Fixed Personal Tailscale access on current macOS/iOS Serve paths that omit optional
  identity headers. PMT now verifies the exact saved tailnet hostname and accepts only
  loopback or Tailscale-addressed proxy traffic, while ordinary LAN/Internet sources remain
  rejected.
- Fixed Tailscale connection detection in Finder-launched macOS builds. PMT now invokes the
  App Store Tailscale executable in CLI mode, so a connected Mac no longer appears offline
  and incorrectly disables the Personal Tailscale switch.
- On macOS, the red traffic-light now hides the PMT window without stopping the local app;
  selecting PMT in the Dock restores it, while **Quit** still exits normally. New windows
  also start at a larger 1360 × 880 default size.
- Dismissing the Settings privacy reminder now persists in PMT preferences across complete
  application restarts instead of depending on WebKit local storage.
- Local-only applications no longer reveal an Account navigation button from stale or saved
  server-client state. Access & Devices now keeps PMT Server connection controls inside the
  PMT Server mode group and restores the Personal Tailscale address generator under a clearly
  separate Tailscale private connection setup group.
- A forgotten server-account password is recovered from the private server setup folder
  with `./scripts/pmt-server-control.sh recover-server-account`; this host-only action
  replaces guessable security questions and revokes sessions without changing user data.
- Popups no longer cover the native macOS drag surface. The sign-in and host-recovery
  screen now uses a readable landscape layout and remains draggable from the title area.
- Reopening an already-running Mac app now brings its existing native window forward;
  PMT no longer opens a protected `127.0.0.1` server URL in Safari or produces an
  `invalid_host` response during duplicate launches.
- Older Shared Access libraries remain intact when their historical server-owner account
  already owns media; the regular desktop opens those records as its local library without
  transferring records or exposing Server console navigation.
- Fixed packaged macOS startup after Shared Access/server configuration by allowing the
  launcher's loopback health probe without weakening public-host checks.
- Fixed native macOS and Linux exports so CSV, JSON, Markdown, Obsidian, and Everything
  archives use the desktop save dialog instead of replacing the PMT window.
- Fixed regular-user password changes, failed sign-in recovery, invitation forms, account
  switching, shared-list rendering, and visible account feedback.
- Improved Tailscale/server verification so an unavailable port, a local-only PMT app,
  and an incorrectly configured server hostname produce different next steps.
- Fixed rapid appearance changes being saved out of order and restored the large-library
  performance fixture as a required release check.
- Disabled in-app replacement for unsigned or Gatekeeper-unapproved macOS builds. Those
  installations continue to use **Open the Release**.
- Added migration, isolation, backup/restore, browser, packaged-startup, server identity,
  and multi-user regression coverage.

## PMT Server Beta

The normal local desktop application remains account-free and is the recommended default.
The separate **PMT Server Setup Beta** asset is optional and intended for private testing.
It includes multi-user accounts, shared lists, durable jobs, backups, Tailscale-oriented
setup, SQLite, and optional PostgreSQL. Keep verified backups and update the server and
clients together.

## macOS installation note

Unless the release assets explicitly say they are Developer ID signed and notarized,
macOS may require manual approval in **System Settings → Privacy & Security**. This cannot
be safely bypassed in application code; signing and notarization require Apple credentials.
