# PMT Server Beta and shared access

> **Beta:** PMT Server is optional preview software. Keep verified backups, expect its
> account/sync setup to keep evolving, and update to the newest matching server beta.
> The account-free local desktop application remains the recommended default.

> **Release hold:** new public PMT Server setup bundles and container tags are disabled
> while orders 13–19 undergo private stability testing. These instructions document the
> source/private preview and do not make older beta artifacts production-ready.

Shared access is optional. In the default **local-only** mode, Personal Media Tracker
still binds only to loopback, needs no account, and behaves like the desktop release.
Server mode means one always-on headless PMT Server owns one database and authenticated
people use private accounts from browsers or compatible PMT clients. It never synchronizes
a live SQLite file between computers. The desktop application and PMT Server are release
artifacts from the same source, version, API contract, and migration history.

The first server release remains invite-only. There are only two visible account types:
one **server account** and **regular users**. The server account completes one-time setup,
creates short-lived invitations, can disable sign-in, and can issue recovery links. It is
a management identity, not a personal media profile, and the
server console does not expose an ordinary route for reading another person's ratings,
history, rankings, or notes. The person who runs the server should create a separate
invited regular user account for use on their everyday devices. Backend role names remain
an implementation detail and do not introduce a third account type.

## Easiest setup: PMT Server Setup Beta ZIP

This is the recommended path for a non-technical home install. You need:

- one Mac, Windows, Linux, or NAS computer that can stay on when the library is needed;
- [Docker Desktop](https://docs.docker.com/desktop/) (or Docker Engine with Compose) open
  and running;
- Tailscale signed into the same private tailnet as the phones/computers that will use PMT.

Download **PMT Server Setup Beta** from the same GitHub release as the desktop app and unzip it.
On a Mac, double-click `packaging/Install PMT Server Beta.command`. On Linux, open a terminal in
the unzipped folder and run:

```bash
./scripts/install-pmt-server.sh
```

The installer does the technical preparation for you: it checks Docker, finds your
Tailscale HTTPS name when available, generates unique secrets, offers a database choice,
starts the correct containers, configures private Tailscale Serve, and opens the setup
page. Choose **SQLite** unless you already know you need PostgreSQL. The installer will
not replace an existing `server.env`; rerunning it offers to start that server instead.

In the page that opens, paste the one-time setup code printed by the installer and create
the single server account. Then remove that one-time code with:

```bash
./scripts/pmt-server-control.sh finish-setup
```

Invite regular users from **Server console → People and invitations**. Each user has a private
library. A list becomes collaborative only when its owner shares it with an exact PMT
username as a viewer or editor.

### Metadata tokens for regular users

Keyless providers remain available to every regular user. In **Settings → Metadata**, each
regular user can add an individual TMDb token; this is the recommended default because it
keeps request quotas separate. The server account can optionally save one shared TMDb token
from its own Metadata page. A regular user must explicitly enable the server-token fallback,
and PMT uses it only when that user has no individual token. Tokens are stored separately,
never returned by the API, and excluded from exports and recovery archives.

### Everyday controls

Run these from the unzipped PMT Server Setup folder:

```bash
./scripts/pmt-server-control.sh status
./scripts/pmt-server-control.sh start
./scripts/pmt-server-control.sh stop
./scripts/pmt-server-control.sh backup
./scripts/pmt-server-control.sh logs
```

If the server-account password is forgotten, recover it only from the server device:

```bash
./scripts/pmt-server-control.sh recover-server-account
```

This local command is the security proof: it requires access to the private setup folder,
Docker installation, and server environment on the host. It prompts twice for a new
password and revokes the server account's existing sessions without changing any regular
user or media data. PMT does not use security questions, whose answers are commonly
guessable, and it does not imply email recovery unless an email service is actually
configured and verified.

Keep this folder: it contains the private `server.env` needed to control the installation.
Do not upload that file or paste it into an issue. The actual database is in a Docker
volume, not in the setup folder. Stopping keeps all data; deleting Docker volumes does not.

### Which database?

| Choice | Use it when | Operational rule |
| --- | --- | --- |
| SQLite (recommended) | A person or normal household uses one PMT Server process. | Simplest recovery and fewest moving parts. Never put its live volume on a network/cloud-synced filesystem. |
| PostgreSQL (beta) | A larger installation needs a separate worker or has an existing PostgreSQL operating practice. | Requires both Compose files and `pg_dump`/`pg_restore` recovery drills. The database port stays private. |

The two choices expose the same PMT API and can be used by the same desktop/mobile client
design. PostgreSQL is not needed merely because several people have accounts.

## Private access with Tailscale Serve

Tailscale is not an application dependency and Personal Media Tracker never changes a
Tailscale account. Tailscale Serve stays private to the devices and users allowed by your
tailnet; do not use Tailscale Funnel for this setup. The devices do not need to remain on
the same Wi-Fi network, but they must be signed in to the same tailnet and permitted by
its access controls.

PMT presents two deliberately separate Tailscale choices in **Access & Devices**:

- **Personal Tailscale access** shares the one account-free local library while its desktop
  app is open. PMT prepares a private Serve route and shows the link; another allowed
  tailnet device can open it without a PMT username or password. That convenience means
  the link grants full view/edit access to the library. It never creates a server, users,
  shared lists, or a public Funnel route.
- **PMT Server Beta** is the standalone multi-user service described by the rest of this
  guide. It always requires server-issued invitations and PMT account authentication in
  addition to Tailscale reachability.

### Short Mac and iPhone test

Use the separate **PMT Server Setup** package so the existing desktop library remains an
independent local client:

1. Confirm Tailscale says **Connected** on the Mac and iPhone.
2. On the Mac, run the guided PMT Server installer. It locates the Tailscale command,
   starts the dedicated server, enables private Serve routing, and prints the exact
   `https://device.tailnet.ts.net` address. The first run may open a Tailscale consent page
   to enable HTTPS certificates.
3. Open that address on the Mac, use the one-time setup code to create the server
   account, then run `./scripts/pmt-server-control.sh finish-setup` from the setup folder.
4. In the bare server console, create a regular-user invitation. Sign out of the server
   account and use the invitation to create your everyday regular user account.
5. On the iPhone, open the same HTTPS address in Safari and sign in as that user. Add or
   edit a harmless tag, refresh the Mac browser while signed in as the same user, confirm
   the change, then remove it.

Running `tailscale serve --bg http://127.0.0.1:8000` configures only the private HTTPS
route; it does not start PMT Server and does not convert a desktop app or local preview
into one. The route is ready only while the dedicated PMT Server is answering on port
8000. If `curl http://127.0.0.1:8000/health` cannot connect, start the server package
before using **Verify server** in a PMT client.

Tailscale Serve resumes after Tailscale or the Mac restarts, while PMT itself resumes only
when its dedicated container or service is running. To stop only PMT while retaining all
data, run `./scripts/pmt-server-control.sh stop`. To remove this Mac's Serve route as well,
run the commands below. Do not reset Serve if the Mac intentionally hosts another route.

The normal packaged desktop application is a personal client, not the server console. In
**Settings → Access & Devices**, connect it to the standalone server once; its revocable
device tokens stay in the operating-system credential vault. On later launches the app
uses that token to create a two-minute, one-use browser handoff and opens the saved account
without asking for the password again. The handoff travels only in a URL fragment, is
consumed immediately, and cannot be replayed. If the server or Tailscale is unavailable,
PMT opens the separate local library instead. Turning the connection switch off returns
that application to its local library while preserving the saved device session for an
easy reconnect. **Forget** removes only that device's token/cache/queue. Neither action
deletes the server account, server library, shared lists, or backups. A normal browser
still requires a username and password.

Turning off Tailscale makes the standalone server temporarily unreachable from remote
devices, but it does not stop the server process or delete data. Conversely, stopping the
server leaves every account and library stored in its database until the service starts
again. A single-person installation uses this same design with only one regular account;
there is no less-secure desktop-host shortcut.

A blank or white browser page is not a successful readiness result. It normally means one
of the two required processes is unavailable: PMT is not answering on local port 8000, or
Tailscale is disconnected/not forwarding that port. From the unzipped setup folder run:

```bash
./scripts/pmt-server-control.sh status
./scripts/pmt-server-control.sh logs
```

`status` now reports both local PMT health and the active Tailscale Serve route. Do not test
the iPhone until it says `Local PMT health: ready` and Serve shows the same HTTPS hostname.
Keep the host awake and keep Tailscale connected on both devices. The installer also waits
for these checks before it opens the setup page, so a first load cannot race server startup.

```bash
PMT_TAILSCALE="/Applications/Tailscale.app/Contents/MacOS/Tailscale"
"$PMT_TAILSCALE" serve reset
"$PMT_TAILSCALE" serve status
```

PMT Server still requires its own server-account and regular-user passwords. Tailscale
membership is defense in depth, not a replacement for server authentication. (Only the
separate one-person Personal Tailscale option is intentionally account-free.) Release checks and scheduled backups
stop whenever the host process is off, asleep, or disconnected.

## Native Linux headless service

Install from source in your user environment and copy
`packaging/personal-media-tracker.service` to `~/.config/systemd/user/`. Put the server
configuration at `~/.config/personal-media-tracker/server.env` with permissions `0600`:

```dotenv
WATCHTRACKER_ACCESS_MODE=server
WATCHTRACKER_HOST=127.0.0.1
WATCHTRACKER_PORT=8000
WATCHTRACKER_PUBLIC_BASE_URL=https://your-device.your-tailnet.ts.net
WATCHTRACKER_APPLICATION_SECRET=GENERATE_A_RANDOM_URL_SAFE_VALUE_OF_AT_LEAST_64_CHARACTERS
WATCHTRACKER_SERVER_BOOTSTRAP_TOKEN=GENERATE_A_DIFFERENT_RANDOM_ONE_TIME_VALUE
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
```

Open the configured HTTPS address and use the bootstrap token once to create the single
server account. The database permanently locks bootstrap after that account exists; remove
the bootstrap token from the environment file and restart. Then run
`personal-media-tracker server-readiness`. The command never prints secrets, password
hashes, library counts, titles, or notes.

## Docker Compose with an advanced public reverse proxy

The included Compose example keeps the application on a private, fixed container network,
runs it as a non-root user, stores data in a named volume, and lets Caddy terminate HTTPS.
This is the advanced public/VPS path: configure DNS, firewall rules, OS updates, and host
backups before exposing it.

Copy `server.env.example` to ignored `server.env`, generate two independent random values,
and configure the public HTTPS origin:

```dotenv
WATCHTRACKER_ACCESS_MODE=server
WATCHTRACKER_PUBLIC_BASE_URL=https://tracker.example.com
WATCHTRACKER_APPLICATION_SECRET=YOUR_RANDOM_64_PLUS_CHARACTER_VALUE
WATCHTRACKER_SERVER_BOOTSTRAP_TOKEN=A_DIFFERENT_RANDOM_ONE_TIME_VALUE
WATCHTRACKER_TRUSTED_HOSTS=tracker.example.com
WATCHTRACKER_TRUSTED_PROXY_IPS=172.30.0.3
```

```bash
chmod 600 server.env
PMT_DOMAIN=tracker.example.com docker compose --profile public-domain up -d
```

Open the HTTPS address, complete the one-time server-account setup, remove
`WATCHTRACKER_SERVER_BOOTSTRAP_TOKEN` from `server.env`, and restart only the tracker:

```bash
PMT_DOMAIN=tracker.example.com docker compose --profile public-domain up -d --force-recreate tracker
```

For this public-domain profile, firewall the loopback tracker port and expose only Caddy's
80/443 ports. The Compose network uses `172.30.0.3` as the trusted Caddy proxy; change both
the network and setting together if that address conflicts with your environment.

For PostgreSQL, add `-f compose.postgres.yaml` to the same commands and add the four
PostgreSQL values shown in `server.env.example`. The database has no host-published port.

## Backups, restoration, and moving the owner host

Server mode schedules a checked disaster-recovery snapshot when one is due, then every 24
hours while running, retaining the newest 14 server archives by default. SQLite snapshots
are restored and integrity-checked in an isolated temporary database. PostgreSQL snapshots
are custom-format dumps whose catalog is verified with `pg_restore`; recovery restores
into an explicitly selected empty database. Override with
`WATCHTRACKER_SERVER_BACKUP_INTERVAL_HOURS` and
`WATCHTRACKER_SERVER_BACKUP_RETENTION`. A write/disk failure preserves the live database,
records a safe failure status, logs only the exception type, and retries with bounded
backoff. Copy backup archives to separate protected storage using your own host backup
tool.

Server recovery archives retain account/password hashes so people can sign in after a
disaster, but remove live browser/device sessions, invitation and recovery tokens, login
throttles, calendar-feed tokens, provider tokens, and the application secret. Portable
user exports remain separate and never contain authentication state. To move hosts:

1. Create and download an Everything archive on the current host.
2. Stop the current server. Do not run two hosts against copies of the same active
   library.
3. Put the archive in the future host's PMT backups directory and run
   `personal-media-tracker verify-backup ARCHIVE.zip`.
4. Restore while PMT Server is stopped, configure a new application secret/HTTPS origin,
   and start the server. PostgreSQL recovery uses the documented explicit target database;
   never restore over the running source database. Only after verification should clients
   switch to the new URL.

To recover, stop the process, keep an untouched copy of the failed data directory, and use
the standalone server package's verified restore workflow. A multi-user server is never
converted into one desktop local library: those ownership boundaries are intentionally
preserved. A desktop client can disconnect without changing the server database.

## Security and operating limits

- Server startup fails unless the public URL is HTTPS, the secret is strong, hosts are
  exact (no wildcard), proxy IPs are explicit, and either a server account exists or a
  one-time bootstrap token is configured.
- Sessions are opaque, expiring, revocable, Secure/HttpOnly/SameSite cookies. Every
  authenticated mutation also requires a per-session CSRF token. Login failures receive
  generic errors and bounded backoff.
- Calendar subscription URLs are optional bearer secrets containing only titles and air
  dates. Create them only for a trusted calendar client and revoke them from Access &
  Devices when no longer needed.
- Health/readiness endpoints reveal only process/database readiness. API data, exports,
  backups, and settings require authentication.
- One application process owns SQLite on local storage. Do not use a separate worker and
  do not place the live database on Dropbox, iCloud, Syncthing, NFS, or SMB. SQLite WAL
  does not make network-file access safe.
- PostgreSQL 15 is an optional beta profile selected through
  `WATCHTRACKER_DATABASE_URL_OVERRIDE`; it can use the separate
  `personal-media-tracker worker` command. Do not add multiple web processes until a
  release explicitly documents that topology.
- Native clients use short-lived bearer tokens plus rotating refresh tokens stored in the
  operating system credential store. Offline writes use idempotent request IDs and record
  versions; the server rejects stale mutations instead of silently overwriting them.
- A server-connected profile stores no canonical PMT library in iCloud. A future CloudKit
  library is an alternative authority selected during onboarding, not an automatic mirror.

Primary operational references: [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve),
[Serve command reference](https://tailscale.com/docs/reference/tailscale-cli/serve), and
[Docker volume storage](https://docs.docker.com/engine/storage/volumes/).
