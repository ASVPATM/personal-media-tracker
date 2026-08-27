# Security policy

## Supported deployment

The supported default is one user running one local process bound to loopback. Local mode
has no login and now refuses a non-loopback bind.

Optional multi-user server mode is beta and supported only through its fail-closed
configuration: one authoritative PMT Server, local-storage SQLite or the documented
PostgreSQL deployment, an exact HTTPS public URL, strong application secret, exact trusted
hosts and proxy IPs, Argon2id passwords, opaque expiring/revocable sessions, CSRF
validation, and login backoff. Do not expose the application port directly, trust wildcard
hosts/proxies, or synchronize a live SQLite database file. Follow
[the self-hosting guide](docs/SELF_HOSTING.md). Tailscale/network access controls remain
defense in depth and do not replace application login.

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub's **Security → Report a
vulnerability** feature for this repository. Do not include real watch history,
credentials, databases, or other personal data in a report. Maintainers should
acknowledge a complete report within seven days and coordinate disclosure after a fix is
available.

## Release support

Security fixes target the latest recommended desktop release and newest matching PMT
Server Beta. Historical release tags remain available for reproducibility but are not
maintained. The project does not collect telemetry, so users should check GitHub Releases
manually from the About panel or repository.
