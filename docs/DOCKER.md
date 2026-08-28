# Docker local preview

This is an account-free preview of the normal local PMT library for people who prefer a
container on Windows, Linux, or macOS. It is not PMT Server, creates no accounts, and is
not yet a replacement for a verified native release.

## Start PMT

Install Docker Desktop, open it, then run from the repository folder:

```bash
docker compose -f compose.local.yaml up --build -d
```

Open `http://127.0.0.1:8000`. The port is deliberately bound to loopback, so another
device cannot reach it. PMT data persists in the `pmt-local-data` Docker volume.

Use these everyday commands from the same folder:

```bash
docker compose -f compose.local.yaml ps
docker compose -f compose.local.yaml logs -f tracker
docker compose -f compose.local.yaml stop
docker compose -f compose.local.yaml start
```

`stop` preserves the library. Do not run `docker compose down --volumes` unless you
intend to delete the Docker library. Keep PMT Everything archives outside Docker.

## Optional Apprise API

PMT's in-app alerts work without Apprise. The sidecar is only for forwarding selected
alerts to services such as ntfy, Discord, Telegram, Slack, or email.

```bash
docker compose -f compose.local.yaml -f compose.apprise.yaml up --build -d
```

1. Open `http://127.0.0.1:8001`.
2. Create an Apprise configuration with the key `pmt` and add the destination URL(s).
3. In PMT, open **Notifications → Delivery settings**.
4. Choose **Add Docker Apprise API**, add a rule, and send a test.

The Apprise manager and its configuration port remain loopback-only. PMT stores only the
internal `/notify/pmt` endpoint as a protected notification secret; it never returns that
URL to the interface. The `pmt-apprise-config` volume keeps the Apprise configuration.

Stop both services with:

```bash
docker compose -f compose.local.yaml -f compose.apprise.yaml stop
```
