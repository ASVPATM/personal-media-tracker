# Security policy

## Supported deployment

The supported default is one user running one local process bound to loopback. Local mode
has no login and now refuses a non-loopback bind.

Optional single-owner server mode is supported only through its fail-closed configuration:
one process, local-storage SQLite, an exact HTTPS public URL, strong application secret,
exact trusted hosts and proxy IPs, an Argon2id owner password, opaque expiring/revocable
sessions, CSRF validation, and login backoff. Do not expose the application port directly,
run multiple workers, trust wildcard hosts/proxies, or synchronize the live database file.
Follow [the self-hosting guide](docs/SELF_HOSTING.md). Tailscale/network access controls
remain defense in depth and do not replace application login.

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub's **Security → Report a
vulnerability** feature for this repository. Do not include real watch history,
credentials, databases, or other personal data in a report. Maintainers should
acknowledge a complete report within seven days and coordinate disclosure after a fix is
available.

## Release support

Security fixes target the latest stable release. The project does not collect telemetry,
so users should check GitHub Releases manually from the About panel or repository.
