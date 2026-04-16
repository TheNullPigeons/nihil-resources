#!/usr/bin/env python3
"""Validate, list, and optionally sync nihil-resources catalog entries."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tempfile
import tomllib
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = REPO_ROOT / "catalog" / "resources.toml"
PROFILES_PATH = REPO_ROOT / "catalog" / "profiles.toml"


class CatalogError(Exception):
    """Raised when the catalog is invalid."""


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


def is_safe_relative_target(target: str) -> bool:
    path = Path(target)
    return not path.is_absolute() and ".." not in path.parts


def validate_catalog(resources: list[dict], profiles: dict[str, dict]) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    known_profiles = set(profiles)

    for index, resource in enumerate(resources, start=1):
        label = resource.get("id", f"resource#{index}")
        resource_id = resource.get("id")
        target = resource.get("target")
        kind = resource.get("kind")
        resource_profiles = resource.get("profiles", [])
        sha256 = (resource.get("sha256") or "").strip()

        if not resource_id:
            errors.append(f"{label}: missing 'id'")
        elif resource_id in seen_ids:
            errors.append(f"{label}: duplicate id")
        else:
            seen_ids.add(resource_id)

        if not target or not is_safe_relative_target(target):
            errors.append(f"{label}: invalid relative target '{target}'")

        if kind not in {"url"}:
            errors.append(f"{label}: unsupported kind '{kind}'")

        if kind == "url" and not resource.get("url"):
            errors.append(f"{label}: missing 'url'")

        if not isinstance(resource_profiles, list) or not resource_profiles:
            errors.append(f"{label}: missing profiles")
        else:
            unknown = sorted(set(resource_profiles) - known_profiles)
            if unknown:
                errors.append(f"{label}: unknown profiles: {', '.join(unknown)}")

        if sha256 and len(sha256) != 64:
            errors.append(f"{label}: sha256 must be 64 hex chars when set")

    return errors


def filter_resources(
    resources: list[dict],
    *,
    profile: str | None,
    category: str | None,
    enabled_only: bool,
) -> list[dict]:
    selected = resources

    if profile:
        selected = [r for r in selected if profile in r.get("profiles", [])]

    if category:
        selected = [r for r in selected if r.get("category") == category]

    if enabled_only:
        selected = [r for r in selected if bool(r.get("enabled"))]

    return selected


def print_resources(resources: list[dict]) -> None:
    if not resources:
        print("No matching resources.")
        return

    for resource in resources:
        status = "enabled" if resource.get("enabled") else "disabled"
        profiles = ",".join(resource.get("profiles", []))
        print(
            f"{resource['id']:<16} "
            f"{resource['category']:<18} "
            f"{status:<8} "
            f"{profiles:<16} "
            f"{resource['target']}"
        )


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(resource: dict, destination: Path, *, force: bool, dry_run: bool) -> str:
    url = resource["url"]
    sha256 = (resource.get("sha256") or "").strip()

    if destination.exists() and not force:
        return f"skip    {resource['id']}: already exists"

    if dry_run:
        return f"dry-run {resource['id']}: {url} -> {destination.relative_to(REPO_ROOT)}"

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False) as tmp_handle:
        tmp_path = Path(tmp_handle.name)

    try:
        with urllib.request.urlopen(url) as response, tmp_path.open("wb") as handle:
            shutil.copyfileobj(response, handle)

        if sha256:
            actual = compute_sha256(tmp_path)
            if actual != sha256:
                raise CatalogError(
                    f"{resource['id']}: sha256 mismatch (expected {sha256}, got {actual})"
                )

        tmp_path.replace(destination)

        if resource.get("executable"):
            destination.chmod(0o755)

        return f"sync    {resource['id']}: wrote {destination.relative_to(REPO_ROOT)}"
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def cmd_validate(_: argparse.Namespace) -> int:
    profiles = load_profiles()
    resources = load_resources()
    errors = validate_catalog(resources, profiles)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Catalog is valid.")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    profiles = load_profiles()
    resources = load_resources()
    errors = validate_catalog(resources, profiles)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    selected = filter_resources(
        resources,
        profile=args.profile,
        category=args.category,
        enabled_only=args.enabled_only,
    )
    print_resources(selected)
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    profiles = load_profiles()
    resources = load_resources()
    errors = validate_catalog(resources, profiles)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    selected = filter_resources(
        resources,
        profile=args.profile,
        category=args.category,
        enabled_only=True,
    )

    if not selected:
        print("No enabled resources match the current selection.")
        return 0

    for resource in selected:
        destination = REPO_ROOT / resource["target"]
        try:
            print(download(resource, destination, force=args.force, dry_run=args.dry_run))
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sync.py", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate catalog files")
    validate_parser.set_defaults(func=cmd_validate)

    list_parser = subparsers.add_parser("list", help="List catalog entries")
    list_parser.add_argument("--profile", help="Filter by profile name")
    list_parser.add_argument("--category", help="Filter by category")
    list_parser.add_argument("--enabled-only", action="store_true", help="Show only enabled resources")
    list_parser.set_defaults(func=cmd_list)

    sync_parser = subparsers.add_parser("sync", help="Download enabled resources")
    sync_parser.add_argument("--profile", help="Filter by profile name")
    sync_parser.add_argument("--category", help="Filter by category")
    sync_parser.add_argument("--force", action="store_true", help="Overwrite existing files")
    sync_parser.add_argument("--dry-run", action="store_true", help="Print actions without downloading")
    sync_parser.set_defaults(func=cmd_sync)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except CatalogError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
