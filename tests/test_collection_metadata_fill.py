"""Import recovery must be explicit, conservative, resumable and non-destructive."""

import asyncio
import hashlib
import os
import time
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from watchtracker.authorization import LOCAL_USER_ID
from watchtracker.metadata.http import ProviderError
from watchtracker.models import BookRecord, MusicAlbum, ScheduledJob
from watchtracker.services.collection_artwork import CollectionArtworkCache, allowed
from watchtracker.services.collection_metadata import KIND, confident_candidate
from watchtracker.services.jobs import DurableJobRunner


class Catalog:
    def __init__(self, domain):
        self.domain = domain
        self.identifier = str(uuid4()) if domain == "music" else "OL123M"
        self.group = str(uuid4()) if domain == "music" else "OL123W"
        self.creator = "artist" if domain == "music" else "author"
        self.calls = []
        self.hook = None
        self.fail = False
        self.results = None

    async def search(self, title, creator, **kwargs):
        self.calls.append((title, creator))
        if self.fail:
            raise ProviderError("Fixture", "Offline", retryable=True)
        self.data = {
            "title": title,
            self.creator: creator,
            "provider_id": self.identifier,
            "release_group_id" if self.domain == "music" else "work_id": self.group,
        }
        return {"results": self.results if self.results is not None else [self.data]}

    async def detail(self, identifier):
        if self.hook:
            self.hook()
        return {
            **self.data,
            "year": 1992,
            "genres": ["Pop"],
            "artwork_url": "https://covers.openlibrary.org/b/id/123-L.jpg",
            **(
                {"tracks": [{"position": 1, "title": "Track one"}]}
                if self.domain == "music"
                else {"page_count": 300, "publisher": "Fixture press"}
            ),
        }


def setup_fill(client, domain):
    client.portal.call(client.app.state.job_runner.close)
    service = client.app.state.collection_metadata
    provider = Catalog(domain)
    service.providers[domain] = provider
    runner = DurableJobRunner(client.app.state.durable_jobs, {KIND: service.execute})
    return service, provider, runner


def create(client, domain, **extra):
    creator = "artist" if domain == "music" else "author"
    path = "albums" if domain == "music" else "entries"
    data = {
        "title": "A Synthetic Collection",
        creator: "Fixture Creator",
        "rating": 8.2,
        "notes": "Keep me",
        "status": "collected",
        "tags": ["Mine"],
        **extra,
    }
    response = client.post(f"/api/{domain}/{path}", json=data)
    assert response.status_code == 201, response.text
    return response.json(), f"/api/{domain}/{path}"


@pytest.mark.parametrize("domain", ["music", "books"])
def test_opt_in_import_and_existing_library_fill_preserve_personal_fields(client, domain):
    service, provider, runner = setup_fill(client, domain)
    document = {
        "format": f"pmt-{'music' if domain == 'music' else 'book'}-collection",
        "version": 1,
        "albums" if domain == "music" else "books": [
            {
                "id": str(uuid4()),
                "title": "A Synthetic Collection",
                provider.creator: "Fixture Creator",
                "status": "collected",
                "rating": 8.2,
                "notes": "Keep me",
                "tags": ["Mine"],
            }
        ],
    }
    preview = client.post(f"/api/{domain}/import/preview", json={"document": document}).json()
    body = {"document": document, "sha256": preview["sha256"]}
    assert "metadata" not in client.post(f"/api/{domain}/import", json=body).json()
    assert provider.calls == []
    # Re-importing with fill enabled repairs the existing entry, not a copy.
    response = client.post(f"/api/{domain}/import", json={**body, "fill_metadata": True})
    assert response.status_code == 200, response.text
    assert response.json()["skipped"] == 1
    assert response.json()["metadata"]["pending"] == 1
    client.portal.call(runner.run_once)
    path = f"/api/{domain}/{'albums' if domain == 'music' else 'entries'}"
    rows = client.get(path).json()["items"]
    assert len(rows) == 1
    row = client.get(f"{path}/{rows[0]['id']}").json()
    assert row["provider_id"] == provider.identifier and row["year"] == 1992
    assert row["rating"] == 8.2 and row["notes"] == "Keep me"
    assert row["status"] == "collected" and row["tags"] == ["Mine"]
    assert row["artwork_url"] and row["genres"] == ["Pop"]
    status = client.get(f"/api/collections/{domain}/metadata-fill").json()
    assert status["pending"] == 0 and status["updated"] == 1
    assert service.status(str(uuid4()), domain)["total"] == 0


@pytest.mark.parametrize("domain", ["music", "books"])
def test_matching_duplicate_create_and_import_are_consistent(client, domain):
    row, path = create(client, domain)
    creator = "artist" if domain == "music" else "author"
    data = {
        "title": "Synthetic Collection",
        creator: "Fixture Creator",
        "year": 1992,
        "provider_id": str(uuid4()) if domain == "music" else "OL99M",
    }
    assert client.post(path, json=data).status_code == 409
    document = {
        "format": f"pmt-{'music' if domain == 'music' else 'book'}-collection",
        "version": 1,
        "albums" if domain == "music" else "books": [
            {"id": str(uuid4()), **data},
            {"id": str(uuid4()), **data},
        ],
    }
    preview = client.post(f"/api/{domain}/import/preview", json={"document": document}).json()
    assert preview["skipped"] == 2
    saved = client.post(
        f"/api/{domain}/import", json={"document": document, "sha256": preview["sha256"]}
    )
    assert saved.status_code == 200
    assert client.get(path).json()["total"] == 1
    assert client.get(f"{path}/{row['id']}").json()["provider_id"] is None


def test_ambiguous_match_and_wrong_artist_never_auto_link(client):
    _, provider, runner = setup_fill(client, "music")
    row, path = create(client, "music")
    provider.results = [
        {"title": row["title"], "artist": "Wrong artist", "provider_id": str(uuid4())}
    ]
    client.post("/api/collections/music/metadata-fill", json={})
    client.portal.call(runner.run_once)
    assert client.get(f"{path}/{row['id']}").json()["version"] == 1
    status = client.get("/api/collections/music/metadata-fill").json()
    assert status["review_count"] == 1 and status["review"][0]["reason"] == "review"
    exact = [
        {
            "title": row["title"],
            "artist": row["artist"],
            "release_group_id": str(uuid4()),
            "provider_id": str(uuid4()),
        }
        for _ in range(2)
    ]
    assert confident_candidate(row, exact, "music") is None


def test_retry_review_skips_already_matched_entries_and_review_is_not_truncated(client):
    service, _, _ = setup_fill(client, "music")
    matched, _ = create(client, "music", title="Matched album", provider_id=str(uuid4()))
    unresolved, _ = create(client, "music", title="Unresolved album")
    run = str(uuid4())
    with client.app.state.session_factory() as session:
        for index in range(102):
            entry = matched if index == 0 else unresolved
            session.add(
                ScheduledJob(
                    kind=KIND,
                    user_id=LOCAL_USER_ID,
                    scope_type="music",
                    scope_id=run,
                    state="completed",
                    idempotency_key=f"fixture:{index}",
                    payload={
                        "entry_id": entry["id"],
                        "title": entry["title"],
                        "outcome": "updated" if index == 0 else "review",
                    },
                )
            )
        session.commit()
    limited = client.get("/api/collections/music/metadata-fill").json()
    assert limited["review_count"] == 101 and len(limited["review"]) == 100
    assert limited["review_has_more"]
    all_rows = client.get("/api/collections/music/metadata-fill?review_offset=100").json()
    assert len(all_rows["review"]) == 1 and not all_rows["review_has_more"]
    retried = client.post(
        "/api/collections/music/metadata-fill", json={"retry_review": True}
    ).json()
    assert retried["pending"] == 1
    with client.app.state.session_factory() as session:
        job = session.scalar(
            select(ScheduledJob).where(ScheduledJob.scope_id == retried["run_id"])
        )
        assert job.payload["entry_id"] == unresolved["id"]


@pytest.mark.parametrize("action", ["resolve", "delete"])
def test_review_list_reflects_manual_resolution_and_removal(client, action):
    service, provider, runner = setup_fill(client, "music")
    entry, _ = create(client, "music")
    provider.results = []
    client.post("/api/collections/music/metadata-fill", json={})
    asyncio.run(runner.run_once())
    assert service.status(LOCAL_USER_ID, "music")["review_count"] == 1
    with client.app.state.session_factory() as session:
        row = session.get(MusicAlbum, entry["id"])
        if action == "resolve":
            row.provider_id = str(uuid4())
            row.artwork_url = "https://coverartarchive.org/release/fixture/front-500"
        else:
            from watchtracker.models import utcnow

            row.deleted_at = utcnow()
        session.commit()
    assert service.status(LOCAL_USER_ID, "music")["review_count"] == 0


@pytest.mark.parametrize("opt_in", [False, True])
def test_additional_catalog_only_runs_with_explicit_fill_consent(client, opt_in):
    service, provider, runner = setup_fill(client, "music")
    create(client, "music")
    called = []

    async def primary(source):
        called.append("primary")
        return None

    async def additional(source):
        called.append("additional")
        return None

    provider.match_album = primary
    provider.match_album_with_aliases = additional
    response = client.post(
        "/api/collections/music/metadata-fill", json={"use_wikidata": opt_in}
    )
    assert response.status_code == 200
    asyncio.run(runner.run_once())
    assert called == ["additional" if opt_in else "primary"]


@pytest.mark.parametrize("action", ["edit", "cancel", "delete"])
def test_background_fill_cannot_overwrite_edit_delete_or_cancel(client, action):
    service, provider, runner = setup_fill(client, "music")
    row, path = create(client, "music")
    run = client.post("/api/collections/music/metadata-fill", json={}).json()["run_id"]

    def mutate():
        if action == "cancel":
            service.cancel(LOCAL_USER_ID, "music", run)
        else:
            from watchtracker.models import utcnow

            with client.app.state.session_factory() as session:
                changes = (
                    {"version": 2, "notes": "Newer note"}
                    if action == "edit"
                    else {"deleted_at": utcnow()}
                )
                session.execute(
                    update(MusicAlbum).where(MusicAlbum.id == row["id"]).values(**changes)
                )
                session.commit()

    provider.hook = mutate
    client.portal.call(runner.run_once)
    with client.app.state.session_factory() as session:
        saved = session.get(MusicAlbum, row["id"])
        assert saved.provider_id is None
        if action == "edit":
            assert saved.notes == "Newer note"
    assert service.status(LOCAL_USER_ID, "music")["pending"] == 0


def test_durable_progress_reuses_active_run_retries_offline_and_is_scoped(client):
    service, provider, runner = setup_fill(client, "music")
    row, _ = create(client, "music")
    first = client.post("/api/collections/music/metadata-fill", json={}).json()
    second = client.post("/api/collections/music/metadata-fill", json={}).json()
    assert first["run_id"] == second["run_id"] and second["total"] == 1
    provider.fail = True
    client.portal.call(runner.run_once)
    with client.app.state.session_factory() as session:
        job = session.scalar(select(ScheduledJob).where(ScheduledJob.kind == KIND))
        assert job.state == "retry" and job.attempts == 1
    # A new service instance sees persisted progress; no in-memory-only task.
    from watchtracker.services.collection_metadata import CollectionMetadataService

    replacement = CollectionMetadataService(
        client.app.state.session_factory, provider, provider
    )
    assert replacement.status(LOCAL_USER_ID, "music")["pending"] == 1
    foreign = str(uuid4())
    assert replacement.schedule(foreign, "music", [row["id"]])["total"] == 0
    replacement.cancel(foreign, "music", first["run_id"])
    assert replacement.status(LOCAL_USER_ID, "music")["pending"] == 1


def test_already_linked_manual_import_duplicate_is_reported_not_merged(client):
    _, provider, runner = setup_fill(client, "music")
    manual, path = create(client, "music")
    # Simulate a pre-fix duplicate, which new create/import paths now prevent.
    with client.app.state.session_factory() as session:
        session.add(
            MusicAlbum(
                user_id=LOCAL_USER_ID,
                title=manual["title"],
                artist=manual["artist"],
                provider_id=provider.identifier,
                release_group_id=provider.group,
                identity_key="fixture-existing",
                year=1992,
            )
        )
        session.commit()
    client.post("/api/collections/music/metadata-fill", json={"ids": [manual["id"]]})
    client.portal.call(runner.run_once)
    status = client.get("/api/collections/music/metadata-fill").json()
    assert status["review"][0]["reason"] == "duplicate"
    assert client.get(path).json()["total"] == 2  # No automatic destructive merge.


@pytest.mark.parametrize("domain", ["music", "books"])
def test_owned_artwork_revalidates_and_url_does_not_change_for_personal_edits(client, domain):
    row, path = create(
        client, domain, artwork_url="https://covers.openlibrary.org/b/id/123-L.jpg"
    )
    calls = []

    async def get(urls):
        calls.append(urls)
        return b"fixture-jpeg"

    client.app.state.collection_artwork.get = get
    image = client.get(row["cover_url"])
    assert image.status_code == 200 and image.headers["cache-control"] == "private, no-cache"
    assert (
        client.get(
            row["cover_url"], headers={"if-none-match": image.headers["etag"]}
        ).status_code
        == 304
    )
    assert len(calls) == 2  # Disk cache is checked before replying 304.
    model = MusicAlbum if domain == "music" else BookRecord
    with client.app.state.session_factory() as session:
        session.execute(update(model).where(model.id == row["id"]).values(rating=9, version=2))
        session.commit()
    assert client.get(f"{path}/{row['id']}").json()["cover_url"] == row["cover_url"]
    assert client.get(path).headers["cache-control"].startswith("no-store")


@pytest.mark.asyncio
async def test_artwork_cache_coalesces_and_survives_restart_without_provider_fetch(
    tmp_path, monkeypatch
):
    cache = CollectionArtworkCache(tmp_path)
    calls = []

    async def download(url):
        calls.append(url)
        await asyncio.sleep(0)
        return b"normalized-jpeg"

    monkeypatch.setattr(cache, "download", download)
    url = "https://covers.openlibrary.org/b/id/123-L.jpg"
    assert await asyncio.gather(cache.get([url]), cache.get([url])) == [b"normalized-jpeg"] * 2
    assert len(calls) == 1
    fresh = CollectionArtworkCache(tmp_path)
    assert await fresh.get([url]) == b"normalized-jpeg"
    for bad in [
        "http://covers.openlibrary.org/x",
        "https://127.0.0.1/",
        "https://covers.openlibrary.org@evil.test/",
        "https://evil.archive.org.test/image",
        "https://covers.openlibrary.org:9999/image",
    ]:
        assert not allowed(bad)
        assert await fresh.get([bad]) is None
    await cache.close()
    await fresh.close()


@pytest.mark.asyncio
async def test_cached_fallback_does_not_wait_for_dead_primary(tmp_path, monkeypatch):
    cache = CollectionArtworkCache(tmp_path)
    fallback = "https://covers.openlibrary.org/b/id/123-M.jpg"
    path = cache.directory / f"{hashlib.sha256(fallback.encode()).hexdigest()}.jpg"
    cache.store(path, b"cached-cover")

    async def download(url):
        pytest.fail("A cached alternative must be used before any upstream lookup")

    monkeypatch.setattr(cache, "download", download)
    assert (
        await cache.get(["https://covers.openlibrary.org/b/id/999-L.jpg", fallback])
        == b"cached-cover"
    )
    # Hot page traversal uses bounded memory rather than another disk read.
    monkeypatch.setattr(cache, "read_cached", lambda *_: pytest.fail("Memory hit expected"))
    assert await cache.get([fallback]) == b"cached-cover"
    await cache.close()


@pytest.mark.asyncio
async def test_stale_artwork_is_visible_during_one_background_refresh(tmp_path, monkeypatch):
    cache = CollectionArtworkCache(tmp_path)
    url = "https://coverartarchive.org/release/fixture/front-500"
    path = cache.directory / f"{hashlib.sha256(url.encode()).hexdigest()}.jpg"
    cache.store(path, b"old-cover")
    stamp = time.time() - 8 * 86400
    os.utime(path, (stamp, stamp))
    started, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def download(url):
        calls.append(url)
        started.set()
        await release.wait()
        return b"new-cover"

    monkeypatch.setattr(cache, "download", download)
    assert await asyncio.wait_for(cache.get([url]), 1) == b"old-cover"
    await started.wait()
    assert await asyncio.wait_for(cache.get([url]), 1) == b"old-cover"
    assert len(calls) == 1
    tasks = list(cache.pending.values())
    release.set()
    await asyncio.gather(*tasks)
    assert await cache.get([url]) == b"new-cover"
    await cache.close()
