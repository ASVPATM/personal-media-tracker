# Building desktop releases

PMT Server Beta publication is paused by default. When maintainers deliberately set the
`PMT_SERVER_RELEASES_ENABLED` repository variable to `true`, the tagged workflow also
publishes the same source/version as `ghcr.io/asvpatm/personal-media-tracker-server`, with
`linux/amd64` and `linux/arm64` manifests, provenance, and an SBOM. The image runs the
explicit headless `server` command; it does not contain PMT Flow, tests, local databases,
environment files, screenshots, or developer handoffs because `.dockerignore` excludes
them from the build context.

With that same explicit variable enabled, the workflow builds
`PMT-Server-Setup-Beta-vX.Y.Z.zip`. It contains only the two Compose files, public example
environment file, guided installer, lifecycle helper, and Mac double-click launcher. It
pulls the matching public server image; it does not package PMT Flow, a database,
credentials, or synthetic preview content. Server containers use the explicit
`vX.Y.Z-beta` and moving `beta` tags; they do not use the stable-looking `latest` tag.

To validate the headless artifact locally when Docker is installed:

```bash
docker build -t pmt-server:test .
cp server.env.example server.env
# Replace every placeholder before starting Compose.
PMT_DOMAIN=tracker.example.com docker compose config
```

To exercise PostgreSQL locally, add `-f compose.postgres.yaml`. The server image and
Compose service intentionally use compatible PostgreSQL 15 client/server tools so
custom-format disaster snapshots can be verified and restored.

Install all local build dependencies:

```bash
uv sync --extra dev --extra desktop --extra packaging
uv run python scripts/build_icons.py
uv run pyinstaller packaging/watchtracker.spec --noconfirm --clean
```

Run the repeatable local performance fixture before a release:

```bash
uv run python scripts/benchmark_local.py
```

It creates disposable 300-entry and 3,000-entry libraries with substantial synthetic
viewing history, then measures first-page, filtered-page, and complete Insights service
work. It fails when the deliberately generous consumer-hardware thresholds are exceeded.

The spec collects frontend assets, Alembic migrations, and package metadata explicitly;
the packaged process writes runtime state only to platform user directories.

GitHub Actions builds each operating system on its native runner. macOS produces an app
bundle and compressed archive, Windows produces an application directory archive, and
Linux produces a self-contained directory archive with a `.desktop` file and per-user
installer. The release workflow publishes SHA-256 checksums after tests and smoke checks
pass. The macOS disk image includes an Applications shortcut for drag-to-install.
Windows version resources and macOS bundle versions are both derived from
`src/watchtracker/__init__.py`, which is the single application-version source.

Each packaged executable must pass its own `--smoke-test` before archiving. This starts
the bundled server against a clean temporary data directory, waits for `/health`, then
shuts down. The workflow also checks that the build directory did not receive a runtime
database. On Linux, users can run the extracted executable in place or run
`install-linux.sh`; the latter copies the bundle beneath `XDG_DATA_HOME` and creates a
desktop entry containing absolute executable and icon paths.

Signing/notarization hooks activate only when the documented repository secrets are
present. Unsigned artifacts remain buildable and are labeled honestly. macOS requires an
Apple Developer ID certificate and notarization credentials; Windows requires a trusted
code-signing certificate. No workflow claims a signature when credentials are absent.
An unsigned or ad-hoc macOS build also disables **Download in App** because Gatekeeper
would reject the replacement; it keeps the release-page/manual installation path. There
is no supported code-level bypass for Gatekeeper. A Developer ID-signed and notarized
running bundle is required before PMT offers in-app replacement on macOS.

The release workflow recognizes these optional repository secrets:

- `MACOS_CERTIFICATE_P12`, `MACOS_CERTIFICATE_PASSWORD`, and `MACOS_SIGN_IDENTITY`
- `MACOS_NOTARY_APPLE_ID`, `MACOS_NOTARY_PASSWORD`, and `MACOS_NOTARY_TEAM_ID`
- `WINDOWS_CERTIFICATE_PFX` and `WINDOWS_CERTIFICATE_PASSWORD`

Certificate values are base64-encoded PKCS#12/PFX files. They are materialized only in
the hosted runner's temporary directory. The project never stores signing credentials,
TMDb credentials, user databases, or generated release archives in source control.
