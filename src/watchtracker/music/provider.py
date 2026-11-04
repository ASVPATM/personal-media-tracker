"""Explicit, keyless album lookup. Never polls or sends private library data."""

from __future__ import annotations

import asyncio
import copy
import re
import time
from collections import OrderedDict
from urllib.parse import urljoin, urlsplit
from uuid import UUID

import httpx

from watchtracker import __version__
from watchtracker.metadata.http import ProviderError
from watchtracker.music.schemas import AlbumInput, MusicTrack
from watchtracker.services.catalog_cache import (
    CatalogDiskCache,
    CatalogLane,
    background_catalog,
    bypass_negative,
    negative_payload,
)


def artist_credit(value: list) -> str:
    return "".join(
        (part.get("name") or part.get("artist", {}).get("name", ""))
        + part.get("joinphrase", "")
        if isinstance(part, dict)
        else str(part)
        for part in value
    )[:500]


def release_year(value: str | None) -> int | None:
    match = re.match(r"^(\d{4})", value or "")
    return int(match[1]) if match and 1000 <= int(match[1]) <= 2200 else None


def release_variant(row: dict) -> tuple[str, ...]:
    """Distinguish named editions without treating an album title as a variant."""
    from watchtracker.metadata.catalog_matching import normalized_title

    title = normalized_title(row.get("title") or "")
    group_title = normalized_title((row.get("release-group") or {}).get("title") or title)
    extra = title.removeprefix(group_title)
    words = normalized_title(extra + " " + str(row.get("disambiguation") or ""))
    return tuple(
        term
        for term in ("deluxe", "expanded", "anniversary", "bonus", "remaster")
        if term in words.replace("remastered", "remaster").split()
    )


def special_pressing(row: dict) -> bool:
    return bool(
        re.search(
            r"\b(test pressing|white label|promo(?:tional)?|advance|sampler|club)\b",
            str(row.get("disambiguation") or ""),
            re.I,
        )
    )


def image_options(data, scope="Selected edition"):
    options = []
    for row in data.get("images", []):
        if not isinstance(row, dict) or row.get("approved") is False:
            continue
        image_id = str(row.get("id", ""))
        image = urlsplit(str(row.get("image", "")))
        match = re.fullmatch(r"/release/([0-9a-fA-F-]{36})/\d+\.[a-zA-Z]+", image.path)
        if (
            image.hostname != "coverartarchive.org"
            or not match
            or not re.fullmatch(r"\d{1,30}", image_id)
        ):
            continue
        try:
            release_id = UUID(match[1])
        except ValueError:
            continue
        types = ", ".join(str(value) for value in row.get("types", []))[:100]
        comment = str(row.get("comment") or "")[:140]
        packaging = bool(
            re.search(
                r"\b(sticker|jewel|case|obi|tray|booklet|liner|medium|spine|cassette|box|shrinkwrap|packaging|test pressing|white label)\b",
                types + " " + comment,
                re.I,
            )
        )
        root = f"https://coverartarchive.org/release/{release_id}/{image_id}"
        options.append(
            {
                "url": root + "-1200.jpg",
                "thumbnail_url": root + "-250.jpg",
                "label": (types or "Artwork") + (" · " + comment if comment else ""),
                "source": "Cover Art Archive",
                "scope": scope,
                "front": bool(row.get("front")),
                "packaging": packaging,
            }
        )
    return sorted(options, key=lambda row: (not row["front"], row["packaging"]))


class PublicCatalogClient:
    api_root = "https://musicbrainz.org/ws/2/"
    provider_name = "MusicBrainz"
    default_params = {"fmt": "json"}

    def __init__(self, client: httpx.AsyncClient | None = None):
        self.client = client or httpx.AsyncClient(timeout=20, follow_redirects=False)
        self.owns_client = client is None
        self.lane = CatalogLane()
        self.disk_cache = None
        self.next_request = 0.0
        self.cache: OrderedDict = OrderedDict()
        self.cache_sizes = {}
        self.cache_bytes = 0

    def configure_cache(self, directory):
        self.disk_cache = CatalogDiskCache(directory)
        for name in ("artwork_client", "alias_client"):
            if child := getattr(self, name, None):
                child.configure_cache(directory)

    def remember(self, key, data, ttl):
        import json

        self.cache[key] = (time.monotonic() + ttl, data)
        self.cache_bytes -= self.cache_sizes.get(key, 0)
        self.cache_sizes[key] = len(json.dumps(data).encode())
        self.cache_bytes += self.cache_sizes[key]
        self.cache.move_to_end(key)
        while len(self.cache) > 256 or self.cache_bytes > 8 * 1024 * 1024:
            removed, _ = self.cache.popitem(last=False)
            self.cache_bytes -= self.cache_sizes.pop(removed, 0)

    async def close(self):
        if self.owns_client:
            await self.client.aclose()

    async def _request(self, path: str, params: dict):
        return await self.client.get(
            self.api_root + path,
            params={**self.default_params, **params},
            headers={
                "User-Agent": f"PersonalMediaTracker/{__version__} (https://github.com/ASVPATM/personal-media-tracker)",
                "Accept": "application/json",
            },
        )

    async def _artwork_get(self, path: str, **params):
        # The chooser does at most three catalog lookups. Bound each including
        # queue/retry waits; an optional artwork failure must not stall editing.
        try:
            async with asyncio.timeout(8):
                return await self._get(path, **params)
        except TimeoutError as exc:
            raise ProviderError(
                self.provider_name, "Artwork lookup timed out", retryable=True
            ) from exc

    async def _search_get(self, path: str, **params):
        # A stale typeahead request must not hold the provider queue for minutes.
        # This deadline includes lock, rate-limit and retry waits, not just I/O.
        try:
            async with asyncio.timeout(12):
                return await self._get(path, **params)
        except TimeoutError as exc:
            raise ProviderError(self.provider_name, "Search timed out", retryable=True) from exc

    async def _get(self, path: str, **params):
        key = (path, tuple(sorted(params.items())))
        # A cached answer must not wait behind an unrelated slow network call.
        cached = self.cache.get(key)
        if (
            cached
            and cached[0] > time.monotonic()
            and not (bypass_negative.get() and negative_payload(cached[1]))
        ):
            self.cache.move_to_end(key)
            self.lane.metrics["memory_hit"] += 1
            return copy.deepcopy(cached[1])
        disk_key = CatalogDiskCache.key(self.api_root, path, {**self.default_params, **params})
        if self.disk_cache:
            item = await asyncio.to_thread(
                self.disk_cache.read, disk_key, retry=bypass_negative.get()
            )
            if item:
                self.remember(key, item["data"], max(0, item["expires"] - time.time()))
                return copy.deepcopy(item["data"])
        self.lane.metrics["cache_miss"] += 1
        async with self.lane.acquire():
            cached = self.cache.get(key)
            if (
                cached
                and cached[0] > time.monotonic()
                and not (bypass_negative.get() and negative_payload(cached[1]))
            ):
                self.cache.move_to_end(key)
                return copy.deepcopy(cached[1])
            for attempt in range(2):
                await asyncio.sleep(max(0, self.next_request - time.monotonic()))
                self.next_request = time.monotonic() + 1.05
                try:
                    started = time.perf_counter()
                    response = await self._request(path, params)
                    self.lane.metrics["request_ms"] += (time.perf_counter() - started) * 1000
                    self.lane.metrics["requests"] += 1
                    self.lane.metrics["bytes"] += len(response.content)
                    if response.status_code in {429, 503} and attempt == 0:
                        try:
                            retry_after = min(
                                60, max(2, float(response.headers.get("Retry-After", "2")))
                            )
                        except ValueError:
                            try:
                                from email.utils import parsedate_to_datetime

                                retry_after = min(
                                    60,
                                    max(
                                        2,
                                        parsedate_to_datetime(
                                            response.headers["Retry-After"]
                                        ).timestamp()
                                        - time.time(),
                                    ),
                                )
                            except (KeyError, TypeError, ValueError, OverflowError):
                                retry_after = 2
                        self.lane.metrics["rate_limits"] += 1
                        self.lane.metrics["retry_after_seconds"] = retry_after
                        self.next_request = time.monotonic() + retry_after
                        if retry_after > 5:
                            break
                        continue
                    response.raise_for_status()
                    if len(response.content) > 4 * 1024 * 1024:
                        raise ValueError("Response too large")
                    data = response.json()
                    if not isinstance(data, dict):
                        raise ValueError("Invalid response")
                    search = (
                        any(name in params for name in ("query", "q", "search"))
                        or "search" in path
                    )
                    ttl = 900 if negative_payload(data) else 86400 if search else 7 * 86400
                    self.remember(key, data, ttl)
                    if self.disk_cache:
                        await asyncio.to_thread(
                            self.disk_cache.write, disk_key, data, search=search
                        )
                    return copy.deepcopy(data)
                except (httpx.HTTPError, ValueError) as exc:
                    # Stale details are display-only. Never make an automatic
                    # identity decision using an expired provider response.
                    if (
                        self.disk_cache
                        and not background_catalog.get()
                        and "/" in path
                        and not params.get("query")
                    ):
                        item = await asyncio.to_thread(
                            self.disk_cache.read, disk_key, stale=True
                        )
                        if item and not item["negative"]:
                            self.lane.metrics["stale_display"] += 1
                            return copy.deepcopy(item["data"])
                    raise ProviderError(
                        self.provider_name, "Catalog lookup failed", retryable=True
                    ) from exc
        error = ProviderError(self.provider_name, "Rate limit reached", retryable=True)
        error.retry_after_seconds = max(1, int(self.next_request - time.monotonic()) + 1)
        raise error


class CoverArtArchiveClient(PublicCatalogClient):
    api_root = "https://coverartarchive.org/"
    provider_name = "Cover Art Archive"
    default_params = {}

    async def _request(self, path: str, params: dict):
        # CAA's documented JSON API redirects to archive.org/index.json.
        # Follow only HTTPS redirects to the two official services, never an
        # arbitrary URL supplied by a catalog response or a local user.
        url = self.api_root + path
        for _ in range(4):
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or parsed.username
                or parsed.password
                or parsed.port not in (None, 443)
                or not parsed.hostname
                or (
                    parsed.hostname not in {"coverartarchive.org", "archive.org"}
                    and not parsed.hostname.endswith(".archive.org")
                )
            ):
                raise ValueError("Unexpected artwork catalog redirect")
            response = await self.client.get(
                url,
                headers={
                    "User-Agent": f"PersonalMediaTracker/{__version__} (https://github.com/ASVPATM/personal-media-tracker)",
                    "Accept": "application/json",
                },
                follow_redirects=False,
                timeout=10,
            )
            if response.status_code == 404:
                return httpx.Response(200, json={"images": []}, request=response.request)
            if response.status_code not in {301, 302, 303, 307, 308}:
                return response
            url = urljoin(url, response.headers.get("Location", ""))
        raise ValueError("Too many artwork catalog redirects")


class MusicBrainzProvider(PublicCatalogClient):
    def __init__(self, client: httpx.AsyncClient | None = None):
        super().__init__(client)
        self.artwork_client = CoverArtArchiveClient(self.client)
        from watchtracker.music.wikidata import WikidataAlbumBridge

        self.alias_client = WikidataAlbumBridge(self.client)

    async def match_album_with_aliases(self, source: dict) -> dict | None:
        if match := await self.match_album(source):
            return match
        bridge = await self.alias_client.find(source)
        if not bridge:
            return None
        group = await self._get(f"release-group/{bridge['id']}", inc="artist-credits+aliases")
        verified = False
        for credit in group.get("artist-credit", []):
            artist = credit.get("artist", {})
            aliases = bridge["artists"].get(artist.get("id"))
            if aliases:
                verified = True
                artist["aliases"] = [
                    *(artist.get("aliases") or []),
                    *({"name": name} for name in aliases),
                ]
        if not verified or group.get("id") != bridge["id"]:
            return None
        group["aliases"] = [
            *(group.get("aliases") or []),
            *({"name": name} for name in bridge["titles"]),
        ]
        from watchtracker.music.matching import choose_group

        if not choose_group(source, [group]):
            return None
        return await self._edition_for_group(source, group)

    async def match_album(self, source: dict) -> dict | None:
        """Bounded album-first recovery, including credited artists and verified aliases.

        A bounded search discovers the group and edition;
        details use the same IDs. No user ratings, notes or listening data leave PMT.
        """
        from watchtracker.music.matching import (
            album_key,
            artist_names,
            artist_strength,
            choose_group,
        )

        def quoted(value):
            return '"' + re.sub(r'([+\-!(){}\[\]^"~*?:\\/|&])', r"\\\1", value) + '"'

        def fuzzy_terms(value):
            # Search expansion only: identity still needs independent validation.
            return " AND ".join(
                word + ("~1" if len(word) >= 4 else "")
                for word in re.findall(r"\w+", value.casefold())[:20]
            )

        title = album_key(source["title"])
        if not title or not artist_strength(source["artist"], [source["artist"]]):
            return None
        raw_title = re.sub(r"\bhertz\b", "Hz", source["title"], flags=re.I).replace("’", "'")
        title_query = f"releasegroup:{quoted(raw_title)} OR releasegroup:{quoted(title)} OR alias:{quoted(raw_title)}"
        expression = (
            f"({title_query}) AND artist:{quoted(source['artist'])} AND status:official"
        )
        data = await self._get("release-group/", query=expression, limit=100)
        groups = data.get("release-groups") or []
        group = choose_group(source, groups)
        if not group:
            # Album-only discovery can recover a misspelled artist without
            # guessing the artist from popularity. Identity is still checked
            # locally against the full credit and aliases.
            data = await self._get(
                "release-group/", query=f"({title_query}) AND status:official", limit=100
            )
            title_groups = data.get("release-groups") or []
            if data.get("count", len(title_groups)) <= 100:
                group = choose_group(source, title_groups)
                # Some albums have a distinct official title and are catalogued
                # as remixes (not 'Album X (remix)'). Only a complete, unique,
                # exact-title set without a competing original qualifies.
                if not group:
                    group = choose_group(source, title_groups, allow_named_remix=True)
        if not group:
            # Artist aliases are catalog evidence, not a hand-maintained table
            # or a guess from the most popular result. Include aliases returned
            # in search so legal names and transliterations can share an MBID.
            name = quoted(source["artist"])
            artists = await self._get(
                "artist/", query=f"artist:{name} OR alias:{name}", limit=25
            )
            verified = [
                row
                for row in artists.get("artists", [])
                if artist_strength(source["artist"], artist_names([row]))
            ]
            if not verified:
                artists = await self._get(
                    "artist/", query=f"artist:({fuzzy_terms(source['artist'])})", limit=25
                )
                verified = [
                    row
                    for row in artists.get("artists", [])
                    if artist_strength(source["artist"], artist_names([row]))
                ]
            if not verified:
                words = re.findall(r"\w+", source["artist"].casefold())
                terms = [quoted(word) for word in words if len(word) >= 4]
                if terms:
                    artists = await self._get(
                        "artist/", query="artist:(" + " OR ".join(terms[:8]) + ")", limit=25
                    )
                    verified = [
                        row
                        for row in artists.get("artists", [])
                        if artist_strength(source["artist"], artist_names([row]))
                    ]
            # Never pick the first of a long list of ambiguous artist names.
            if not verified:
                return None
            strength = max(
                artist_strength(source["artist"], artist_names([row])) for row in verified
            )
            verified = [
                row
                for row in verified
                if artist_strength(source["artist"], artist_names([row])) == strength
            ]
            ids = [str(UUID(row["id"])) for row in verified]
            artist_filter = "(" + " OR ".join(f"arid:{value}" for value in ids) + ")"
            data = await self._get(
                "release-group/",
                query=f"({title_query} OR releasegroup:({fuzzy_terms(title)})) AND {artist_filter} AND status:official",
                limit=100,
            )
            groups = data.get("release-groups") or []

            # Some search responses omit aliases; carry only names verified
            # against the exact artist MBID, never onto unrelated credits.
            def with_aliases(rows):
                for row in rows:
                    for credit in row.get("artist-credit", []):
                        artist = credit.get("artist", {})
                        match = next(
                            (item for item in verified if item["id"] == artist.get("id")), None
                        )
                        if match:
                            artist["aliases"] = match.get("aliases") or []
                return rows

            group = choose_group(source, with_aliases(groups))
            if not group and len(ids) <= 3:
                # One bounded artist-discography lookup also exposes translated
                # album aliases and punctuation variants omitted by text search.
                discography = []
                complete = True
                for artist_id in ids:
                    data = await self._get(
                        "release-group/",
                        artist=artist_id,
                        inc="artist-credits+aliases",
                        type=source.get("release_type")
                        if source.get("release_type") in {"album", "ep", "single"}
                        else "album",
                        limit=100,
                    )
                    complete = complete and data.get("release-group-count", 0) <= 100
                    discography.extend(data.get("release-groups") or [])
                if complete:
                    group = choose_group(source, with_aliases(discography))
        if not group:
            return None
        return await self._edition_for_group(source, group)

    async def _edition_for_group(self, source, group):
        from watchtracker.music.matching import album_key

        group_id = str(UUID(group["id"]))
        editions = await self._get(
            "release/",
            **{
                "release-group": group_id,
                "status": "official",
                "inc": "media+artist-credits",
                "limit": 100,
            },
        )
        requested = album_key(source["title"])
        candidates = []
        for row in editions.get("releases", []):
            if str(row.get("status", "")).lower() != "official":
                continue
            edition = str(row.get("disambiguation") or "").lower()
            # The group proves album identity, not a deluxe edition's identity.
            if any(
                term in edition and term not in requested
                for term in ("deluxe", "expanded", "bonus", "anniversary")
            ):
                continue
            candidates.append(row)
        if not candidates:
            return None
        candidates.sort(
            key=lambda row: (
                album_key(row.get("title")) != requested,
                special_pressing(row),
                not row.get("cover-art-archive", {}).get("front", False),
                not any(medium.get("track-count") for medium in row.get("media", [])),
                bool(re.search(r"\b(promo|club)\b", row.get("disambiguation", ""), re.I)),
                row.get("date") or "9999",
                row["id"],
            )
        )
        return {"provider_id": str(UUID(candidates[0]["id"])), "release_group_id": group_id}

    async def fill_detail(self, identifier: UUID) -> dict:
        # Bulk fill needs a reliable small cover, not the interactive chooser's
        # two extra CAA JSON lookups and 1200px image on every imported album.
        return await self.detail(identifier, artwork_choices=False)

    async def search(self, query: str, artist: str = "") -> dict:
        from watchtracker.metadata.catalog_matching import title_distance

        # Quote user text; never interpret it as a Lucene query/program.
        def escape(text):
            return re.sub(r'([+\-!(){}\[\]^"~*?:\\/|&])', r"\\\1", text)

        expression = f'release:"{escape(query)}"'
        if artist:
            expression += f' AND artist:"{escape(artist)}"'
        data = await self._search_get("release/", query=expression, limit=100)
        strategy = "exact"
        if not data.get("releases"):
            # One bounded fallback: tolerate a partial final word or different
            # word order without broadening to a different catalog/identity.
            words = re.findall(r"\w+", query.casefold())[:20]
            if words and len(words[-1]) >= 3:
                terms = [f'"{escape(word)}"' for word in words[:-1]]
                terms.append(escape(words[-1]) + "*")
                broader = "release:(" + " AND ".join(terms) + ")"
                if artist:
                    broader += f' AND artist:"{escape(artist)}"'
                else:
                    # One search box also accepts an artist plus album (e.g.
                    # "sade deluxe"). Each token must still match one of those
                    # two fields; this is not an unrestricted Lucene query.
                    broader = " AND ".join(
                        f"(release:{term} OR artist:{term})" for term in terms
                    )
                data = await self._search_get("release/", query=broader, limit=100)
                strategy = "broader_terms"
        results = []
        groups, coverage, seen_releases = {}, {}, set()
        for row in data.get("releases", [])[:100]:
            try:
                identifier = str(UUID(row["id"]))
            except (ValueError, KeyError, TypeError):
                continue
            if identifier in seen_releases:
                continue
            seen_releases.add(identifier)
            title = row.get("title", "")[:500]
            name = artist_credit(row.get("artist-credit", []))
            group = row.get("release-group", {})
            country = row.get("country", "")
            # Country, medium and date alone do not make another album. Retain
            # meaningful named versions without a network request per result.
            count = sum(int(medium.get("track-count", 0)) for medium in row.get("media", []))
            formats = ", ".join(
                dict.fromkeys(
                    str(medium["format"])
                    for medium in row.get("media", [])
                    if medium.get("format")
                )
            )
            variant = release_variant(row)
            identity = (group.get("id") or identifier, variant)
            if not title or not name:
                continue
            coverage[identity[0]] = coverage.get(identity[0], 0) + (
                row.get("status") == "Official"
            )
            candidate = {
                "provider_id": identifier,
                "title": title,
                "artist": name,
                "year": release_year(row.get("date")),
                "country": country,
                "track_count": count,
                "edition": " · ".join(
                    filter(
                        None,
                        [
                            row.get("disambiguation", ""),
                            formats,
                            row.get("date", ""),
                            country,
                        ],
                    )
                )[:500],
                "official": row.get("status") == "Official",
                "artwork_url": f"https://coverartarchive.org/release/{identifier}/front-500",
                "release_group_id": group.get("id"),
                "variant": " · ".join(variant),
            }
            try:
                group_id = str(UUID(str(group.get("id"))))
            except ValueError:
                group_id = None
            edition_cover = candidate["artwork_url"]
            group_cover = (
                f"https://coverartarchive.org/release-group/{group_id}/front-500"
                if group_id
                else None
            )
            # CAA's curated release-group image is much more reliable than a
            # random physical edition's front endpoint. Named versions keep
            # their own cover first; the UI tries the bounded fallback on 404.
            candidate["artwork_url"] = (
                edition_cover if variant else group_cover or edition_cover
            )
            candidate["artwork_fallbacks"] = [
                url
                for url in (group_cover, edition_cover)
                if url and url != candidate["artwork_url"]
            ]
            # Choose a useful representative of this group/version. Do not
            # prefer a bootleg, or borrow another release's tracklist/cover.
            quality = (
                not candidate["official"],
                special_pressing(row),
                not bool(count),
                candidate["year"] or 9999,
                bool(
                    re.search(
                        r"\b(club|promo|promotional)\b",
                        str(row.get("disambiguation") or ""),
                        re.I,
                    )
                ),
                "CD" not in formats,
                row.get("date") or "9999",
                identifier,
            )
            old = groups.get(identity)
            if old is None or quality < old[0]:
                groups[identity] = (quality, candidate)
        results = [item[1] for item in groups.values()]
        # Exact title/creator matches lead; never rank an unrelated popular album
        # above the user's query just because its edition has more fields.
        results.sort(
            key=lambda row: (
                min(
                    title_distance(row["title"], query),
                    title_distance(row["artist"] + " " + row["title"], query),
                )
                if not artist
                else title_distance(row["title"], query),
                title_distance(row["artist"], artist) if artist else (0, 0),
                not row["official"],
                # Catalog coverage is only a tie-break after title/creator;
                # it is not a popularity score or evidence of personal taste.
                -coverage.get(row["release_group_id"] or row["provider_id"], 0),
                row["year"] or 9999,
                not bool(row["track_count"]),
            )
        )
        return {"results": results[:24], "source": "MusicBrainz", "search_strategy": strategy}

    async def detail(self, identifier: UUID, *, artwork_choices=True) -> dict:
        data = await self._get(
            f"release/{identifier}",
            inc="recordings+artist-credits+release-groups+genres+labels",
        )
        tracks = []
        artist = artist_credit(data.get("artist-credit", []))
        seen_discs = set()
        for disc_index, medium in enumerate(data.get("media", [])[:100], 1):
            disc = medium.get("position", disc_index)
            if not isinstance(disc, int) or not 1 <= disc <= 100 or disc in seen_discs:
                disc = next(value for value in range(1, 101) if value not in seen_discs)
            seen_discs.add(disc)
            seen_positions = set()
            for index, row in enumerate(medium.get("tracks", []), 1):
                recording = row.get("recording", {})
                position = row.get("position", index)
                if (
                    not isinstance(position, int)
                    or not 1 <= position <= 1000
                    or position in seen_positions
                ):
                    position = next(
                        value for value in range(1, 1001) if value not in seen_positions
                    )
                seen_positions.add(position)
                tracks.append(
                    MusicTrack(
                        disc=disc,
                        position=position,
                        title=row.get("title") or recording.get("title") or f"Track {index}",
                        artist=artist_credit(
                            row.get("artist-credit") or recording.get("artist-credit") or []
                        )
                        or artist,
                        duration_ms=row.get("length") or recording.get("length"),
                        recording_id=recording.get("id"),
                    )
                )
        group = data.get("release-group", {})
        # Search uses the curated group cover for a standard album. Detail and
        # bulk fill must keep that choice instead of replacing it with a photo
        # of whichever cassette/CD happened to supply the tracklist.
        prefer_group_art = bool(group.get("id")) and not release_variant(data)
        kind = str(group.get("primary-type", "album")).lower()
        if "Compilation" in group.get("secondary-types", []):
            kind = "compilation"
        if kind not in {"album", "ep", "single", "compilation"}:
            kind = "other"
        genres = list(
            dict.fromkeys(
                row["name"]
                for row in [*data.get("genres", []), *group.get("genres", [])]
                if row.get("name")
            )
        )[:40]
        album = AlbumInput(
            title=data["title"],
            artist=artist or "Unknown artist",
            year=release_year(data.get("date")),
            release_type=kind,
            provider_id=identifier,
            release_group_id=group.get("id"),
            edition_info={
                "name": str(data.get("disambiguation") or "")[:500],
                "date": str(data.get("date") or "")[:100],
                "country": str(data.get("country") or "")[:100],
                "format": ", ".join(
                    dict.fromkeys(
                        str(row.get("format"))
                        for row in data.get("media", [])
                        if row.get("format")
                    )
                )[:200],
                "language": str((data.get("text-representation") or {}).get("language") or "")[
                    :100
                ],
                "labels": list(
                    dict.fromkeys(
                        (row.get("label") or {}).get("name", "")
                        for row in data.get("label-info") or []
                        if isinstance(row, dict) and (row.get("label") or {}).get("name")
                    )
                )[:20],
                "catalog_numbers": list(
                    dict.fromkeys(
                        row["catalog-number"]
                        for row in data.get("label-info") or []
                        if isinstance(row, dict) and row.get("catalog-number")
                    )
                )[:20],
                "barcode": str(data.get("barcode") or "")[:100],
                "original_year": release_year(group.get("first-release-date")),
                "artwork_scope": "Selected edition"
                if data.get("cover-art-archive", {}).get("front") and not prefer_group_art
                else "Release group",
            },
            artwork_url=(
                f"https://coverartarchive.org/release/{identifier}/front-1200"
                if data.get("cover-art-archive", {}).get("front") and not prefer_group_art
                else f"https://coverartarchive.org/release-group/{group['id']}/front-1200"
                if group.get("id")
                else None
            ),
            genres=genres,
            tracks=tracks,
        )
        if not artwork_choices:
            if album.artwork_url:
                album.artwork_url = album.artwork_url.replace("/front-1200", "/front-500")
            return album.model_dump(mode="json")
        # Consult only this release and, if needed, its exact release group.
        # Curated front/approved/type labels can avoid known packaging scans;
        # they do not establish that an image is a pristine digital master.
        artwork_sources = [
            (f"release/{identifier}/", "Selected edition"),
            (f"release-group/{group.get('id')}/", "Release group"),
        ]
        if prefer_group_art:
            artwork_sources.reverse()
        for path, scope in artwork_sources:
            if scope == "Release group" and not group.get("id"):
                continue
            try:
                choices = image_options(await self.artwork_client._artwork_get(path), scope)
            except ProviderError:
                # Preserve the representative cover endpoint if its optional
                # JSON request fails; a test-pressing scan is not a better cover.
                if scope == "Release group" and prefer_group_art:
                    return album.model_dump(mode="json")
                continue
            front = next(
                (row for row in choices if row["front"] and not row["packaging"]), None
            )
            if front:
                album.artwork_url = front["url"]
                album.edition_info.artwork_scope = scope
                break
        return album.model_dump(mode="json")

    async def artwork_options(self, identifier: UUID, group_id: UUID | None = None) -> dict:
        """Read-only alternate art for this album, never a metadata relink."""
        options = []
        seen = set()
        incomplete = False

        async def append_images(path: str):
            nonlocal incomplete
            try:
                data = await self.artwork_client._artwork_get(path)
            except ProviderError:
                incomplete = True
                return
            for option in image_options(
                data, "Release group" if "release-group" in path else "Selected edition"
            ):
                if option["url"] in seen:
                    continue
                seen.add(option["url"])
                options.append(option)
                if len(options) >= 24:
                    break

        if group_id:
            await append_images(f"release-group/{group_id}/")
        await append_images(f"release/{identifier}/")
        if group_id and len(options) < 24:
            try:
                editions = await self._artwork_get(
                    "release/", **{"release-group": str(group_id), "limit": 12}
                )
            except ProviderError:
                incomplete = True
            else:
                for row in editions.get("releases", []):
                    try:
                        release_id = UUID(row["id"])
                    except (ValueError, TypeError, KeyError):
                        continue
                    if release_id == identifier or not row.get("cover-art-archive", {}).get(
                        "front"
                    ):
                        continue
                    root = f"https://coverartarchive.org/release/{release_id}/front"
                    label = " · ".join(
                        str(row[key])
                        for key in ("date", "country", "disambiguation")
                        if row.get(key)
                    )
                    options.append(
                        {
                            "url": root + "-1200",
                            "thumbnail_url": root + "-250",
                            "label": label or "Alternate edition",
                            "source": "Cover Art Archive",
                            "scope": "Alternate edition",
                            "front": True,
                            "packaging": False,
                        }
                    )
                    if len(options) >= 24:
                        break
        options.sort(
            key=lambda row: (
                not row.get("front"),
                row.get("packaging", False),
                row.get("scope") != "Release group",
            )
        )
        return {
            "options": options,
            "source": "Cover Art Archive",
            "warning": "Some artwork sources are unavailable. You can retry or upload an image."
            if incomplete
            else None,
        }
