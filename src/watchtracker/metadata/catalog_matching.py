"""Small, deterministic relevance rules for optional collection searches.

These order candidates for a human to select; they never establish identity or
automatically attach metadata. Provider popularity is not a title match.
"""

import re
import unicodedata


def normalized_title(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value)).casefold()
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(re.findall(r"\w+", value))


def title_distance(title: str, query: str) -> tuple[int, int]:
    title, query = normalized_title(title), normalized_title(query)
    if title == query:
        return (0, 0)
    words, wanted = set(title.split()), set(query.split())
    if query and query in title:
        return (1, len(words - wanted))
    if wanted and wanted <= words:
        return (2, len(words - wanted))
    return (3, len(wanted - words))


def secondary_book(title: str, query: str) -> bool:
    # A study guide is useful when requested, not a substitute for its subject.
    pattern = r"\b(notes|study guide|study guides|summary|summaries|cliffsnotes|sparknotes|analysis|criticism)\b"
    return bool(re.search(pattern, normalized_title(title))) and not bool(
        re.search(pattern, normalized_title(query))
    )
