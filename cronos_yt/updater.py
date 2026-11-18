"""Hash-locked engine updates with verified, private, offline rollback wheels.

A missing or incomplete reviewed lock fails closed.  The explicit unpinned
escape hatch is a user trust decision, not a secure replacement for the lock.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, distribution, version
from pathlib import Path
from typing import Callable

from .settings import state_dir

TRACKED = ("yt-dlp", "yt-dlp-ejs", "rich", "questionary", "mutagen")
UPDATE_SPECS = ("yt-dlp[default]", "yt-dlp-ejs", "rich>=13.7,<16", "questionary>=2,<3", "mutagen>=1.47,<2")
SMOKE_CODE = (
    "import yt_dlp, yt_dlp_ejs, rich, questionary, mutagen, cronos_yt; "
    "from yt_dlp import YoutubeDL; from rich.console import Console; "
    "assert callable(YoutubeDL); assert Console(width=40).width == 40"
)
VERSION_PATTERN = re.compile(r"[0-9][A-Za-z0-9._+!\-]*\Z")
LOCK_NAME = "requirements.lock"


def default_lock_path() -> Path:
    """Support source checkout and installed Termux wheel without cwd assumptions."""
    explicit = os.environ.get("CRONOS_LOCK_FILE")
    if explicit:
        return Path(explicit).expanduser()
    source = Path.home() / "CRONOS" / LOCK_NAME
    if source.is_file():
        return source
    return Path(__file__).resolve().parent / LOCK_NAME


def versions(read_version: Callable[[str], str] = version) -> dict[str, str]:
    result = {}
    for package in TRACKED:
        try:
            result[package] = read_version(package)
        except PackageNotFoundError:
            pass
    return result


def installed_closure(names: tuple[str, ...] = TRACKED) -> dict[str, str]:
    """Inspect the *installed* direct+transitive distributions, never resolve latest.

    Extras may be platform-specific; include every reachable installed optional
    distribution conservatively so a rollback can restore the actual environment.
    """
    work = list(names)
    closure: dict[str, str] = {}
    while work:
        name = work.pop()
        normalized = name.lower().replace("_", "-")
        if normalized in closure:
            continue
        try:
            dist = distribution(name)
        except PackageNotFoundError:
            continue
        real_name = str(dist.metadata.get("Name") or normalized).lower().replace("_", "-")
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", real_name):
            continue
        if not VERSION_PATTERN.fullmatch(dist.version):
            continue
        closure[real_name] = dist.version
        for requirement in dist.requires or ():
            match = re.match(r"[A-Za-z0-9_.-]+", requirement.strip())
            if match:
                candidate = match.group(0).lower().replace("_", "-")
                if candidate not in closure and candidate not in work:
                    work.append(candidate)
    return dict(sorted(closure.items()))

def cache_dir(root: Path | None = None) -> Path:
    """Private app state, never shared with the Android media library."""
    base = root if root is not None else state_dir() / "engine-updates"
    return base.parent / "engine-cache" if root is None else base / "engine-cache"


def snapshot_path(root: Path | None = None) -> Path:
    return (root if root is not None else state_dir() / "engine-updates") / "latest.json"


def _wheel_digests(folder: Path) -> list[dict[str, str]]:
    items = []
    if not folder.is_dir():
        return items
    for path in sorted(folder.glob("*.whl")):
        if path.name != Path(path.name).name or path.is_symlink():
            raise ValueError("Invalid cached wheel")
        path.chmod(0o600)
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        items.append({"filename": path.name, "sha256": digest})
    return items


def _manifest_data(before: dict[str, str], wheels: list[dict[str, str]],
                   environment: dict[str, str] | None = None) -> dict:
    for name, ver in before.items():
        if name not in TRACKED or not isinstance(ver, str) or not VERSION_PATTERN.fullmatch(ver):
            raise ValueError("Unsupported package/version in update snapshot")
    environment = environment or {}
    if not isinstance(environment, dict):
        raise ValueError("Invalid installed-environment snapshot")
    for name, ver in environment.items():
        if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name)
                or not VERSION_PATTERN.fullmatch(ver)):
            raise ValueError("Invalid transitive package in snapshot")
    return {"timestamp": datetime.now(timezone.utc).isoformat(),
            "packages": before, "environment": environment, "wheels": wheels}


def save_snapshot(before: dict[str, str], root: Path | None = None,
                  wheels: list[dict[str, str]] | None = None,
                  environment: dict[str, str] | None = None) -> Path:
    """Atomic 0600 snapshot of exact versions and independently hashed wheels."""
    path = snapshot_path(root)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = _manifest_data(before, wheels or [], environment)
    fd, tmp = tempfile.mkstemp(prefix=".engine-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return path


def _read_manifest(root: Path | None = None) -> dict:
    contents = json.loads(snapshot_path(root).read_text(encoding="utf-8"))
    packages = contents.get("packages")
    if not isinstance(packages, dict) or not packages:
        raise ValueError("No previous package versions available")
    _manifest_data(packages, [], contents.get("environment", {}))  # validate all names/versions
    wheels = contents.get("wheels", [])
    if not isinstance(wheels, list):
        raise ValueError("Invalid wheel manifest")
    for item in wheels:
        if (not isinstance(item, dict) or not isinstance(item.get("filename"), str) or
                not re.fullmatch(r"[A-Za-z0-9_.+\-]+\.whl", item["filename"]) or
                not isinstance(item.get("sha256"), str) or
                not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])):
            raise ValueError("Malformed wheel entry in manifest")
    return contents


def read_snapshot(root: Path | None = None) -> dict[str, str]:
    """Retained for the original CLI/tests; full manifest is read internally."""
    return _read_manifest(root)["packages"]


def verify_wheels(root: Path | None = None) -> bool:
    """Return False if uncached; raise on any present-but-tampered wheel."""
    manifest = _read_manifest(root)
    wheels = manifest.get("wheels", [])
    if not wheels:
        return False
    folder = cache_dir(root) / "rollback"
    expected = {item["filename"] for item in wheels}
    if folder.is_dir():
        for file in folder.iterdir():
            # pip --find-links would otherwise consider unlisted, unverified files.
            if file.name not in expected:
                raise ValueError("Unlisted artifact in rollback cache; refusing restore")
    present = True
    for item in wheels:
        wheel = folder / item["filename"]
        if not wheel.exists():
            present = False
            continue
        if wheel.is_symlink() or not wheel.is_file():
            raise ValueError("Invalid cached wheel type")
        with wheel.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != item["sha256"]:
            raise ValueError("Cached wheel digest mismatch; refusing restore")
    return present


def _invoke(args: list[str]) -> int:
    try:
        return subprocess.run(args, check=False, timeout=900).returncode
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"Package operation failed: {type(exc).__name__}", file=sys.stderr)
        return 1


def smoke_test(run: Callable[[list[str]], int] = _invoke) -> bool:
    return run([sys.executable, "-c", SMOKE_CODE]) == 0


def _pip(*parts: str) -> list[str]:
    return [sys.executable, "-m", "pip", *parts]


def validate_lock(path: Path) -> bool:
    """Check pip-compile style pinned hashes, including wrapped hash lines.

    pip itself verifies the entire transitive closure and artifact digests.
    """
    if not path.is_file():
        return False
    raw = path.read_text(encoding="utf-8")
    # pip-compile wraps hash entries using backslash-newline continuation.
    combined = raw.replace("\\\n", " ")
    actual = [line.split(" #", 1)[0].strip() for line in combined.splitlines()
              if line.strip() and not line.lstrip().startswith("#")]
    # A pip-compile output may include indented 'via' comments; ignore above.
    actual = [line for line in actual if line]
    if not actual:
        return False
    allowed = re.compile(
        r"[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?==[A-Za-z0-9_.+!\-]+"
        r"(?:\s*;\s*[A-Za-z0-9_ .<>=!\"'()-]+)?"
        r"(?:\s+--hash=sha256:[0-9a-f]{64})+"
    )
    for line in actual:
        if not allowed.fullmatch(line):
            return False
    names = {re.split(r"[=\[]", line, 1)[0].lower().replace("_", "-") for line in actual}
    return set(TRACKED).issubset(names)


def _cache_prior(before: dict[str, str], run: Callable[[list[str]], int], root: Path | None,
                 environment: dict[str, str] | None = None) -> list[dict[str, str]] | None:
    folder = cache_dir(root) / "rollback"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Download before changing anything; wheels must be compatible with this device.
    specs = [f"{name}=={ver}" for name, ver in (environment or before).items()]
    if run(_pip("download", "--disable-pip-version-check", "--no-input", "--only-binary=:all:",
                "--dest", str(folder), *specs)) != 0:
        return None
    wheels = _wheel_digests(folder)
    return wheels or None


def rollback(before: dict[str, str], run: Callable[[list[str]], int] = _invoke,
             root: Path | None = None) -> bool:
    if not before:
        return False
    try:
        manifest = _read_manifest(root)
    except (OSError, ValueError, json.JSONDecodeError):
        manifest = {"environment": {}}
    environment = manifest.get("environment") or before
    pinned = [f"{name}=={environment[name]}" for name in sorted(environment)]
    try:
        cached = verify_wheels(root)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"Restore aborted: {exc}", file=sys.stderr)
        return False  # NEVER fall back to index after a digest mismatch.
    if cached:
        result = run(_pip("install", "--disable-pip-version-check", "--no-input",
                          "--force-reinstall", "--only-binary=:all:", "--no-index", "--find-links", str(cache_dir(root) / "rollback"),
                          *pinned))
        if result == 0 and smoke_test(run):
            return True
    print("Verified offline rollback unavailable; trying exact versions from index.", file=sys.stderr)
    result = run(_pip("install", "--disable-pip-version-check", "--no-input", "--force-reinstall", *pinned))
    return result == 0 and smoke_test(run)


def update_engine(run: Callable[[list[str]], int] = _invoke,
                  read_version: Callable[[str], str] = version,
                  root: Path | None = None, *,
                  unpinned: bool = False, yes: bool = False,
                  lock: Path | None = None) -> int:
    """0=healthy update, 1=failed then restored, 2=no safe update/restore."""
    if unpinned and not yes:
        print("Unpinned updates require explicit --update-unpinned --yes.", file=sys.stderr)
        return 2
    pinned_lock = lock or default_lock_path()
    if not unpinned and not validate_lock(pinned_lock):
        print(f"Missing/incomplete reviewed SHA-256 lock: {pinned_lock}. Update refused.", file=sys.stderr)
        return 2
    before = versions(read_version)
    if not before:
        print("No installed engine packages found. Re-run bash install.sh.", file=sys.stderr)
        return 2
    environment = installed_closure()
    # Tests with injected version lookup can omit unknown local distributions;
    # the manifest still captures the actual validated direct set.
    environment.update(before)
    cached = _cache_prior(before, run, root, environment)
    if not cached:
        print("Unable to cache previous engine wheels; update aborted to protect offline rollback.", file=sys.stderr)
        return 2
    manifest = save_snapshot(before, root, cached, environment)
    print(f"Recorded previous engine versions and SHA-256 wheel manifest: {manifest}")
    target = cache_dir(root) / ("target-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f"))
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    if unpinned:
        fetched = run(_pip("download", "--disable-pip-version-check", "--no-input",
                           "--only-binary=:all:", "--dest", str(target), *UPDATE_SPECS))
        if fetched:
            return 2
        print("UNPINNED escape hatch — unreviewed artifacts, exact wheel versions:")
        for item in _wheel_digests(target):
            print("  " + item["filename"] + "  sha256:" + item["sha256"])
        if not list(target.glob("*.whl")):
            return 2
        install = _pip("install", "--disable-pip-version-check", "--no-input", "--upgrade",
                       "--no-index", "--find-links", str(target), *UPDATE_SPECS)
    else:
        fetched = run(_pip("download", "--disable-pip-version-check", "--no-input",
                           "--only-binary=:all:", "--require-hashes", "-r", str(pinned_lock),
                           "--dest", str(target)))
        if fetched:
            return 2
        install = _pip("install", "--disable-pip-version-check", "--no-input",
                       "--require-hashes", "--no-index", "--find-links", str(target),
                       "-r", str(pinned_lock))
    result = run(install)
    if result == 0 and smoke_test(run):
        print("Engine update verified; offline rollback wheel manifest retained.")
        return 0
    print("Engine update failed; attempting verified offline rollback...", file=sys.stderr)
    if rollback(before, run, root):
        return 1
    print("Rollback failed; existing media and SQLite data remain unchanged.", file=sys.stderr)
    return 2


def restore_engine(run: Callable[[list[str]], int] = _invoke, root: Path | None = None) -> int:
    try:
        before = read_snapshot(root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Cannot read update snapshot: {exc}", file=sys.stderr)
        return 2
    if rollback(before, run, root):
        print("Engine restored to the recorded versions.")
        return 0
    print("Restore failed; cached wheels may be unavailable or damaged.", file=sys.stderr)
    return 2
