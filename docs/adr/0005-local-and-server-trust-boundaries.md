# ADR 0005: Explicit local and single-owner-server trust boundaries

Status: Accepted

## Context

The released app is an unauthenticated loopback desktop service protected by host and
same-origin checks. Binding that API to a LAN or public interface would expose private
history, backups, notes, and credentials.

## Decision

Local mode stays the default, loopback-only, account-free mode. Server mode is a separate
explicit configuration and must fail closed unless an owner password, application
secret, trusted hosts/origins, secure session cookies, CSRF protection, HTTPS expectation,
and proxy policy all validate. Bootstrap is one-time; sessions are revocable and
time-bounded. Read, write, import, export, backup, and settings APIs all require a session
in server mode.

No non-loopback listener is enabled or documented until these controls and their tests
land together. Readiness output reports only categories and remediation, never secrets.

## Consequences

Local upgrades remain frictionless. Shared access cannot be partially enabled. Reverse
proxy headers are ignored unless an explicit trusted-proxy configuration authorizes them.
