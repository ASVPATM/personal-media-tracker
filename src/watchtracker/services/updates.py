from __future__ import annotations

import asyncio
import hashlib
import os
import platform
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import httpx
from packaging.version import InvalidVersion, Version

APP_BUNDLE_ID = "com.personalmediatracker.app"
APP_BUNDLE_NAME = "Personal Media Tracker.app"
MAX_UPDATE_BYTES = 1_500_000_000


class UpdateCheckError(RuntimeError):
    pass


class UpdateDownloadError(RuntimeError):
    pass


def _status_template() -> dict[str, Any]:
    return {
        "state": "idle",
        "downloaded_bytes": 0,
        "total_bytes": None,
        "percent": 0,
        "message": "",
        "latest_version": None,
        "ready_to_install": False,
        "error_code": None,
    }


class UpdateService:
    def __init__(
        self,
        repository_url: str,
        current_version: str,
        *,
        client: httpx.AsyncClient | None = None,
        cache_dir: Path | None = None,
        packaged: bool = False,
        platform_name: str | None = None,
        machine: str | None = None,
        app_bundle_path: Path | None = None,
        signature_verifier: Callable[[Path], bool] | None = None,
    ):
        self.repository_url = repository_url.rstrip("/")
        self.current_version = current_version
        self.client = client
        self.cache_dir = Path(cache_dir or Path(tempfile.gettempdir()) / "pmt-updates")
        self.packaged = packaged
        self.platform_name = platform_name or sys.platform
        self.machine = (machine or platform.machine()).lower()
        self.app_bundle_path = app_bundle_path or self._running_bundle_path()
        self.signature_verifier = signature_verifier
        self._release: dict[str, Any] | None = None
        self._asset: dict[str, Any] | None = None
        self._checksum_asset: dict[str, Any] | None = None
        self._status = _status_template()
        self._task: asyncio.Task | None = None
        self._staged_bundle: Path | None = None

    @staticmethod
    def _running_bundle_path() -> Path | None:
        executable = Path(sys.executable).resolve()
        return next((parent for parent in executable.parents if parent.suffix == ".app"), None)

    @property
    def endpoint(self) -> str:
        parts = self.repository_url.split("/")
        if len(parts) < 2:
            raise UpdateCheckError("The update source is not configured correctly.")
        owner, repository = parts[-2:]
        return f"https://api.github.com/repos/{owner}/{repository}/releases/latest"

    @property
    def packaged_macos_bundle(self) -> bool:
        return bool(
            self.packaged
            and self.platform_name == "darwin"
            and self.app_bundle_path
            and self.app_bundle_path.suffix == ".app"
        )

    @property
    def download_supported_runtime(self) -> bool:
        # Never offer self-replacement from an ad-hoc/unsigned build. Gatekeeper
        # would block the incoming bundle and leave the user with a misleading
        # completed download. Signed and notarized builds pass this same check.
        return bool(
            self.packaged_macos_bundle
            and self.app_bundle_path
            and self._verify_signature(self.app_bundle_path)
        )

    def _select_assets(
        self, payload: dict[str, Any], latest: Version
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        assets = payload.get("assets")
        if not isinstance(assets, list):
            return None, None
        architecture = "arm64" if self.machine in {"arm64", "aarch64"} else "x86_64"
        candidates = [
            asset
            for asset in assets
            if isinstance(asset, dict)
            and str(asset.get("name") or "").endswith(".zip")
            and "macOS" in str(asset.get("name") or "")
            and architecture in str(asset.get("name") or "")
            and str(asset.get("browser_download_url") or "").startswith("https://github.com/")
        ]
        if not candidates:
            return None, None
        version_text = str(latest)
        asset = next(
            (item for item in candidates if version_text in str(item.get("name"))),
            candidates[0],
        )
        checksum_names = {
            f"{asset.get('name')}.sha256",
            f"{asset.get('name')}.sha256.txt",
            "SHA256SUMS.txt",
        }
        checksum = next(
            (
                item
                for item in assets
                if isinstance(item, dict)
                and str(item.get("name")) in checksum_names
                and str(item.get("browser_download_url") or "").startswith(
                    "https://github.com/"
                )
            ),
            None,
        )
        return asset, checksum

    @staticmethod
    def _asset_digest(asset: dict[str, Any] | None) -> str | None:
        digest = str((asset or {}).get("digest") or "").lower()
        if digest.startswith("sha256:") and len(digest) == 71:
            value = digest.removeprefix("sha256:")
            if all(character in "0123456789abcdef" for character in value):
                return value
        return None

    async def check(self) -> dict[str, Any]:
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient(
            timeout=httpx.Timeout(8.0, connect=4.0), follow_redirects=False
        )
        try:
            response = await client.get(
                self.endpoint,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": f"personal-media-tracker/{self.current_version}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("response is not an object")
            tag = str(payload.get("tag_name") or "").lstrip("v")
            release_url = str(payload.get("html_url") or "")
            if not tag or not release_url.startswith("https://github.com/"):
                raise ValueError("release fields are missing")
            current = Version(self.current_version)
            latest = Version(tag)
            asset, checksum = self._select_assets(payload, latest)
            self._release = payload
            self._asset = asset
            self._checksum_asset = checksum
            update_available = latest > current and not latest.is_prerelease
            verified_source = bool(self._asset_digest(asset) or checksum)
            download_supported = bool(
                update_available
                and self.download_supported_runtime
                and asset
                and verified_source
            )
            reason = None
            if update_available and not download_supported:
                if not self.packaged_macos_bundle:
                    reason = "Use Open the Release to install this update on your platform."
                elif not self.download_supported_runtime:
                    reason = (
                        "In-app installation is disabled for this unsigned or "
                        "Gatekeeper-unapproved macOS build. Use Open the Release instead."
                    )
                elif not asset:
                    reason = (
                        "A compatible macOS update archive is not attached to this release."
                    )
                elif not verified_source:
                    reason = "The release archive has no SHA-256 verification data."
            return {
                "current_version": str(current),
                "latest_version": str(latest),
                "update_available": update_available,
                "release_url": release_url,
                "download_supported": download_supported,
                "download_unavailable_reason": reason,
            }
        except (httpx.HTTPError, ValueError, InvalidVersion) as exc:
            raise UpdateCheckError(
                "Updates could not be checked. Check your connection and try again."
            ) from exc
        finally:
            if owns_client:
                await client.aclose()

    def status(self) -> dict[str, Any]:
        return dict(self._status)

    async def start_download(self) -> dict[str, Any]:
        if self._task and not self._task.done():
            return self.status()
        checked = await self.check()
        if not checked["update_available"]:
            raise UpdateDownloadError("No newer stable release is available.")
        if not checked["download_supported"] or not self._asset:
            raise UpdateDownloadError(
                checked["download_unavailable_reason"]
                or "This update cannot be installed in the app."
            )
        self._status = {
            **_status_template(),
            "state": "starting",
            "message": "Preparing the verified update download…",
            "latest_version": checked["latest_version"],
        }
        self._task = asyncio.create_task(self._download_and_stage(checked["latest_version"]))
        return self.status()

    async def _download_and_stage(self, latest_version: str) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        updates_dir = self.cache_dir / "updates"
        updates_dir.mkdir(parents=True, exist_ok=True)
        archive = updates_dir / f"pmt-{latest_version}-macos.zip.part"
        archive.unlink(missing_ok=True)
        try:
            expected_hash = self._asset_digest(self._asset) or await self._download_checksum()
            if not expected_hash:
                raise UpdateDownloadError("The update could not be verified with SHA-256.")
            url = str(self._asset["browser_download_url"])
            owns_client = self.client is None
            client = self.client or httpx.AsyncClient(
                timeout=httpx.Timeout(120.0, connect=8.0), follow_redirects=True
            )
            digest = hashlib.sha256()
            downloaded = 0
            try:
                async with client.stream(
                    "GET",
                    url,
                    headers={"User-Agent": f"personal-media-tracker/{self.current_version}"},
                    follow_redirects=True,
                ) as response:
                    response.raise_for_status()
                    header_size = response.headers.get("content-length", "")
                    total = (
                        int(header_size)
                        if header_size.isdigit()
                        else int(self._asset.get("size") or 0)
                    )
                    if total <= 0:
                        total = None
                    if total and total > MAX_UPDATE_BYTES:
                        raise UpdateDownloadError("The update archive is unexpectedly large.")
                    self._status.update(
                        state="downloading",
                        total_bytes=total,
                        message="Downloading the signed macOS update…",
                    )
                    with archive.open("wb") as output:
                        async for chunk in response.aiter_bytes(1024 * 256):
                            downloaded += len(chunk)
                            if downloaded > MAX_UPDATE_BYTES:
                                raise UpdateDownloadError(
                                    "The update archive is unexpectedly large."
                                )
                            output.write(chunk)
                            digest.update(chunk)
                            self._status.update(
                                downloaded_bytes=downloaded,
                                percent=(
                                    min(100, round(downloaded / total * 100)) if total else 0
                                ),
                            )
                    if total and downloaded != total:
                        raise UpdateDownloadError(
                            "The update download ended before it was complete."
                        )
            finally:
                if owns_client:
                    await client.aclose()
            if digest.hexdigest() != expected_hash:
                raise UpdateDownloadError("The update archive failed SHA-256 verification.")
            self._status.update(
                state="verifying", percent=100, message="Verifying the application bundle…"
            )
            staged = self._stage_archive(archive, latest_version)
            self._staged_bundle = staged
            self._status.update(
                state="ready",
                ready_to_install=True,
                message="Update verified. PMT will close, replace the app, and reopen.",
            )
        except Exception as exc:
            message = (
                str(exc)
                if isinstance(exc, UpdateDownloadError)
                else "The update could not be prepared safely."
            )
            self._status.update(
                state="failed",
                ready_to_install=False,
                error_code=type(exc).__name__,
                message=message,
            )
        finally:
            archive.unlink(missing_ok=True)

    async def _download_checksum(self) -> str | None:
        if not self._checksum_asset:
            return None
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0), follow_redirects=True
        )
        try:
            response = await client.get(
                str(self._checksum_asset["browser_download_url"]),
                headers={"User-Agent": f"personal-media-tracker/{self.current_version}"},
                follow_redirects=True,
            )
            response.raise_for_status()
            if len(response.content) > 4096:
                return None
            lines = response.text.strip().splitlines()
            asset_name = str((self._asset or {}).get("name") or "")
            selected = next(
                (
                    line
                    for line in lines
                    if line.strip() and line.strip().split()[-1].lstrip("*") == asset_name
                ),
                lines[0] if len(lines) == 1 else "",
            )
            candidate = selected.strip().split()[0].lower()
            if len(candidate) == 64 and all(value in "0123456789abcdef" for value in candidate):
                return candidate
            return None
        except (httpx.HTTPError, IndexError):
            return None
        finally:
            if owns_client:
                await client.aclose()

    def _stage_archive(self, archive: Path, latest_version: str) -> Path:
        staging_root = Path(
            tempfile.mkdtemp(prefix="pmt-update-", dir=self.cache_dir / "updates")
        )
        try:
            with zipfile.ZipFile(archive) as bundle_zip:
                members = sorted(
                    bundle_zip.infolist(),
                    key=lambda item: stat.S_ISLNK(item.external_attr >> 16),
                )
                if len(members) > 20_000:
                    raise UpdateDownloadError("The update archive contains too many files.")
                extracted_bytes = 0
                for member in members:
                    path = PurePosixPath(member.filename)
                    mode = member.external_attr >> 16
                    extracted_bytes += member.file_size
                    if (
                        not member.filename
                        or path.is_absolute()
                        or ".." in path.parts
                        or extracted_bytes > MAX_UPDATE_BYTES * 2
                    ):
                        raise UpdateDownloadError("The update archive contains an unsafe path.")
                    destination = staging_root.joinpath(*path.parts)
                    if not destination.resolve(strict=False).is_relative_to(
                        staging_root.resolve()
                    ):
                        raise UpdateDownloadError(
                            "The update archive contains an unsafe destination."
                        )
                    if member.is_dir():
                        destination.mkdir(parents=True, exist_ok=True)
                        continue
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if stat.S_ISLNK(mode):
                        target = bundle_zip.read(member).decode("utf-8")
                        target_path = PurePosixPath(target)
                        resolved_target = (destination.parent / target).resolve(strict=False)
                        if (
                            target_path.is_absolute()
                            or len(target) > 4096
                            or not resolved_target.is_relative_to(staging_root.resolve())
                        ):
                            raise UpdateDownloadError(
                                "The update archive contains an unsafe symbolic link."
                            )
                        destination.symlink_to(target)
                        continue
                    with bundle_zip.open(member) as source, destination.open("wb") as output:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
                    if mode:
                        destination.chmod(mode & 0o777)
            candidates = [path for path in staging_root.rglob("*.app") if path.is_dir()]
            if len(candidates) != 1 or candidates[0].name != APP_BUNDLE_NAME:
                raise UpdateDownloadError(
                    "The archive does not contain one expected PMT app bundle."
                )
            bundle = candidates[0]
            info_path = bundle / "Contents" / "Info.plist"
            with info_path.open("rb") as info_file:
                info = plistlib.load(info_file)
            if info.get("CFBundleIdentifier") != APP_BUNDLE_ID:
                raise UpdateDownloadError("The update bundle identifier does not match PMT.")
            bundle_version = str(
                info.get("CFBundleShortVersionString") or info.get("CFBundleVersion") or ""
            )
            if Version(bundle_version) != Version(latest_version):
                raise UpdateDownloadError(
                    "The update bundle version does not match the release."
                )
            if not self._verify_signature(bundle):
                raise UpdateDownloadError("macOS could not verify the update signature.")
            return bundle
        except Exception:
            shutil.rmtree(staging_root, ignore_errors=True)
            raise

    def _verify_signature(self, bundle: Path) -> bool:
        if self.signature_verifier:
            return bool(self.signature_verifier(bundle))
        if self.platform_name != "darwin":
            return False
        try:
            subprocess.run(
                ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(bundle)],
                check=True,
                capture_output=True,
                timeout=30,
            )
            subprocess.run(
                ["/usr/sbin/spctl", "--assess", "--type", "execute", str(bundle)],
                check=True,
                capture_output=True,
                timeout=30,
            )
            return True
        except (OSError, subprocess.SubprocessError):
            return False

    def launch_installer(self, *, current_pid: int | None = None) -> bool:
        if not self._staged_bundle or self._status.get("state") != "ready":
            raise UpdateDownloadError("No verified update is ready to install.")
        target = self.app_bundle_path
        if not target or not target.exists() or target.suffix != ".app":
            raise UpdateDownloadError(
                "The running PMT application bundle could not be located."
            )
        parent = target.parent
        if not os.access(parent, os.W_OK):
            raise UpdateDownloadError(
                "PMT cannot replace the app in this folder. Move it to your Applications folder or use Open the Release."
            )
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        backup = parent / f"{target.stem}.previous-{stamp}.app"
        incoming = parent / f".{target.stem}.updating-{stamp}.app"
        helper_fd, helper_name = tempfile.mkstemp(prefix="pmt-update-helper-", suffix=".sh")
        helper = Path(helper_name)
        script = """#!/bin/sh
set -eu
pid="$1"
staged="$2"
target="$3"
backup="$4"
incoming="$5"
while kill -0 "$pid" 2>/dev/null; do sleep 0.2; done
/usr/bin/ditto "$staged" "$incoming"
/bin/mv "$target" "$backup"
if /bin/mv "$incoming" "$target"; then
  /usr/bin/open "$target"
else
  /bin/mv "$backup" "$target"
  /usr/bin/open "$target"
  exit 1
fi
"""
        with os.fdopen(helper_fd, "w", encoding="utf-8") as file:
            file.write(script)
        helper.chmod(0o700)
        try:
            subprocess.Popen(
                [
                    "/bin/sh",
                    str(helper),
                    str(current_pid or os.getpid()),
                    str(self._staged_bundle),
                    str(target),
                    str(backup),
                    str(incoming),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            helper.unlink(missing_ok=True)
            raise UpdateDownloadError("The update helper could not be started.") from exc
        self._status.update(state="installing", message="Closing PMT to install the update…")
        return True

    async def close(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
