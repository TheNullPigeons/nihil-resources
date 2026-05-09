"""Shared helpers for nihil-resources scripts (sync.py, update.py)."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tarfile
import tempfile
import tomllib
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

# Repository layout
REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = REPO_ROOT / "catalog" / "resources.toml"
PROFILES_PATH = REPO_ROOT / "catalog" / "profiles.toml"
CSV_PATH = REPO_ROOT / "resources_list.csv"

# Supported kinds in the catalog
KIND_URL = "url"
KIND_RELEASE_ASSET = "release_asset"
KIND_SUBMODULE = "submodule"
SUPPORTED_KINDS = frozenset({KIND_URL, KIND_RELEASE_ASSET, KIND_SUBMODULE})

# Kinds handled by sync.py at user time vs. update.py at maintainer time
USER_FETCH_KINDS = frozenset({KIND_URL})
MAINTAINER_KINDS = frozenset({KIND_URL, KIND_RELEASE_ASSET, KIND_SUBMODULE})

USER_AGENT = "nihil-resources-updater"


class CatalogError(Exception):
    """Raised when the catalog is invalid or an operation fails."""


# ---------------------------------------------------------------------------
# TOML loading
# ---------------------------------------------------------------------------

def load_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def load_profiles() -> dict[str, dict]:
    raw = load_toml(PROFILES_PATH)
    profiles = raw.get("profile", {})
    if not profiles:
        raise CatalogError(f"No profiles found in {PROFILES_PATH}")
    return profiles


def load_resources() -> list[dict]:
    raw = load_toml(CATALOG_PATH)
    resources = raw.get("resource", [])
    if not isinstance(resources, list):
        raise CatalogError(f"Invalid resource list in {CATALOG_PATH}")
    return resources


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def is_safe_relative_target(target: str) -> bool:
    path = Path(target)
    return not path.is_absolute() and ".." not in path.parts


def validate_catalog(resources: list[dict], profiles: dict[str, dict]) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    known_profiles = set(profiles)

    for index, resource in enumerate(resources, start=1):
        label = resource.get("id") or f"resource#{index}"
        rid = resource.get("id")
        target = resource.get("target")
        kind = resource.get("kind")
        rprofiles = resource.get("profiles", [])
        sha256 = (resource.get("sha256") or "").strip()

        if not rid:
            errors.append(f"{label}: missing 'id'")
        elif rid in seen_ids:
            errors.append(f"{label}: duplicate id")
        else:
            seen_ids.add(rid)

        if not target or not is_safe_relative_target(target):
            errors.append(f"{label}: invalid relative target '{target}'")

        if kind not in SUPPORTED_KINDS:
            errors.append(f"{label}: unsupported kind '{kind}' (allowed: {sorted(SUPPORTED_KINDS)})")
        else:
            errors.extend(_kind_specific_errors(label, kind, resource))

        if not isinstance(rprofiles, list) or not rprofiles:
            errors.append(f"{label}: missing profiles")
        else:
            unknown = sorted(set(rprofiles) - known_profiles)
            if unknown:
                errors.append(f"{label}: unknown profiles: {', '.join(unknown)}")

        if sha256 and len(sha256) != 64:
            errors.append(f"{label}: sha256 must be 64 hex chars when set")

    return errors


def _kind_specific_errors(label: str, kind: str, r: dict) -> list[str]:
    errors: list[str] = []
    if kind == KIND_URL:
        if not r.get("url"):
            errors.append(f"{label}: missing 'url' for kind=url")
    elif kind == KIND_RELEASE_ASSET:
        if not r.get("github"):
            errors.append(f"{label}: missing 'github' (owner/repo) for kind=release_asset")
        if not r.get("asset_pattern"):
            errors.append(f"{label}: missing 'asset_pattern' (regex) for kind=release_asset")
    elif kind == KIND_SUBMODULE:
        if not r.get("repo"):
            errors.append(f"{label}: missing 'repo' for kind=submodule")
    return errors


# ---------------------------------------------------------------------------
# Filtering / printing
# ---------------------------------------------------------------------------

def filter_resources(
    resources: list[dict],
    *,
    profile: str | None = None,
    category: str | None = None,
    kinds: frozenset[str] | None = None,
    enabled_only: bool = False,
    ids: list[str] | None = None,
) -> list[dict]:
    selected = resources
    if profile:
        selected = [r for r in selected if profile in r.get("profiles", [])]
    if category:
        selected = [r for r in selected if r.get("category") == category]
    if kinds is not None:
        selected = [r for r in selected if r.get("kind") in kinds]
    if enabled_only:
        selected = [r for r in selected if bool(r.get("enabled"))]
    if ids:
        wanted = set(ids)
        selected = [r for r in selected if r.get("id") in wanted]
    return selected


# ---------------------------------------------------------------------------
# Networking
# ---------------------------------------------------------------------------

def http_get(url: str, *, accept: str = "*/*") -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    try:
        with urllib.request.urlopen(request) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise CatalogError(f"HTTP {exc.code} on {url}") from exc
    except urllib.error.URLError as exc:
        raise CatalogError(f"Network error on {url}: {exc.reason}") from exc


def download_url(url: str, destination: Path, *, expected_sha256: str = "") -> None:
    """Download `url` to `destination` atomically. Verify sha256 if provided."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        delete=False,
        dir=destination.parent,
        prefix=f".{destination.name}.",
    ) as tmp_handle:
        tmp_path = Path(tmp_handle.name)
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request) as response, tmp_path.open("wb") as handle:
            shutil.copyfileobj(response, handle)
        if expected_sha256:
            actual = compute_sha256(tmp_path)
            if actual.lower() != expected_sha256.lower():
                raise CatalogError(
                    f"sha256 mismatch on {url} (expected {expected_sha256}, got {actual})"
                )
        tmp_path.replace(destination)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# GitHub release helpers
# ---------------------------------------------------------------------------

_GITHUB_REPO_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")


def resolve_release_asset(github_repo: str, asset_pattern: str) -> tuple[str, str]:
    """Return (asset_name, download_url) of the first asset of the latest
    release of `owner/repo` matching the regex `asset_pattern`."""
    if not _GITHUB_REPO_RE.match(github_repo):
        raise CatalogError(f"Invalid github repo identifier: {github_repo!r}")
    api = f"https://api.github.com/repos/{github_repo}/releases/latest"
    payload = http_get(api, accept="application/vnd.github+json")
    data = json.loads(payload)
    pattern = re.compile(asset_pattern)
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if pattern.search(name):
            return name, asset["browser_download_url"]
    raise CatalogError(
        f"No asset matching /{asset_pattern}/ in latest release of {github_repo} "
        f"(release: {data.get('tag_name', '?')})"
    )


# ---------------------------------------------------------------------------
# Archive extraction
# ---------------------------------------------------------------------------

def extract_archive(archive_path: Path, destination_dir: Path) -> None:
    destination_dir.mkdir(parents=True, exist_ok=True)
    name = archive_path.name.lower()
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive_path) as zf:
            for member in zf.namelist():
                # Block path traversal in zip members
                resolved = (destination_dir / member).resolve()
                if not str(resolved).startswith(str(destination_dir.resolve())):
                    raise CatalogError(f"Unsafe zip member path: {member}")
            zf.extractall(destination_dir)
    elif name.endswith((".tar.gz", ".tgz", ".tar.bz2", ".tar.xz", ".tar")):
        with tarfile.open(archive_path) as tf:
            for member in tf.getmembers():
                resolved = (destination_dir / member.name).resolve()
                if not str(resolved).startswith(str(destination_dir.resolve())):
                    raise CatalogError(f"Unsafe tar member path: {member.name}")
            tf.extractall(destination_dir)
    else:
        raise CatalogError(f"Unsupported archive format: {archive_path.name}")


# ---------------------------------------------------------------------------
# Git submodule helpers
# ---------------------------------------------------------------------------

def run_git(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        check=check,
        capture_output=True,
        text=True,
    )


def submodule_is_declared(path: str) -> bool:
    gitmodules = REPO_ROOT / ".gitmodules"
    if not gitmodules.is_file():
        return False
    needle = f"path = {path}"
    return any(line.strip() == needle for line in gitmodules.read_text(encoding="utf-8").splitlines())


def ensure_submodule(repo_url: str, target_path: str, branch: str = "") -> str:
    """Add the submodule if absent, otherwise update it to remote tip.

    Returns a one-line action string for the caller to print/log.
    """
    if submodule_is_declared(target_path):
        try:
            run_git("submodule", "update", "--init", "--remote", "--merge", "--", target_path, cwd=REPO_ROOT)
        except subprocess.CalledProcessError as exc:
            raise CatalogError(
                f"git submodule update failed for {target_path}: {exc.stderr.strip()}"
            ) from exc
        return f"updated submodule {target_path}"
    add_args = ["submodule", "add"]
    if branch:
        add_args += ["-b", branch]
    add_args += [repo_url, target_path]
    try:
        run_git(*add_args, cwd=REPO_ROOT)
    except subprocess.CalledProcessError as exc:
        raise CatalogError(
            f"git submodule add failed for {target_path}: {exc.stderr.strip()}"
        ) from exc
    return f"added submodule {target_path} -> {repo_url}"
