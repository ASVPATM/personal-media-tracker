from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError


class BackgroundImageError(ValueError):
    pass


class BackgroundImageStore:
    """Device-local workspace artwork, deliberately excluded from exports."""

    max_pixels = 40_000_000
    max_width = 3840
    max_height = 2160

    def __init__(self, config_dir: Path):
        self.path = config_dir / "workspace-background.webp"

    @property
    def available(self) -> bool:
        return self.path.is_file()

    @property
    def version(self) -> str | None:
        if not self.available:
            return None
        stat = self.path.stat()
        return f"{stat.st_mtime_ns:x}-{stat.st_size:x}"

    def save(self, content: bytes) -> dict[str, str | int | bool | None]:
        if not content:
            raise BackgroundImageError("Choose a non-empty image file.")
        try:
            with Image.open(BytesIO(content)) as source:
                source.verify()
            with Image.open(BytesIO(content)) as source:
                if source.width * source.height > self.max_pixels:
                    raise BackgroundImageError(
                        "That image is too large after decoding. Choose one under 40 megapixels."
                    )
                image = ImageOps.exif_transpose(source)
                image.thumbnail((self.max_width, self.max_height), Image.Resampling.LANCZOS)
                converted = image.convert("RGBA" if image.mode in {"RGBA", "LA"} else "RGB")
                self.path.parent.mkdir(parents=True, exist_ok=True)
                descriptor, temporary_name = tempfile.mkstemp(
                    prefix=".workspace-background-", suffix=".webp", dir=self.path.parent
                )
                os.close(descriptor)
                try:
                    converted.save(temporary_name, "WEBP", quality=88, method=6)
                    os.chmod(temporary_name, 0o600)
                    os.replace(temporary_name, self.path)
                    os.chmod(self.path, 0o600)
                except Exception:
                    with suppress(OSError):
                        os.unlink(temporary_name)
                    raise
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
            raise BackgroundImageError(
                "PMT could not read that image. Choose a valid PNG, JPEG, or WebP file."
            ) from exc
        return self.status()

    def delete(self) -> None:
        with suppress(FileNotFoundError):
            self.path.unlink()

    def status(self) -> dict[str, str | int | bool | None]:
        return {
            "available": self.available,
            "version": self.version,
            "size": self.path.stat().st_size if self.available else 0,
        }
