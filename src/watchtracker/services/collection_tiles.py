"""List-only projections. Detail/edit/export always read the complete record."""

from sqlalchemy import func

from watchtracker.services.collection_artwork import artwork_reference


def tile_projection(statement, model, domain):
    names = (
        "id",
        "version",
        "title",
        "year",
        "status",
        "rating",
        "favorite",
        "completion_count",
        "genres",
        "subgenres",
        "genre_additions",
        "genre_removals",
        "subgenre_additions",
        "subgenre_removals",
        "artwork_url",
        "provider_id",
        "created_at",
        "updated_at",
    )
    names += (
        ("artist", "release_type", "release_group_id")
        if domain == "music"
        else (
            "author",
            "book_format",
            "work_id",
            "current_page",
            "page_count",
        )
    )
    columns = [getattr(model, name) for name in names]
    columns.append(model.artwork_data.is_not(None).label("has_local_artwork"))
    if domain == "music":
        # Both supported database engines compute the count without transferring
        # the track JSON to Python. No redundant stored counter/migration.
        count = func.json_array_length(model.tracks)
        columns.append(count.label("track_count"))
    return statement.with_only_columns(*columns, maintain_column_froms=True)


def tile_output(row, domain):
    result = dict(row._mapping)
    result["cover_url"] = artwork_reference(
        row.id, row.version, row.artwork_url, row.has_local_artwork, domain
    )
    return result
