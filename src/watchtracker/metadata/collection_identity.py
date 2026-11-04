"""Conservative, tenant-scoped collection identity across manual/catalog entries.

No existing records are merged or deleted. The same rules power import preview,
commit, editing and background enrichment. Physical format alone is not a work.
"""

import re
from collections import Counter, defaultdict

from watchtracker.metadata.catalog_matching import normalized_title


def value(row, key, default=None):
    return row.get(key, default) if isinstance(row, dict) else getattr(row, key, default)


def collection_title(text):
    return re.sub(r"^(the|a|an) ", "", normalized_title(text or ""))


def import_identity_warnings(rows, creator):
    """Preview-only cautions, not spelling guesses or additional network calls."""
    counts, identities = Counter(), {}
    for row in rows:
        name = str(row.get(creator) or "").strip()
        if not name or name.casefold() in {"unknown", "n/a", "?"}:
            counts["missing_creator"] += 1
        elif len(name) <= 2 or name.endswith(("…", "...")):
            counts["short_creator"] += 1
        if identity := row.get("provider_id"):
            counts["supplied_identity"] += 1
            signature = (
                collection_title(row.get("title")),
                collection_title(name),
                version_label(row),
            )
            if identity in identities and identities[identity] != signature:
                counts["conflicting_identity"] += 1
            identities[identity] = signature
    return [{"code": code, "count": count} for code, count in counts.items()]


def version_label(row):
    info = value(row, "edition_info") or {}
    text = normalized_title(info.get("name", ""))
    return tuple(
        word
        for word in ("deluxe", "expanded", "anniversary", "remaster", "bonus")
        if word in text.replace("remastered", "remaster").split()
    )


def same_collection_item(left, right, domain):
    lp, rp = value(left, "provider_id"), value(right, "provider_id")
    if lp and lp == rp:
        return True
    if (
        domain == "books"
        and value(left, "isbn")
        and value(left, "isbn") == value(right, "isbn")
    ):
        return True
    group = "work_id" if domain == "books" else "release_group_id"
    lg, rg = value(left, group), value(right, group)
    if domain == "music" and lp and rp and lg and rg and lg != rg:
        return False
    if domain == "music" and version_label(left) != version_label(right) and lp and rp:
        return False
    if domain == "books":
        # A specifically selected translation remains a distinct edition.
        ll = (value(left, "edition_info") or {}).get("language")
        rl = (value(right, "edition_info") or {}).get("language")
        if ll and rl and ll != rl:
            return False
    if lg and lg == rg:
        return True
    creator = "author" if domain == "books" else "artist"
    if collection_title(value(left, "title")) != collection_title(value(right, "title")):
        return False
    if normalized_title(value(left, creator) or "") != normalized_title(
        value(right, creator) or ""
    ):
        return False
    # Different, explicitly identified album groups are never guessed together.
    # Without catalog IDs a known year helps separate same-name recordings.
    ly, ry = value(left, "year"), value(right, "year")
    return domain == "books" or not (ly and ry and ly != ry)


class CollectionIndex:
    def __init__(self, domain, rows=()):
        self.domain = domain
        self.buckets = defaultdict(list)
        for row in rows:
            self.add(row)

    def keys(self, row):
        for field in (
            "provider_id",
            "isbn" if self.domain == "books" else "release_group_id",
            "work_id",
        ):
            if item := value(row, field):
                yield (field, str(item))
        creator = "author" if self.domain == "books" else "artist"
        yield (
            "title",
            collection_title(value(row, "title")),
            normalized_title(value(row, creator) or ""),
        )

    def add(self, row):
        for key in self.keys(row):
            self.buckets[key].append(row)

    def find(self, data, exclude=None):
        for key in self.keys(data):
            for row in self.buckets.get(key, ()):
                if exclude and value(row, "id") == exclude:
                    continue
                if same_collection_item(row, data, self.domain):
                    return row
        return None
