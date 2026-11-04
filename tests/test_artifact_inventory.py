import hashlib
import importlib.util
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "inventory_artifacts", Path(__file__).parents[1] / "scripts/inventory_artifacts.py"
)
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


def fixture(tmp_path, monkeypatch):
    root = (tmp_path / "project").resolve()
    root.mkdir()
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    (root / ".gitignore").write_text("build/\ndist/\nrelease/\n.pmt-flow/\n")
    (root / "build").mkdir()
    for number in range(4):
        path = root / "build" / f"build-{number}"
        path.mkdir()
        (path / "Analysis-00.toc").write_text("synthetic")
        stamp = time.time() - (40 - number) * 86400
        os.utime(path, (stamp, stamp))
    monkeypatch.setattr(inventory, "active_build", lambda: False)
    recovery = tmp_path.resolve() / "recovery"
    return root, recovery


def test_inventory_is_report_only_and_archive_is_recoverable(tmp_path, monkeypatch):
    root, recovery = fixture(tmp_path, monkeypatch)
    report = inventory.inventory(root, recovery)
    candidates = [row for row in report["entries"] if row["decision"] == "candidate"]
    assert len(candidates) == 2 and not recovery.exists()
    manifest = tmp_path / "reviewed.json"
    manifest.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="digest"):
        inventory.archive(manifest, "wrong", root)
    approval = hashlib.sha256(manifest.read_bytes()).hexdigest()
    moved = inventory.archive(manifest, approval, root)
    assert len(moved) == 2
    assert len(list((root / "build").iterdir())) == 2
    assert all(Path(row["recovery"]).is_dir() for row in moved)
    assert (recovery / "recovery-receipt.json").exists()


def test_inventory_protects_data_symlinks_references_and_changed_artifacts(
    tmp_path, monkeypatch
):
    root, recovery = fixture(tmp_path, monkeypatch)
    oldest = root / "build/build-0"
    (oldest / "watchtracker.sqlite3").write_bytes(b"private")
    flow = root / ".pmt-flow/old-capture"
    flow.mkdir(parents=True)
    (flow / "trace.zip").write_bytes(b"irreplaceable")
    report = inventory.inventory(root, recovery)
    assert all(
        row["decision"] == "keep"
        for row in report["entries"]
        if row["path"] in {str(flow), str(oldest)}
    )
    candidate = next(row for row in report["entries"] if row["decision"] == "candidate")
    manifest = tmp_path / "reviewed.json"
    manifest.write_text(json.dumps(report))
    (Path(candidate["path"]) / "new-data").write_text("keep this")
    with pytest.raises(ValueError, match="changed"):
        inventory.archive(manifest, hashlib.sha256(manifest.read_bytes()).hexdigest(), root)
    assert not recovery.exists()
    with pytest.raises(ValueError):
        inventory.validate(root, root / "src")
    linked = root / "build/linked"
    linked.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        inventory.validate(root, linked)
