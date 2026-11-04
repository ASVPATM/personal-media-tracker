from __future__ import annotations

import re
from contextlib import suppress

from watchtracker.books.schemas import BookInput
from watchtracker.metadata.catalog_matching import (
    normalized_title,
    secondary_book,
    title_distance,
)
from watchtracker.metadata.http import ProviderError
from watchtracker.music.provider import PublicCatalogClient


def text_value(value):
    return value.get("value", "") if isinstance(value, dict) else str(value or "")


def list_text(value):
    return (
        ", ".join(str(item) for item in value) if isinstance(value, list) else str(value or "")
    )


def edition_year(value):
    match = re.search(r"(?<!\d)(1\d{3}|20\d{2}|21\d{2}|2200)(?!\d)", str(value or ""))
    return int(match[1]) if match else None


def edition_pages(edition):
    number = edition.get("number_of_pages")
    if isinstance(number, str) and re.fullmatch(r"\d{1,6}", number.strip()):
        number = int(number)
    if type(number) is int and 0 < number <= 100000:
        return number, "Selected edition"
    pagination = str(edition.get("pagination") or "")
    match = re.search(r"(?:^|[,;\s(\[])(\d{1,6})\s*(?:p\b|pages\b)", pagination, re.I)
    if not match:
        match = re.fullmatch(r"\s*(?:[ivxlcdm]+[,;]\s*)?(\d{1,6})\s*", pagination, re.I)
    if match and 0 < int(match[1]) <= 100000:
        return int(match[1]), "Selected edition pagination"
    return None, ""


def edition_format(value):
    value = str(value or "").lower()
    if "paper" in value or "soft" in value:
        return "paperback"
    if "hard" in value:
        return "hardcover"
    if "ebook" in value or "e-book" in value or "electronic" in value:
        return "ebook"
    return "other" if value else "book"


class OpenLibraryProvider(PublicCatalogClient):
    api_root = "https://openlibrary.org/"
    provider_name = "Open Library"
    default_params = {}

    async def preferred_edition(self, candidate: dict, source: dict, language="en"):
        """Choose a complete edition only while first matching an unlinked book.

        Never borrow a page count from a different edition of a linked book or
        override an explicit ISBN/year/format. The chosen ID owns every fact.
        """
        if source.get("provider_id") or source.get("isbn") or not candidate.get("work_id"):
            return candidate
        try:
            editions = await self.editions(
                candidate["work_id"],
                title=source["title"],
                language=language,
                preferred=candidate["provider_id"],
            )
        except ProviderError:
            return candidate
        wanted_title = re.sub(r"^(the|a|an) ", "", normalized_title(source["title"]))
        wanted_language = (
            (source.get("edition_info") or {}).get("language")
            or candidate.get("language")
            or {"en": "eng", "fr": "fre", "zh-CN": "chi"}.get(language, "eng")
        )
        for row in editions["results"]:
            if not row.get("page_count") or not row.get("year"):
                continue
            if re.sub(r"^(the|a|an) ", "", normalized_title(row["title"])) != wanted_title:
                continue
            if row.get("language") and not set(row["language"].split(", ")) & set(
                wanted_language.split(", ")
            ):
                continue
            if source.get("year") and row["year"] != source["year"]:
                continue
            kind = source.get("book_format")
            if (
                kind in {"paperback", "hardcover", "ebook"}
                and edition_format(row.get("edition")) != kind
            ):
                continue
            if re.search(r"audio|large.print|abridg", row.get("edition", ""), re.I):
                continue
            return {**candidate, **row}
        return candidate

    async def search(self, query: str, author: str = "", language: str = "en"):
        parameters = {
            # Include translated edition titles even if the primary work's
            # title is in another language. Quote user text as a literal.
            "q": '"' + query.replace("\\", "\\\\").replace('"', '\\"') + '"',
            "limit": 40,
            "fields": "key,title,author_name,author_key,first_publish_year,edition_count,cover_i,editions,editions.key,editions.title,editions.cover_i,editions.publish_date,editions.language,editions.publisher,editions.physical_format",
            "lang": {"en": "en", "fr": "fr", "zh-CN": "zh"}.get(language, "en"),
        }
        if author:
            parameters["author"] = author
        data = await self._search_get("search.json", **parameters)
        results = []
        seen = set()
        for row in data.get("docs", []):
            # Work.edition_key is unordered; its first value can be an unrelated
            # language/format. Use the edition ranked for this exact search.
            editions = row.get("editions", {}).get("docs", [])
            edition = next(
                (
                    item
                    for item in editions
                    if re.fullmatch(r"/books/OL\d+M", item.get("key", ""))
                ),
                None,
            )
            if not edition or not edition.get("title"):
                continue
            identifier = edition["key"].removeprefix("/books/")
            work = str(row.get("key", "")).removeprefix("/works/")
            work = work if re.fullmatch(r"OL\d+W", work) else None
            identity = work or identifier
            if identity in seen:
                continue
            seen.add(identity)
            cover = edition.get("cover_i") or row.get("cover_i")
            results.append(
                {
                    "provider_id": identifier,
                    "work_id": work,
                    "work_title": str(row.get("title") or edition["title"])[:500],
                    "title": str(edition["title"])[:500],
                    "author": ", ".join(row.get("author_name", []))[:500],
                    "author_ids": sorted(
                        key
                        for key in row.get("author_key", [])
                        if re.fullmatch(r"OL\d+A", str(key))
                    ),
                    "year": edition_year(edition.get("publish_date")),
                    "original_year": row.get("first_publish_year"),
                    "edition_count": row.get("edition_count")
                    if type(row.get("edition_count")) is int
                    else 0,
                    "edition": " · ".join(
                        filter(
                            None,
                            [
                                list_text(edition.get("publish_date")),
                                list_text(edition.get("publisher")),
                                list_text(edition.get("language")),
                            ],
                        )
                    ),
                    "artwork_url": f"https://covers.openlibrary.org/b/id/{int(cover)}-L.jpg?default=false"
                    if isinstance(cover, int) and cover > 0
                    else None,
                    "artwork_fallbacks": [
                        f"https://covers.openlibrary.org/b/id/{value}-L.jpg?default=false"
                        for value in [row.get("cover_i")]
                        if type(value) is int and value > 0 and value != cover
                    ],
                }
            )

        def display_title(value):
            # Leading articles do not distinguish editions; volume numbers,
            # adaptations and subtitles still do. This only groups search UI.
            return re.sub(r"^(the|a|an) ", "", normalized_title(value))

        results.sort(
            key=lambda row: (
                secondary_book(row["work_title"], query) or secondary_book(row["title"], query),
                min(
                    title_distance(display_title(row["title"]), display_title(query)),
                    title_distance(display_title(row["work_title"]), display_title(query)),
                ),
                title_distance(row["author"], author) if author else (0, 0),
                not bool(row["author"]),
                not bool(row["artwork_url"]),
                -min(10000, max(0, row["edition_count"])),
                row["original_year"] if isinstance(row["original_year"], int) else 9999,
            )
        )
        grouped = {}
        for row in results:
            # Open Library sometimes has duplicate *work* records. Stable
            # author IDs let us collapse transliterated author names safely.
            # Never combine works by title alone or union different authors.
            creator = tuple(row["author_ids"]) or normalized_title(row["author"])
            key = (display_title(row["title"]), creator or row["work_id"])
            if key not in grouped:
                grouped[key] = {**row, "catalog_alternatives": [], "catalog_count": 1}
                continue
            primary = grouped[key]
            primary["catalog_count"] += 1
            primary["catalog_alternatives"].append(row)
        return {
            "results": list(grouped.values())[:24],
            "source": "Open Library",
            "result_kind": "works",
        }

    async def by_isbn(self, isbn: str):
        if not re.fullmatch(r"[\dX]{10}|\d{13}", isbn):
            raise ValueError("Invalid ISBN")
        data = await self._get("api/books", bibkeys=f"ISBN:{isbn}", format="json", jscmd="data")
        item = data.get(f"ISBN:{isbn}", {})
        identifiers = item.get("identifiers", {}).get("openlibrary", [])
        identifier = next(
            (key for key in identifiers if re.fullmatch(r"OL\d+M", str(key))), None
        )
        if not identifier:
            return None
        details = await self.detail(identifier)
        # This is the ISBN resolver's edition, not a title-only guess.
        return details

    async def detail(self, identifier: str):
        if not re.fullmatch(r"OL\d+M", identifier):
            raise ValueError("Invalid Open Library edition")
        edition = await self._get(f"books/{identifier}.json")
        work_id = next(
            (
                row.get("key", "").removeprefix("/works/")
                for row in edition.get("works", [])
                if re.fullmatch(r"/works/OL\d+W", row.get("key", ""))
            ),
            None,
        )
        # Edition metadata remains useful when an optional work/author lookup fails.
        work = {}
        if work_id:
            with suppress(ProviderError):
                work = await self._get(f"works/{work_id}.json")
        authors = []
        for row in (edition.get("authors") or work.get("authors", []))[:3]:
            key = row.get("key") or row.get("author", {}).get("key", "")
            if re.fullmatch(r"/authors/OL\d+A", key):
                try:
                    author = await self._get(key.lstrip("/") + ".json")
                except ProviderError:
                    continue
                if author.get("name"):
                    authors.append(author["name"])
        # Prefer the work's representative cover over an arbitrary edition scan.
        # Artwork scope is disclosed; this never borrows year/pages from the work
        # or changes the selected edition, ISBN or private reading progress.
        covers = [
            item for item in work.get("covers", []) if type(item) is int and item > 0
        ] or edition.get("covers", [])
        cover = next((item for item in covers if isinstance(item, int) and item > 0), None)
        year = edition_year(edition.get("publish_date") or edition.get("copyright_date"))
        page_count, page_source = edition_pages(edition)
        isbn = None
        for candidate in [*edition.get("isbn_13", []), *edition.get("isbn_10", [])]:
            try:
                isbn = BookInput.isbn_format(candidate)
                break
            except ValueError:
                continue
        result = BookInput(
            title=edition.get("title") or work["title"],
            author=", ".join(authors)[:500] or "Unknown author",
            year=year,
            book_format=edition_format(edition.get("physical_format")),
            publisher=", ".join(edition.get("publishers", []))[:500],
            description=text_value(edition.get("description") or work.get("description"))[
                :20000
            ],
            page_count=page_count,
            edition_info={
                "name": str(edition.get("edition_name") or "")[:500],
                "date": list_text(edition.get("publish_date") or edition.get("copyright_date"))[
                    :100
                ],
                "format": str(edition.get("physical_format") or "")[:200],
                "language": ", ".join(
                    row.get("key", "").removeprefix("/languages/")
                    for row in edition.get("languages", [])
                    if isinstance(row, dict)
                )[:100],
                "original_year": edition_year(work.get("first_publish_date")),
                "page_count_source": page_source,
                "artwork_scope": "Selected edition"
                if edition.get("covers") and cover in edition["covers"]
                else "Work cover",
                "warning": "This edition is missing its publication year or page count. Choose another edition with those details; other editions may differ."
                if not year or not page_count
                else "",
            },
            isbn=isbn,
            provider_id=identifier,
            work_id=work_id,
            artwork_url=f"https://covers.openlibrary.org/b/id/{cover}-L.jpg?default=false"
            if cover
            else None,
            genres=list(
                dict.fromkeys(
                    str(value).strip()[:100]
                    for value in [*edition.get("subjects", []), *work.get("subjects", [])]
                    if str(value).strip()
                )
            )[:40],
            chapters=[
                str(row["title"])[:500]
                for row in edition.get("table_of_contents", [])
                if isinstance(row, dict) and row.get("title")
            ][:1000],
        )
        return result.model_dump(mode="json")

    async def editions(
        self, identifier: str, title: str = "", language: str = "en", preferred: str = ""
    ):
        if not re.fullmatch(r"OL\d+[MW]", identifier):
            raise ValueError("Invalid Open Library identifier")
        edition = (
            await self._get(f"books/{identifier}.json") if identifier.endswith("M") else {}
        )
        work = (
            f"/works/{identifier}"
            if identifier.endswith("W")
            else next(
                (
                    row.get("key")
                    for row in edition.get("works", [])
                    if re.fullmatch(r"/works/OL\d+W", row.get("key", ""))
                ),
                None,
            )
        )
        if not work:
            return {"results": [], "source": "Open Library"}
        # One bounded work-scoped request, not a new global title search.
        data = await self._search_get(work.lstrip("/") + "/editions.json", limit=100)
        entries = data.get("entries", [])
        if edition:
            entries = [edition, *entries]
        elif re.fullmatch(r"OL\d+M", preferred):
            # Search ranks one relevant edition; keep it even when outside the
            # first page of a work's many editions. Verify its work membership.
            with suppress(ProviderError):
                candidate = await self._get(f"books/{preferred}.json")
                if any(row.get("key") == work for row in candidate.get("works", [])):
                    entries = [candidate, *entries]
        results = []
        seen = set()
        for row in entries:
            key = str(row.get("key", "")).removeprefix("/books/")
            if not re.fullmatch(r"OL\d+M", key) or key in seen:
                continue
            seen.add(key)
            pages, _ = edition_pages(row)
            cover = next(
                (value for value in row.get("covers", []) if type(value) is int and value > 0),
                None,
            )
            results.append(
                {
                    "provider_id": key,
                    "work_id": work.removeprefix("/works/"),
                    "title": row.get("title", ""),
                    "author": "",
                    "year": edition_year(row.get("publish_date")),
                    "page_count": pages,
                    "edition": " · ".join(
                        filter(
                            None,
                            [
                                list_text(row.get("edition_name")),
                                list_text(row.get("physical_format")),
                                list_text(row.get("publishers")),
                            ],
                        )
                    )[:500],
                    "isbn": (row.get("isbn_13") or row.get("isbn_10") or [None])[0],
                    "language": ", ".join(
                        item.get("key", "").removeprefix("/languages/")
                        for item in row.get("languages", [])
                        if isinstance(item, dict)
                    ),
                    "artwork_url": f"https://covers.openlibrary.org/b/id/{cover}-L.jpg?default=false"
                    if cover
                    else None,
                }
            )
        results.sort(
            key=lambda row: (
                title_distance(
                    re.sub(r"^(the|a|an) ", "", normalized_title(row["title"])),
                    re.sub(r"^(the|a|an) ", "", normalized_title(title)),
                )
                if title
                else (0, 0),
                0
                if {"en": "eng", "fr": "fre", "zh-CN": "chi"}.get(language, "eng")
                in row["language"].split(", ")
                else 1
                if not row["language"]
                else 2,
                bool(re.search(r"audio|large.print|abridg", row["edition"], re.I)),
                not bool(row["page_count"] and row["year"]),
                not bool(row["artwork_url"]),
            )
        )
        return {
            "results": results[:40],
            "source": "Open Library",
            "work_id": work.removeprefix("/works/"),
            "limited": len(data.get("entries", [])) >= 100,
        }

    async def artwork_options(self, identifier: str, work_id: str | None = None) -> dict:
        if not re.fullmatch(r"OL\d+M", identifier):
            raise ValueError("Invalid Open Library edition")
        if work_id and not re.fullmatch(r"OL\d+W", work_id):
            raise ValueError("Invalid Open Library work")
        options = []
        seen = set()
        incomplete = False

        def append_covers(record: dict, label: str):
            for cover in record.get("covers", [])[:40]:
                if type(cover) is not int or cover <= 0 or cover in seen:
                    continue
                seen.add(cover)
                root = f"https://covers.openlibrary.org/b/id/{cover}"
                options.append(
                    {
                        "url": root + "-L.jpg?default=false",
                        "thumbnail_url": root + "-M.jpg?default=false",
                        "label": label[:240],
                        "source": "Open Library",
                        "scope": label,
                        "front": True,
                    }
                )
                if len(options) >= 24:
                    break

        try:
            edition = await self._artwork_get(f"books/{identifier}.json")
        except ProviderError:
            incomplete = True
        else:
            append_covers(edition, "Selected edition")
            work_id = work_id or next(
                (
                    row["key"].removeprefix("/works/")
                    for row in edition.get("works", [])
                    if re.fullmatch(r"/works/OL\d+W", row.get("key", ""))
                ),
                None,
            )
        if work_id and len(options) < 24:
            try:
                work = await self._artwork_get(f"works/{work_id}.json")
            except ProviderError:
                incomplete = True
            else:
                append_covers(work, "Work cover")
            if len(options) < 24:
                try:
                    editions = await self._artwork_get(
                        f"works/{work_id}/editions.json", limit=24
                    )
                except ProviderError:
                    incomplete = True
                else:
                    for row in editions.get("entries", [])[:24]:
                        if not isinstance(row, dict):
                            continue
                        label = " · ".join(
                            [
                                str(row.get("publish_date") or "Alternate edition"),
                                ", ".join(str(value) for value in row.get("publishers", []))[
                                    :150
                                ],
                            ]
                        ).strip(" ·")
                        append_covers(row, label)
                        if len(options) >= 24:
                            break
        return {
            "options": options,
            "source": "Open Library",
            "warning": "Some artwork sources are unavailable. You can retry or upload an image."
            if incomplete
            else None,
        }
