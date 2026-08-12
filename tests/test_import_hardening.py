from __future__ import annotations

import io
import zipfile

import pytest

from watchtracker.imports.parsers import ImportLimits, parse_letterboxd_zip, parse_manual_csv


def make_zip(members: dict[str, bytes | str]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in members.items():
            archive.writestr(name, value)
    return output.getvalue()


def test_letterboxd_zip_rejects_traversal_nested_archives_and_executable_content():
    diary = "Name,Year\nFilm,2020\n"
    for unsafe_name in ("../diary.csv", "payload.exe", "nested.zip"):
        content = make_zip({"diary.csv": diary, unsafe_name: b"unsafe"})
        with pytest.raises(ValueError):
            parse_letterboxd_zip(content)


def test_letterboxd_zip_limits_members_decompressed_size_and_compression_ratio():
    diary = "Name,Year\nFilm,2020\n"
    too_many = make_zip({"diary.csv": diary, **{f"ignored-{i}.txt": "x" for i in range(5)}})
    with pytest.raises(ValueError, match="member"):
        parse_letterboxd_zip(too_many, limits=ImportLimits(max_members=3))

    oversized = make_zip({"diary.csv": "A" * 20_000})
    with pytest.raises(ValueError, match="decompressed|compression|large"):
        parse_letterboxd_zip(
            oversized,
            limits=ImportLimits(
                max_decompressed_bytes=10_000,
                max_member_bytes=50_000,
                max_compression_ratio=10_000,
            ),
        )

    bomb = make_zip({"diary.csv": "A" * 500_000})
    with pytest.raises(ValueError, match="compression"):
        parse_letterboxd_zip(
            bomb,
            limits=ImportLimits(
                max_decompressed_bytes=1_000_000,
                max_member_bytes=1_000_000,
                max_compression_ratio=20,
            ),
        )


def test_csv_row_and_cell_limits_and_malformed_quoting():
    rows = b"title\nOne\nTwo\n"
    with pytest.raises(ValueError, match="row safety"):
        parse_manual_csv(rows, limits=ImportLimits(max_rows=1))

    parsed, invalid, _ = parse_manual_csv(
        b"title,notes\nFilm," + b"x" * 2_000 + b"\n",
        limits=ImportLimits(max_cell_chars=1_000),
    )
    assert parsed == []
    assert invalid[0]["error"] == "a cell exceeds the configured size limit"

    with pytest.raises(ValueError, match="Malformed CSV"):
        parse_manual_csv(b'title,notes\nFilm,"unterminated\n')
