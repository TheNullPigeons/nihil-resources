#!/usr/bin/env python3
"""User-side fetch: validate catalog, list entries, download enabled ones.

Only handles kind="url" entries. Resources of kind="release_asset" or
kind="submodule" are produced at maintainer time by update.py and shipped
through `git clone --recurse-submodules`, so this script skips them silently.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from _lib import (
    REPO_ROOT,
    USER_FETCH_KINDS,
    CatalogError,
    download_url,
    filter_resources,
    load_profiles,
    load_resources,
    validate_catalog,
)


def print_resources(resources: list[dict]) -> None:
    if not resources:
        print("No matching resources.")
        return
    for r in resources:
        status = "enabled" if r.get("enabled") else "disabled"
        profiles = ",".join(r.get("profiles", []))
        kind = r.get("kind", "?")
        print(
            f"{r['id']:<28} "
            f"{r.get('category', ''):<18} "
            f"{kind:<14} "
            f"{status:<8} "
            f"{profiles:<20} "
            f"{r.get('target', '')}"
        )


def cmd_validate(_: argparse.Namespace) -> int:
    profiles = load_profiles()
    resources = load_resources()
    errors = validate_catalog(resources, profiles)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Catalog is valid ({len(resources)} entries).")
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
        kinds=USER_FETCH_KINDS,
        enabled_only=True,
    )

    if not selected:
        print("No enabled URL-based resources match the current selection.")
        return 0

    failed = 0
    for resource in selected:
        destination = REPO_ROOT / resource["target"]
        if destination.exists() and not args.force:
            print(f"skip    {resource['id']}: already exists")
            continue
        if args.dry_run:
            print(f"dry-run {resource['id']}: {resource['url']} -> {resource['target']}")
            continue
        try:
            download_url(resource["url"], destination, expected_sha256=(resource.get("sha256") or "").strip())
            if resource.get("executable"):
                destination.chmod(0o755)
            print(f"sync    {resource['id']}: wrote {resource['target']}")
        except CatalogError as exc:
            failed += 1
            print(f"ERROR   {resource['id']}: {exc}", file=sys.stderr)
    return 1 if failed else 0


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

    sync_parser = subparsers.add_parser("sync", help="Download enabled URL-based resources")
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
