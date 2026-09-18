from __future__ import annotations

import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from watchtracker.music.schemas import CollectionInput, Label

EditionId = Annotated[str, StringConstraints(pattern=r"^OL[0-9]+M$", max_length=30)]
WorkId = Annotated[str, StringConstraints(pattern=r"^OL[0-9]+W$", max_length=30)]
BookStatus = Literal["collected", "reading", "read", "plan_to_read"]


class BookInput(CollectionInput):
    author: Label
    book_format: Literal["book", "paperback", "hardcover", "ebook", "other"] = "book"
    # Legacy "collected" remains accepted only for data/API compatibility.
    status: BookStatus = "plan_to_read"
    description: str = Field(default="", max_length=20000)
    publisher: str = Field(default="", max_length=500)
    isbn: str | None = Field(default=None, max_length=30)
    page_count: int | None = Field(default=None, ge=1, le=100000)
    current_page: int | None = Field(default=None, ge=0, le=100000)
    provider_id: EditionId | None = None
    work_id: WorkId | None = None
    chapters: list[Label] = Field(default_factory=list, max_length=1000)

    @field_validator("isbn")
    @classmethod
    def isbn_format(cls, value):
        if not value:
            return None
        value = re.sub(r"[\s-]", "", value).upper()
        valid = False
        if re.fullmatch(r"\d{9}[\dX]", value):
            valid = (
                sum(
                    (10 - i) * (10 if digit == "X" else int(digit))
                    for i, digit in enumerate(value)
                )
                % 11
                == 0
            )
        elif re.fullmatch(r"\d{13}", value):
            valid = (
                sum(int(digit) * (1 if i % 2 == 0 else 3) for i, digit in enumerate(value)) % 10
                == 0
            )
        if not valid:
            raise ValueError("Enter a valid ISBN-10 or ISBN-13, or leave it blank.")
        return value

    @model_validator(mode="after")
    def progress_bounds(self):
        if (
            self.page_count is not None
            and self.current_page is not None
            and self.current_page > self.page_count
        ):
            raise ValueError("Current page cannot exceed the page count.")
        return self


class BookUpdate(BookInput):
    version: int = Field(ge=1)


class BookListInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
    book_ids: list[UUID] = Field(default_factory=list, max_length=5000)
    version: int | None = Field(default=None, ge=1)


class ExportBook(BookInput):
    id: UUID
    # Missing status in an older import is unknown, not evidence of a new plan.
    status: BookStatus = "collected"


class BookDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["pmt-book-collection"] = "pmt-book-collection"
    version: Literal[1] = 1
    books: list[ExportBook] = Field(max_length=5000)
    lists: list[BookListInput] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def references(self):
        ids = {row.id for row in self.books}
        if len(ids) != len(self.books) or any(
            not set(row.book_ids) <= ids for row in self.lists
        ):
            raise ValueError(
                "Book identifiers must be unique and list references must exist in this file."
            )
        return self


class BookImport(BaseModel):
    document: BookDocument
    sha256: str | None = None
