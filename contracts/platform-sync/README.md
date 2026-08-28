# PMT platform-sync contract

Version 2 is the portable boundary between PMT implementations. It is a canonical,
user-owned logical snapshot—not SQLite replication, CloudKit transport, or a credential
backup.

Writers sort records by `(record_type, record_id)`. Readers apply dependency order,
retain unknown dates as null, honor tombstones over older records, ledger each outcome,
and safely skip unknown record types. Importing identical canonical bytes twice is a
no-op the second time.

Secrets, OAuth grants, sessions, raw provider responses, caches, notification delivery
state, CloudKit system fields, and private developer tools are excluded. The JSON schema
is `v2.schema.json`; executable examples are in `fixtures/`.
