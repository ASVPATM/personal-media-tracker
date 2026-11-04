"""Conservative album identity matching; artwork/popularity are not identity evidence."""

import re
import unicodedata

from watchtracker.metadata.collection_identity import collection_title


def name_key(value):
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("&", " and ")
    text = re.sub(r"(?<=\w)['’‘](?=\w)", "", text)
    # 10 000, 10,000 and 10000 represent the same number, not different albums.
    text = re.sub(r"(?<=\d)[\s,.](?=\d{3}(?:\D|$))", "", text)
    return collection_title(text)


def album_key(value):
    text = name_key(value)
    # Packaging labels are not a different musical work. Preserve deluxe,
    # remaster, live and numbered-part qualifiers, which can change identity.
    text = re.sub(r"^eco pack\s+", "", text)
    text = re.sub(r"\bhertz\b", "hz", text)
    # Only non-identifying soundtrack boilerplate. Do NOT strip live/remix/
    # deluxe/year qualifiers or arbitrary subtitles from album identities.
    text = re.sub(
        r"\b(?:music from the |music from |the )?(?:original )?"
        r"(?:motion picture |film |movie )?(?:soundtrack|score)\b",
        " ",
        text,
    )
    return " ".join(text.split())


def one_typo(left, right, minimum=8):
    """One edit in a substantial name; short/partial artist names never qualify."""
    if min(len(left), len(right)) < minimum or abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        differences = [
            index for index, (a, b) in enumerate(zip(left, right, strict=True)) if a != b
        ]
        return len(differences) == 1 or (
            len(differences) == 2
            and differences[1] == differences[0] + 1
            and left[differences[0]] == right[differences[1]]
            and left[differences[1]] == right[differences[0]]
        )
    short, long = sorted((left, right), key=len)
    for index, (a, b) in enumerate(zip(short, long, strict=False)):
        if a != b:
            return short[index:] == long[index + 1 :]
    return True


def artist_names(credit):
    names = []
    combined = ""
    for part in credit or []:
        if not isinstance(part, dict):
            continue
        artist = part.get("artist") or part
        names.extend([part.get("name"), artist.get("name")])
        combined += (part.get("name") or artist.get("name") or "") + part.get("joinphrase", "")
        names.extend(alias.get("name") for alias in artist.get("aliases") or [])
    return [name for name in [combined, *names] if name]


def artist_strength(source, names):
    key = name_key(source)
    if not key or key in {"unknown", "unknown artist", "various", "various artists"}:
        return 0
    keys = [name_key(name) for name in names if name]
    if key in keys:
        return 3
    if (
        len(key) >= 8
        and len(key.split()) > 1
        and any(sorted(key.split()) == sorted(other.split()) for other in keys)
    ):
        return 2
    # A typo is admissible only alongside an exact album title below, and a
    # unique artist/release-group candidate, never as a broad fuzzy match.
    if any(one_typo(key, other) for other in keys):
        return 2
    return 0


def choose_group(source, groups, *, allow_named_remix=False):
    candidates = []
    title = album_key(source["title"])
    for row in groups:
        aliases = [row.get("title"), *(a.get("name") for a in row.get("aliases") or [])]
        titles = [album_key(value) for value in aliases if value]
        title_score = (
            3 if any(title.replace(" ", "") == key.replace(" ", "") for key in titles) else 0
        )
        # A colon-delimited descriptive subtitle may be omitted in an import.
        # Do not turn a live, deluxe, instrumental or numbered part into its
        # parent album. Distinct surviving groups still require disambiguation.
        main, separator, subtitle = str(row.get("title", "")).partition(":")
        qualifiers = {
            "live",
            "remix",
            "deluxe",
            "expanded",
            "anniversary",
            "instrumental",
            "karaoke",
            "part",
            "vol",
            "volume",
        }
        if (
            not title_score
            and separator
            and len(title) >= 8
            and album_key(main) == title
            and not qualifiers.intersection(name_key(subtitle).split())
        ):
            title_score = 2
        # OCR/copying often confuses capital I and lowercase l. Require an
        # otherwise exact substantial title, an exact artist, and a unique work.
        strength = artist_strength(source["artist"], artist_names(row.get("artist-credit")))
        if (
            not title_score
            and strength == 3
            and len(title) >= 10
            and any(
                title.translate(str.maketrans({"i": "l"}))
                == key.translate(str.maketrans({"i": "l"}))
                for key in titles
            )
        ):
            title_score = 2
        if (
            not title_score
            and strength == 3
            and any(one_typo(title, key, minimum=6) for key in titles)
        ):
            title_score = 2
        if not strength or not title_score or (strength == 2 and title_score != 3):
            continue
        secondary = {str(value).lower() for value in row.get("secondary-types") or []}
        # A studio album cannot silently turn into a live/remix/compilation.
        if any(
            kind in secondary
            and kind not in name_key(source["title"]).split()
            and not (
                kind == "remix" and allow_named_remix and title_score == 3 and strength == 3
            )
            for kind in ("live", "remix")
        ):
            continue
        kind = str(row.get("primary-type", "")).lower()
        if "compilation" in secondary:
            kind = "compilation"
        expected = source.get("release_type", "album")
        candidates.append(((strength + title_score, kind == expected), row))
    if not candidates:
        return None
    best_score = max(item[0] for item in candidates)
    best = {row["id"]: row for score, row in candidates if score == best_score}
    if len(best) > 1 and source.get("year"):
        best = {
            key: row
            for key, row in best.items()
            if str(row.get("first-release-date", ""))[:4] == str(source["year"])
        }
    return next(iter(best.values())) if len(best) == 1 else None
