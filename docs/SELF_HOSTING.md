# Single-owner shared access

Shared access is optional. In the default **local-only** mode, Personal Media Tracker
still binds only to loopback, needs no account, and behaves like the desktop release.
Server mode means one always-on application process owns one database and every Mac or
Linux browser opens that same authenticated HTTPS application. It never synchronizes a
live SQLite file between computers.

## Recommended: local process plus Tailscale Serve

Tailscale is not an application dependency and Personal Media Tracker never changes a
Tailscale account. Install and connect Tailscale yourself, then:

1. In local mode, create an Everything archive and verify that it appears under Settings
   → Data & Backup.
2. Run `tailscale serve 8000` to confirm the private HTTPS name Tailscale assigns. Current
   Tailscale documentation says Serve routes a tailnet-only HTTPS name to a local port and
   that tailnet access controls still apply. Do not use Funnel for this private setup.
3. Open Settings → Access & Devices → Set up shared access. Enter that exact `https://…`
   name, port `8000`, trusted proxies `127.0.0.1,::1`, and a new owner password of at
   least 12 characters. The app checks the port, creates a backup, stores only an
   Argon2id password hash, and writes a strong application secret to the user-only local
   configuration file. Canceling before submission changes nothing.
4. Restart Personal Media Tracker with `personal-media-tracker --no-open`. Keep Tailscale
   Serve running according to the operating method supported by your installed Tailscale
   version. Open the HTTPS name from each authorized Mac or Linux browser and sign in.

The app still requires its own owner password. Tailscale membership is defense in depth,
not a replacement for application authentication. Release checks and scheduled backups
stop whenever the host process is off, asleep, or disconnected.

## Native Linux service

Install from source in your user environment, complete owner setup from Settings or with
`personal-media-tracker setup-owner`, and copy
`packaging/personal-media-tracker.service` to `~/.config/systemd/user/`. Put the server
configuration at `~/.config/personal-media-tracker/server.env` with permissions `0600`:

```dotenv
WATCHTRACKER_ACCESS_MODE=server
WATCHTRACKER_HOST=127.0.0.1
WATCHTRACKER_PORT=8000
WATCHTRACKER_PUBLIC_BASE_URL=https://your-device.your-tailnet.ts.net
WATCHTRACKER_APPLICATION_SECRET=GENERATE_A_RANDOM_URL_SAFE_VALUE_OF_AT_LEAST_64_CHARACTERS
WATCHTRACKER_TRUSTED_HOSTS=your-device.your-tailnet.ts.net
WATCHTRACKER_TRUSTED_PROXY_IPS=127.0.0.1,::1
```

Generate the application secret locally with a cryptographic password/secret generator;
do not reuse the displayed placeholder, commit the file, or paste the secret into an
issue. Then run:

```bash
chmod 600 ~/.config/personal-media-tracker/server.env
systemctl --user daemon-reload
systemctl --user enable --now personal-media-tracker.service
personal-media-tracker server-readiness
```

The readiness command reports only pass/fail categories. It never prints secrets,
password hashes, library counts, titles, or notes.

## Docker Compose with an advanced public reverse proxy

The included Compose example keeps the application on a private, fixed container network,
runs it as a non-root user, stores data in a named volume, and lets Caddy terminate HTTPS.
This is the advanced public/VPS path: configure DNS, firewall rules, OS updates, and host
backups before exposing it.

Create ignored `server.env` with the same fields as above, except:

```dotenv
WATCHTRACKER_ACCESS_MODE=server
WATCHTRACKER_PUBLIC_BASE_URL=https://tracker.example.com
WATCHTRACKER_APPLICATION_SECRET=YOUR_RANDOM_64_PLUS_CHARACTER_VALUE
WATCHTRACKER_TRUSTED_HOSTS=tracker.example.com
WATCHTRACKER_TRUSTED_PROXY_IPS=172.30.0.3
```

Initialize the persistent database and one-time owner interactively before starting
server mode:

```bash
docker compose build
docker compose run --rm -e WATCHTRACKER_ACCESS_MODE=local tracker setup-owner
docker compose run --rm -e WATCHTRACKER_ACCESS_MODE=local tracker backup
PMT_DOMAIN=tracker.example.com docker compose up -d
```

Never publish the tracker container's port directly. Only the HTTPS proxy should be
reachable. The Compose network uses `172.30.0.3` as the one trusted proxy; change both
the network and setting together if that address conflicts with your environment.

## Backups, restoration, and moving the owner host

Server mode creates a checked SQLite backup when it starts if one is due, then every 24
hours while running, retaining the newest 14 scheduled archives by default. Override with
`WATCHTRACKER_SERVER_BACKUP_INTERVAL_HOURS` and
`WATCHTRACKER_SERVER_BACKUP_RETENTION`. A write/disk failure preserves the live database,
records a safe failure status, logs only the exception type, and retries with bounded
backoff. Copy backup archives to separate protected storage using your own host backup
tool.

Portable archives contain every library, rating, assessment, comparison, episode-viewing,
and release record, but remove owner accounts, sessions, login throttles, calendar-feed
tokens, provider tokens, and the application secret. To move hosts:

1. Create and download an Everything archive on the current host.
2. Stop the current server. Do not run two hosts against copies of the same active
   library.
3. Start the future host in local mode, restore the archive, verify title/viewing counts,
   and create a fresh owner password.
4. Run readiness, configure a new HTTPS name and application secret, then start server
   mode. Only after it is verified should clients switch to the new URL.

To recover, stop the process, keep an untouched copy of the failed data directory, and run
`personal-media-tracker restore /path/to/backup.zip` in local mode. Returning to local-only
from Settings retains the library, revokes active sessions, writes loopback configuration,
and takes effect after restart.

## Security and operating limits

- Server startup fails unless the public URL is HTTPS, the secret is strong, hosts are
  exact (no wildcard), proxy IPs are explicit, and an owner exists.
- Sessions are opaque, expiring, revocable, Secure/HttpOnly/SameSite cookies. Every
  authenticated mutation also requires a per-session CSRF token. Login failures receive
  generic errors and bounded backoff.
- Calendar subscription URLs are optional bearer secrets containing only titles and air
  dates. Create them only for a trusted calendar client and revoke them from Access &
  Devices when no longer needed.
- Health/readiness endpoints reveal only process/database readiness. API data, exports,
  backups, and settings require authentication.
- One application process owns SQLite on local storage. Do not use multiple workers and
  do not place the live database on Dropbox, iCloud, Syncthing, NFS, or SMB. SQLite WAL
  does not make network-file access safe.
- The configuration has a database-URL seam, but this release supports and documents
  SQLite only. PostgreSQL and multiple workers remain future work.
- Mobile/PWA installation and offline writes are deliberately not included.

Primary operational references: [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve),
[Tailscale HTTPS](https://tailscale.com/docs/how-to/set-up-https-certificates), and
[Docker volume storage](https://docs.docker.com/engine/storage/volumes/).
