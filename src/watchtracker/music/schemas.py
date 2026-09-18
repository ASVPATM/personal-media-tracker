from __future__ import annotations

import base64
import hashlib
import io
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from PIL import Image, UnidentifiedImageError
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    StringConstraints,
    field_validator,
    model_validator,
)

Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
# "collected" is a legacy/unknown compatibility value, not an offered UI choice.
MusicStatus = Literal["collected", "listening", "listened", "plan_to_listen"]


def normalize_artwork(data: bytes) -> str:
    if len(data) > 4 * 1024 * 1024:
        raise ValueError("Choose an artwork image smaller than 4 MB.")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if (
                image.format not in {"PNG", "JPEG", "WEBP"}
                or image.width * image.height > 16_000_000
            ):
                raise ValueError("Choose a PNG, JPEG or WebP image up to 16 megapixels.")
            image = image.convert("RGB")
            image.thumbnail((800, 800))
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=88)
            return "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode(
                "ascii"
            )
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ValueError("This artwork image could not be read.") from exc


class MusicTrack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID = Field(default_factory=uuid4)
    disc: int = Field(default=1, ge=1, le=100)
    position: int = Field(ge=1, le=1000)
    title: Label
    artist: str = Field(default="", max_length=500)
    duration_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    recording_id: UUID | None = None


class EditionInfo(BaseModel):
    """Bounded provider facts about the selected edition, never another edition's counts."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="", max_length=500)
    date: str = Field(default="", max_length=100)
    format: str = Field(default="", max_length=200)
    language: str = Field(default="", max_length=100)
    country: str = Field(default="", max_length=100)
    labels: list[Label] = Field(default_factory=list, max_length=20)
    catalog_numbers: list[Label] = Field(default_factory=list, max_length=20)
    barcode: str = Field(default="", max_length=100)
    original_year: int | None = Field(default=None, ge=1000, le=2200)
    page_count_source: str = Field(default="", max_length=100)
    artwork_scope: str = Field(default="", max_length=100)
    warning: str = Field(default="", max_length=1000)


class CollectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    _artwork_input_digest: bytes | None = PrivateAttr(default=None)
    title: Label
    year: int | None = Field(default=None, ge=1000, le=2200)
    rating: float | None = Field(default=None, ge=1, le=10, multiple_of=0.1)
    favorite: bool = False
    completion_count: int | None = Field(default=None, ge=0, le=1_000_000)
    edition_info: EditionInfo = Field(default_factory=EditionInfo)
    genre_additions: list[Label] = Field(default_factory=list, max_length=40)
    genre_removals: list[Label] = Field(default_factory=list, max_length=40)
    subgenre_additions: list[Label] = Field(default_factory=list, max_length=40)
    subgenre_removals: list[Label] = Field(default_factory=list, max_length=40)
    genres: list[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    ] = Field(default_factory=list, max_length=40)
    # Providers expose flat genres/subjects, not a reliable parent/child taxonomy.
    # Keep explicitly chosen subgenres separate rather than inventing classifications.
    subgenres: list[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    ] = Field(default_factory=list, max_length=40)
    tags: list[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    ] = Field(default_factory=list, max_length=40)
    notes: str = Field(default="", max_length=20000)
    artwork_url: str | None = Field(default=None, max_length=2000)
    artwork_data: str | None = Field(default=None, max_length=2_000_000)

    @model_validator(mode="wrap")
    @classmethod
    def remember_validated_artwork_input(cls, value, handler):
        # Validate/sanitize first. Remember only the fingerprint of the raw
        # input, privately, so an update sending the exact existing cover can
        # preserve those bytes instead of applying another lossy JPEG encode.
        result = handler(value)
        if isinstance(value, dict) and isinstance(value.get("artwork_data"), str):
            result._artwork_input_digest = hashlib.sha256(
                value["artwork_data"].encode("utf-8")
            ).digest()
        return result

    def artwork_for_update(self, existing: str | None) -> str | None:
        if (
            existing
            and self._artwork_input_digest == hashlib.sha256(existing.encode("utf-8")).digest()
        ):
            return existing
        return self.artwork_data

    @field_validator("artwork_url")
    @classmethod
    def safe_artwork_url(cls, value):
        if not value:
            return None
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
        ):
            raise ValueError("Artwork links must use HTTPS without credentials.")
        if parsed.hostname not in {
            "coverartarchive.org",
            "archive.org",
            "covers.openlibrary.org",
        } and not parsed.hostname.endswith(".archive.org"):
            raise ValueError(
                "Use a Cover Art Archive, Internet Archive or Open Library image link, or upload the image."
            )
        return value

    @field_validator("artwork_data")
    @classmethod
    def safe_artwork_data(cls, value):
        if not value:
            return None
        if not value.startswith("data:image/") or ";base64," not in value:
            raise ValueError("Invalid embedded artwork.")
        try:
            raw = base64.b64decode(value.split(";base64,", 1)[1], validate=True)
        except ValueError as exc:
            raise ValueError("Invalid embedded artwork.") from exc
        return normalize_artwork(raw)


class AlbumInput(CollectionInput):
    artist: Label
    release_type: Literal["album", "ep", "single", "compilation", "other"] = "album"
    status: MusicStatus = "plan_to_listen"
    provider_id: UUID | None = None
    release_group_id: UUID | None = None
    tracks: list[MusicTrack] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def unique_tracks(self):
        if len({track.id for track in self.tracks}) != len(self.tracks):
            raise ValueError("Track identifiers must be unique within an album.")
        if len({(track.disc, track.position) for track in self.tracks}) != len(self.tracks):
            raise ValueError("Track positions must be unique within each disc.")
        return self


class AlbumUpdate(AlbumInput):
    version: int = Field(ge=1)


class MusicListInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
    album_ids: list[UUID] = Field(default_factory=list, max_length=5000)
    version: int | None = Field(default=None, ge=1)


class ExportAlbum(AlbumInput):
    id: UUID
    # Old version-1 files can lack a status; do not invent listening intentions
    # merely because new interactive entries now default to Plan to listen.
    status: MusicStatus = "collected"


class MusicDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["pmt-music-collection"] = "pmt-music-collection"
    version: Literal[1] = 1
    albums: list[ExportAlbum] = Field(max_length=5000)
    lists: list[MusicListInput] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def valid_references(self):
        ids = {row.id for row in self.albums}
        if len(ids) != len(self.albums):
            raise ValueError("Album identifiers must be unique.")
        if any(not set(row.album_ids) <= ids for row in self.lists):
            raise ValueError("A music list refers to an album missing from this file.")
        return self


class MusicImport(BaseModel):
    document: MusicDocument
    sha256: str | None = None
