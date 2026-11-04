"""Report-only artifact inventory, with explicit, recoverable manifest archiving.

Never run automatically at startup/build time. A human must review the manifest
and supply its SHA-256 before --archive will move even one generated directory.
Unknown Flow evidence is protected, not assumed resolved because it is old.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

ROOTS = ("build", "dist", "release", ".pmt-flow", ".project-flow", ".private")
PROTECTED = (".sqlite3", ".sqlite3-wal", ".sqlite3-shm", ".db", ".db-wal", ".db-shm")


def active_build():
    try:
        # Never print process arguments, which may contain unrelated secrets.
        result = subprocess.run(
            ["ps", "-axo", "args"], capture_output=True, text=True, check=True
        )
        return any(
            "pyinstaller" in line.lower() and "inventory_artifacts" not in line
            for line in result.stdout.splitlines()
        )
    except (OSError, subprocess.CalledProcessError):
        return True


def fingerprint(path):
    """No symlink traversal; include every filename, size and mtime in the digest."""
    rows, protected = [], []
    if path.name.endswith(PROTECTED) or path.name in {
        ".env",
        "secrets.env",
        "profile",
        "uploads",
        "exports",
        "backups",
    }:
        protected.append("personal data or backup")
    for directory, folders, files in os.walk(path, followlinks=False):
        for name in [*folders, *files]:
            item = Path(directory) / name
            if item.is_symlink():
                protected.append("symlink")
                continue
            info = item.stat()
            rows.append(
                (
                    str(item.relative_to(path)),
                    info.st_size if item.is_file() else 0,
                    info.st_mtime_ns,
                )
            )
            if name.endswith(PROTECTED) or name in {
                ".env",
                "secrets.env",
                "profile",
                "uploads",
                "exports",
                "backups",
            }:
                protected.append("personal data or backup")
    if path.is_file():
        info = path.stat()
        rows.append((path.name, info.st_size, info.st_mtime_ns))
    digest = hashlib.sha256(json.dumps(sorted(rows)).encode()).hexdigest()
    return {
        "bytes": sum(row[1] for row in rows),
        "fingerprint": digest,
        "mtime_ns": path.stat().st_mtime_ns,
        "protected": sorted(set(protected)),
    }


def validate(root, path):
    if not path.is_absolute() or path.is_symlink() or path.resolve() != path:
        raise ValueError("Unresolved path or symlink in manifest")
    relative = path.relative_to(root)
    if len(relative.parts) != 2 or relative.parts[0] not in ROOTS:
        raise ValueError("Only explicitly inventoried generated-directory children are allowed")
    return relative


def inventory(root, destination):
    root, destination = root.resolve(), destination.resolve()
    if destination == root or root in destination.parents:
        raise ValueError("Recovery directory must be outside the project")
    active = active_build()
    references = []
    # Plans/handoffs are small text only; evidence, databases and secrets are never read.
    for path in [*root.glob("*handoff*.md"), *(root / ".private").glob("*.md")]:
        if not path.is_symlink() and path.stat().st_size < 2 * 1024 * 1024:
            references.append((str(path.relative_to(root)), path.read_text(errors="replace")))
    rows = []
    for category in ROOTS:
        directory = root / category
        if not directory.is_dir() or directory.is_symlink():
            continue
        children = sorted(
            (p for p in directory.iterdir() if not p.is_symlink()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        def version(path):
            match = re.search(r"(?:-v|-)(\d+)\.(\d+)\.(\d+)(?:[.-]|$)", path.name)
            return tuple(map(int, match.groups())) if match else None

        retained_versions = set(
            sorted({v for p in children if (v := version(p))}, reverse=True)[:2]
        )
        for index, path in enumerate(children):
            info = fingerprint(path)
            relative = validate(root, path)
            refs = [
                name for name, text in references if str(relative) in text or str(path) in text
            ]
            age = (time.time() - path.stat().st_mtime) / 86400
            reason = "private evidence or document: resolution/pinning must be reviewed"
            decision = "keep"
            if category in {"build", "dist", "release"}:
                reason = "retain two newest sets and all referenced, active or data-bearing artifacts"
                known = (
                    (path.is_dir() and any(path.rglob("Analysis-00.toc")))
                    if category == "build"
                    else bool(version(path))
                    and path.name.startswith(
                        ("Personal-Media-Tracker-", "personal_media_tracker-", "SHA256SUMS-")
                    )
                )
                keep_version = category != "build" and version(path) in retained_versions
                if (
                    known
                    and not keep_version
                    and index >= 2
                    and age > 7
                    and not refs
                    and not info["protected"]
                    and not active
                ):
                    decision, reason = (
                        "candidate",
                        "superseded generated artifact; owner approval required",
                    )
            ignored = (
                subprocess.run(
                    ["git", "check-ignore", "--quiet", str(relative)], cwd=root, check=False
                ).returncode
                == 0
            )
            if not ignored:
                decision, reason = "keep", "tracked or not ignored"
            rows.append(
                {
                    "path": str(path),
                    "category": category,
                    **info,
                    "age_days": round(age, 1),
                    "references": refs,
                    "decision": decision,
                    "reason": reason,
                    "recovery": str(destination / relative),
                }
            )
    return {
        "schema": 1,
        "root": str(root),
        "created": datetime.now(UTC).isoformat(),
        "recovery_root": str(destination),
        "entries": rows,
    }


def archive(manifest_path, approval, root):
    raw = manifest_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != approval:
        raise ValueError("Approval digest does not match this exact reviewed manifest")
    manifest = json.loads(raw)
    if manifest.get("schema") != 1 or manifest["root"] != str(root.resolve()):
        raise ValueError("Manifest belongs to another repository")
    if active_build():
        raise ValueError("A build may be active; archive only after it completes")
    recovery = Path(manifest["recovery_root"])
    if recovery.resolve() != recovery or recovery == root or root in recovery.parents:
        raise ValueError("Unsafe recovery destination")
    candidates = [row for row in manifest["entries"] if row["decision"] == "candidate"]
    # Validate the complete set before any move; source changes require a new report.
    for row in candidates:
        path = Path(row["path"])
        relative = validate(root, path)
        if (
            relative.parts[0] not in {"build", "dist", "release"}
            or row["references"]
            or row["protected"]
        ):
            raise ValueError("Protected evidence cannot be archived by this helper")
        fresh = fingerprint(path)
        if any(
            fresh[key] != row[key] for key in ("bytes", "fingerprint", "mtime_ns", "protected")
        ):
            raise ValueError(f"Artifact changed since inspection: {path}")
        if (
            Path(row["recovery"]) != recovery / relative
            or Path(row["recovery"]).exists()
            or Path(row["recovery"]).parent.resolve() != Path(row["recovery"]).parent
        ):
            raise ValueError("Recovery path differs or already exists")
        if subprocess.run(
            ["git", "check-ignore", "--quiet", str(relative)], cwd=root, check=False
        ).returncode:
            raise ValueError("Artifact is no longer ignored")
    moved = []
    for row in candidates:
        target = Path(row["recovery"])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(row["path"], target)
        moved.append({"from": row["path"], "recovery": str(target)})
        # Persist recovery receipts after each move, including partial runs.
        (recovery / "recovery-receipt.json").write_text(json.dumps(moved, indent=2))
    return moved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--recovery", type=Path)
    parser.add_argument("--archive", type=Path, help="An already-reviewed JSON manifest")
    parser.add_argument("--approve-sha256")
    args = parser.parse_args()
    if args.archive:
        print(
            json.dumps(
                archive(args.archive, args.approve_sha256, args.root.resolve()), indent=2
            )
        )
        return
    if not args.recovery:
        parser.error(
            "Provide an external --recovery directory (reporting creates nothing there)"
        )
    result = json.dumps(inventory(args.root, args.recovery), indent=2)
    if args.output:
        args.output.write_text(result)
        print(
            f"Report only: {args.output}\nSHA-256: {hashlib.sha256(result.encode()).hexdigest()}"
        )
    else:
        print(result)


if __name__ == "__main__":
    main()
