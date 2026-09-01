# Support

Personal Media Tracker is community-supported local software.

The v2.6.1 macOS package is the only recommended native build. The Windows and Linux
native packages remain known-broken on real hardware even though their packaging checks
pass in CI; do not rely on them. Windows and Linux users may test local Docker/browser
mode instead. PMT Server is beta and new public server artifacts are paused.

- Use a GitHub issue for reproducible bugs and feature requests.
- Use GitHub's private vulnerability-reporting feature for security problems.
- Do not attach a real database, export, token, log containing personal details, or watch
  history. Reproduce the problem with synthetic titles whenever possible.
- Include the app version, operating system, installation type, expected behavior, and
  exact steps that reproduce the problem.
- For Windows/Linux native failures, include a minimal synthetic-data reproduction and
  redacted launcher logs; never attach a personal database, unredacted crash dump, or
  secret-bearing environment output.

Before opening an issue, check the latest release notes and existing issues. The project
does not provide an availability guarantee or private data-recovery service, so keep
regular local backups using Settings → Data & Backup.
