# Release checklist

Use this checklist from a clean clone. A tag triggers public artifact publication, so do
not create or push a version tag until every required item is complete.

## Repository

- [ ] Confirm `git status` is clean and the release commit is on `main`.
- [ ] Confirm no database, `.env`, secret, cache, log, personal export, or generated build
      artifact is tracked.
- [ ] Review dependency and GitHub Action updates; keep actions pinned to full commit SHAs.
- [ ] Confirm the version in `src/watchtracker/__init__.py` and `CHANGELOG.md` match.
- [ ] Confirm provider policies and attribution are still current.

## Verification

- [ ] Run `uv sync --locked --extra dev --extra browser --extra desktop --extra packaging`.
- [ ] Run `uv run ruff check .` and `uv run ruff format --check .`.
- [ ] Run `uv run pytest` including browser E2E.
- [ ] Run `uv run python scripts/benchmark_local.py`.
- [ ] Run `uv run pip-audit --skip-editable`.
- [ ] Run `uv build` and inspect the wheel/source-distribution contents.
- [ ] Build and smoke-test each desktop target through the release workflow.

## GitHub settings

- [ ] Enable private vulnerability reporting and branch protection for `main`.
- [ ] Require CI checks and block force-pushes/deletion on `main`; require an outside review
      when another maintainer is available.
- [ ] Restrict workflow permissions to read by default; approve write access only where
      the release job requires it.
- [ ] Configure signing/notarization secrets if signed builds are being advertised.
- [ ] Add repository description, topics, license detection, and social preview.

## Publish

- [ ] Create and push the matching `vX.Y.Z` tag only after all checks pass.
- [ ] Verify SHA-256 checksums and smoke-test each downloaded release artifact.
- [ ] Confirm release notes describe unsigned artifacts honestly when signing is absent.
- [ ] Confirm a clean first run, backup, export-everything, and restore on one target OS.
