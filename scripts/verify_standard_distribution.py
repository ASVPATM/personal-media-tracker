from __future__ import annotations

import argparse
import json
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

FORBIDDEN_DEPENDENCIES = {
    "joblib",
    "numpy",
    "pandas",
    "pgvector",
    "polars",
    "scikit-learn",
    "scipy",
    "sentence-transformers",
    "streamlit",
    "tensorflow",
    "torch",
}
FORBIDDEN_IMPORT_FRAGMENTS = (
    "from recsys",
    "import recsys",
    "from recommendationsys",
    "import recommendationsys",
    "import joblib",
    "from joblib",
    "import numpy",
    "from numpy",
    "import pandas",
    "from pandas",
    "import pgvector",
    "from pgvector",
    "import polars",
    "from polars",
    "import scipy",
    "from scipy",
    "import sentence_transformers",
    "from sentence_transformers",
    "import sklearn",
    "from sklearn",
    "import streamlit",
    "from streamlit",
    "import tensorflow",
    "from tensorflow",
    "import torch",
    "from torch",
)
FORBIDDEN_ARCHIVE_PARTS = {
    ".private",
    "joblib",
    "numpy",
    "pandas",
    "pgvector",
    "polars",
    "recsys",
    "scipy",
    "sentence_transformers",
    "sklearn",
    "streamlit",
    "tensorflow",
    "torch",
}
FORBIDDEN_ARCHIVE_FRAGMENTS = (
    "pmt-flow",
    "pmt_flow",
    "recommendation_system_implementation_plan",
    "recommender_advanced",
)
EXPECTED_STANDARD_MANIFEST = {
    "application": "personal-media-tracker",
    "distribution_flavor": "standard",
    "recommendation_capabilities": ["scalar-v1"],
    "advanced_pack_version": None,
}


def _dependency_name(requirement: str) -> str:
    value = requirement.split(";", 1)[0].strip()
    for marker in ("[", "<", ">", "=", "!", "~", " "):
        value = value.split(marker, 1)[0]
    return value.casefold().replace("_", "-")


def verify_source(root: Path) -> list[str]:
    failures: list[str] = []
    document = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = {
        _dependency_name(value) for value in document["project"].get("dependencies", [])
    }
    forbidden = sorted(dependencies & FORBIDDEN_DEPENDENCIES)
    if forbidden:
        failures.append(f"Standard runtime dependencies include: {', '.join(forbidden)}")

    manifest_path = root / "src" / "watchtracker" / "distribution_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        failures.append(f"Standard build manifest cannot be read: {type(exc).__name__}")
    else:
        for field, expected in EXPECTED_STANDARD_MANIFEST.items():
            if manifest.get(field) != expected:
                failures.append(f"Standard build manifest has invalid {field!r}")

    for path in sorted((root / "src" / "watchtracker").rglob("*.py")):
        content = path.read_text(encoding="utf-8")
        for fragment in FORBIDDEN_IMPORT_FRAGMENTS:
            if fragment in content:
                failures.append(
                    f"{path.relative_to(root)} imports forbidden Standard code: {fragment}"
                )
    return failures


def _archive_names(path: Path) -> list[str]:
    if path.is_dir():
        return [item.relative_to(path).as_posix() for item in path.rglob("*") if item.is_file()]
    if path.suffix == ".whl" or path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            return archive.namelist()
    if path.name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(path, "r:gz") as archive:
            return archive.getnames()
    raise ValueError(f"Unsupported artifact format: {path}")


def _archive_manifest(path: Path) -> dict | None:
    if path.is_dir():
        matches = [
            item
            for item in path.rglob("distribution_manifest.json")
            if item.parent.name == "watchtracker"
        ]
        if len(matches) != 1:
            return None
        return json.loads(matches[0].read_text(encoding="utf-8"))
    if path.suffix in {".whl", ".zip"}:
        with zipfile.ZipFile(path) as archive:
            names = [
                name
                for name in archive.namelist()
                if name.endswith("watchtracker/distribution_manifest.json")
            ]
            if len(names) != 1:
                return None
            return json.loads(archive.read(names[0]).decode("utf-8"))
    if path.name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(path, "r:gz") as archive:
            members = [
                member
                for member in archive.getmembers()
                if member.name.endswith("src/watchtracker/distribution_manifest.json")
                or member.name.endswith("watchtracker/distribution_manifest.json")
            ]
            if len(members) != 1:
                return None
            handle = archive.extractfile(members[0])
            if handle is None:
                return None
            return json.loads(handle.read().decode("utf-8"))
    return None


def verify_artifact(path: Path) -> list[str]:
    failures: list[str] = []
    for name in _archive_names(path):
        parts = {part.casefold() for part in Path(name).parts}
        blocked = sorted(parts & FORBIDDEN_ARCHIVE_PARTS)
        if blocked:
            failures.append(
                f"{path.name} contains forbidden path {name} ({', '.join(blocked)})"
            )
        folded = name.casefold()
        if fragment := next(
            (item for item in FORBIDDEN_ARCHIVE_FRAGMENTS if item in folded), None
        ):
            failures.append(
                f"{path.name} contains private or Advanced-only path {name} ({fragment})"
            )
    try:
        manifest = _archive_manifest(path)
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
        failures.append(f"{path.name} has an unreadable build manifest: {type(exc).__name__}")
        manifest = None
    if manifest is None:
        failures.append(f"{path.name} does not contain exactly one build manifest")
    else:
        for field, expected in EXPECTED_STANDARD_MANIFEST.items():
            if manifest.get(field) != expected:
                failures.append(f"{path.name} has invalid Standard manifest field {field!r}")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prove that PMT Standard contains no Advanced recommendation runtime"
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("artifacts", nargs="*", type=Path)
    arguments = parser.parse_args(argv)
    failures = verify_source(arguments.root.resolve())
    for artifact in arguments.artifacts:
        failures.extend(verify_artifact(artifact.resolve()))
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1
    print("PMT Standard recommendation boundary verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
