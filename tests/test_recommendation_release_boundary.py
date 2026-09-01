from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

import pytest

from watchtracker import __version__
from watchtracker.build_manifest import parse_build_manifest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "verify_standard_distribution.py"


def _module():
    specification = importlib.util.spec_from_file_location(
        "verify_standard_distribution", SCRIPT
    )
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_standard_source_has_no_advanced_recommendation_runtime():
    assert _module().verify_source(PROJECT_ROOT) == []


def test_standard_pyinstaller_spec_excludes_advanced_runtime_packages():
    text = (PROJECT_ROOT / "packaging" / "watchtracker.spec").read_text(encoding="utf-8")
    assert '"distribution_manifest.json"' in text
    assert '"watchtracker"' in text
    for package in (
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
    ):
        assert f'"{package}"' in text


def test_standard_artifact_scan_rejects_advanced_runtime(tmp_path):
    module = _module()
    clean = tmp_path / "clean.whl"
    blocked = tmp_path / "blocked.whl"
    with zipfile.ZipFile(clean, "w") as archive:
        archive.writestr("watchtracker/recommendations/scalar.py", "")
        archive.writestr(
            "watchtracker/distribution_manifest.json",
            '{"application":"personal-media-tracker","base_version":"2.6.1",'
            '"distribution_flavor":"standard","recommendation_capabilities":'
            '["scalar-v1"],"advanced_pack_version":null}',
        )
    with zipfile.ZipFile(blocked, "w") as archive:
        archive.writestr("sentence_transformers/__init__.py", "")
        archive.writestr(
            "watchtracker/distribution_manifest.json",
            '{"application":"personal-media-tracker","base_version":"2.6.1",'
            '"distribution_flavor":"standard","recommendation_capabilities":'
            '["scalar-v1"],"advanced_pack_version":null}',
        )

    assert module.verify_artifact(clean) == []
    assert "forbidden path" in module.verify_artifact(blocked)[0]


def test_standard_artifact_scan_rejects_private_flow_and_advanced_manifest(tmp_path):
    module = _module()
    artifact = tmp_path / "wrong.whl"
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("tools/pmt_flow/dashboard.py", "")
        archive.writestr(
            "watchtracker/distribution_manifest.json",
            '{"application":"personal-media-tracker","base_version":"2.6.1",'
            '"distribution_flavor":"recommendations-beta","recommendation_capabilities":'
            '["scalar-v1","advanced-hybrid-v1"],"advanced_pack_version":"beta.1"}',
        )

    failures = module.verify_artifact(artifact)
    assert any("private or Advanced-only" in failure for failure in failures)
    assert any("distribution_flavor" in failure for failure in failures)


def test_standard_artifact_scan_accepts_packaged_directory(tmp_path):
    module = _module()
    package = tmp_path / "Personal Media Tracker.app" / "Contents" / "Resources"
    manifest = package / "watchtracker" / "distribution_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        '{"application":"personal-media-tracker","base_version":"2.6.1",'
        '"distribution_flavor":"standard","recommendation_capabilities":'
        '["scalar-v1"],"advanced_pack_version":null}',
        encoding="utf-8",
    )
    (package / "watchtracker" / "app.pyc").write_bytes(b"standard")

    assert module.verify_artifact(tmp_path / "Personal Media Tracker.app") == []


@pytest.mark.parametrize(
    ("changes", "valid"),
    [
        ({}, True),
        ({"recommendation_capabilities": ["scalar-v1", "advanced-hybrid-v1"]}, False),
        ({"advanced_pack_version": "unexpected"}, False),
        ({"recommendation_capabilities": ["scalar-v1", "scalar-v1"]}, False),
        ({"distribution_flavor": "unknown"}, False),
    ],
)
def test_standard_build_manifest_fails_closed(changes, valid):
    payload = {
        "application": "personal-media-tracker",
        "base_version": __version__,
        "distribution_flavor": "standard",
        "recommendation_capabilities": ["scalar-v1"],
        "advanced_pack_version": None,
        **changes,
    }
    if valid:
        assert parse_build_manifest(payload).distribution_flavor == "standard"
    else:
        with pytest.raises(RuntimeError):
            parse_build_manifest(payload)
