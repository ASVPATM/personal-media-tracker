# ADR 0008: Provider-neutral metadata and a mobile synchronization boundary

Status: accepted for the desktop foundation; CloudKit and native mobile clients remain deferred.

## Context

PMT needs more reliable movie, TV, and anime identification without requiring every user
to create several provider accounts. It should also preserve a credible route to a future
native iOS client and optional iCloud synchronization without delaying normal desktop
releases or turning the current SQLite application into a CloudKit prototype.

## Decision

Metadata access uses a capability registry rather than TMDb-specific application calls.
TVmaze supplies keyless TV discovery, aliases, artwork, and schedules; Jikan and Kitsu
supply independent keyless anime discovery and metadata; optional TMDb remains the
richest movie source and a secondary TV source; Wikidata is a deliberately limited,
keyless movie identity bridge. AniList remains opt-in only where its authorization policy
permits it and is not advertised as an available public setup choice.

Search candidates can be clustered only with strong evidence: a shared external identity,
or exact normalized title/alias plus compatible media type and year. Provider position or
popularity alone never merges records. Detail calls preserve normalized source snapshots,
external identities, and field provenance, while user notes, ratings, tags, history, and
manual artwork overrides remain separate.

The future mobile boundary is the versioned `pmt.platform-sync` logical contract in
`services/sync_contract.py`. It uses existing UUID record IDs and separates user-owned
records from replaceable provider/runtime caches. It explicitly excludes credentials,
raw provider payloads, provider response caches, release schedule caches, integration
runtime state, and private developer-tool state.

## Deferred work

This decision does **not** add CloudKit, Apple entitlements, an Xcode project, an iOS app,
background mobile execution, an Apple developer dependency, or a public sync endpoint.
Before sync ships, PMT still needs deletion tombstones for hard-deleted list records,
per-field conflict rules, account/container ownership decisions, incremental change
tokens, encrypted recovery testing, schema-forward compatibility tests, and a separate
native-client release plan.

Those pieces should be developed behind an adapter boundary after several stable desktop
releases. The SQLite desktop database remains authoritative until an explicit migration
and rollback design is approved.

When native Apple work begins, iCloud/CloudKit synchronization is the primary owner-facing
mobile path. Authenticated Shared Access remains an optional advanced browser bridge and
host-management feature; it is not the synchronization model for the native iOS app and
should become less prominent in the mobile-facing product story.

## Consequences

- Desktop releases remain self-contained and can ship provider reliability improvements
  without Apple tooling.
- A future CloudKit adapter can translate stable logical records rather than copy SQLite
  tables or provider caches.
- Keyless providers improve the default experience, while optional TMDb enriches it.
- Cross-provider disagreements remain visible or require confirmation instead of being
  resolved with unsafe last-write-wins behavior.
- The logical snapshot is an internal tested contract, not a promise that sync is enabled.
