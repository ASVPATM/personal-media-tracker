# Security policy

## Supported deployment

The supported default is one user running one local process bound to loopback. The API
has no login because it is not designed to be exposed to a LAN or the Internet. Using a
non-loopback host override changes that security model and is at the operator's risk.

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub's **Security → Report a
vulnerability** feature for this repository. Do not include real watch history,
credentials, databases, or other personal data in a report. Maintainers should
acknowledge a complete report within seven days and coordinate disclosure after a fix is
available.

## Release support

Security fixes target the latest stable release. The project does not collect telemetry,
so users should check GitHub Releases manually from the About panel or repository.
