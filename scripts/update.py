#!/usr/bin/env python3
"""Maintainer-side updater: download every resource declared in the catalog
into the repo so a downstream `git clone --recurse-submodules` ships them.

Run from the repo root:

    ./scripts/update.py                       # process everything (enabled)
    ./scripts/update.py --dry-run             # show what would happen
    ./scripts/update.py --profile ad          # restrict to one profile
    ./scripts/update.py --kind release_asset  # only one kind
    ./scripts/update.py linpeas mimikatz      # only listed ids

After running, regenerates resources_list.csv at the repo root, then it is up
to the maintainer to `git add -A && git commit && git push`.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from _lib import (
    CSV_PATH,
    CatalogError,
    KIND_RELEASE_ASSET,
    KIND_SUBMODULE,
    KIND_URL,
    MAINTAINER_KINDS,
    REPO_ROOT,
    SUPPORTED_KINDS,
    download_url,
    ensure_submodule,
    extract_archive,
    filter_resources,
    load_profiles,
    load_resources,
    resolve_release_asset,
    validate_catalog,
)


def _process_url(resource: dict, dry_run: bool, force: bool) -> str:
    target = REPO_ROOT / resource["target"]
    if target.exists() and not force:
        return f"skip    {resource['id']}: {target.relative_to(REPO_ROOT)} already present"
    if dry_run:
        return f"dry-run {resource['id']}: GET {resource['url']} -> {target.relative_to(REPO_ROOT)}"
    download_url(resource["url"], target, expected_sha256=(resource.get("sha256") or "").strip())
    if resource.get("executable"):
        target.chmod(0o755)
    return f"fetch   {resource['id']}: wrote {target.relative_to(REPO_ROOT)}"


def _process_release_asset(resource: dict, dry_run: bool, force: bool) -> str:
    repo = resource["github"]
    pattern = resource["asset_pattern"]
    target = REPO_ROOT / resource["target"]
    extract = bool(resource.get("extract"))

    if target.exists() and not force and not extract:
        return f"skip    {resource['id']}: {target.relative_to(REPO_ROOT)} already present"

    if dry_run:
        return f"dry-run {resource['id']}: resolve latest {repo} /{pattern}/ -> {target.relative_to(REPO_ROOT)}"

    asset_name, url = resolve_release_asset(repo, pattern)
    if extract:
        # Download to a temp file inside target dir, extract, then drop the archive.
        target.mkdir(parents=True, exist_ok=True)
        archive_path = target / asset_name
        download_url(url, archive_path)
        try:
            extract_archive(archive_path, target)
        finally:
            archive_path.unlink(missing_ok=True)
        return f"fetch   {resource['id']}: extracted {asset_name} -> {target.relative_to(REPO_ROOT)}/"
    download_url(url, target)
    if resource.get("executable"):
        target.chmod(0o755)
    return f"fetch   {resource['id']}: wrote {target.relative_to(REPO_ROOT)} ({asset_name})"


def _process_submodule(resource: dict, dry_run: bool) -> str:
    target = resource["target"]
    repo = resource["repo"]
    branch = resource.get("branch") or ""
    if dry_run:
        suffix = f" (branch {branch})" if branch else ""
        return f"dry-run {resource['id']}: ensure submodule {target} -> {repo}{suffix}"
    return f"submod  {resource['id']}: " + ensure_submodule(repo, target, branch=branch)


def _regenerate_csv(resources: list[dict]) -> None:
    rows = []
    for r in resources:
        if r.get("kind") == KIND_SUBMODULE:
            link = r.get("repo", "")
        elif r.get("kind") == KIND_RELEASE_ASSET:
            link = f"https://github.com/{r.get('github', '')}"
        else:
            link = r.get("url", "")
        rows.append((r.get("name") or r.get("id", ""), link, r.get("notes") or ""))
    with CSV_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("Resource", "Link", "Description"))
        writer.writerows(rows)


def cmd_update(args: argparse.Namespace) -> int:
    profiles = load_profiles()
    resources = load_resources()
    errors = validate_catalog(resources, profiles)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    kinds = MAINTAINER_KINDS if not args.kind else frozenset({args.kind})
    if not kinds.issubset(SUPPORTED_KINDS):
        print(f"ERROR: unsupported --kind {args.kind!r}", file=sys.stderr)
        return 1

    selected = filter_resources(
        resources,
        profile=args.profile,
        category=args.category,
        kinds=kinds,
        enabled_only=not args.include_disabled,
        ids=args.ids or None,
    )

    if not selected:
        print("No matching resources.")
        return 0

    failed: list[str] = []
    for resource in selected:
        kind = resource["kind"]
        try:
            if kind == KIND_URL:
                line = _process_url(resource, args.dry_run, args.force)
            elif kind == KIND_RELEASE_ASSET:
                line = _process_release_asset(resource, args.dry_run, args.force)
            elif kind == KIND_SUBMODULE:
                line = _process_submodule(resource, args.dry_run)
            else:
                line = f"skip    {resource['id']}: unknown kind {kind!r}"
            print(line)
        except CatalogError as exc:
            failed.append(resource["id"])
            print(f"ERROR   {resource['id']}: {exc}", file=sys.stderr)

    if not args.dry_run:
        _regenerate_csv(selected if args.ids else resources)
        print(f"wrote   {CSV_PATH.relative_to(REPO_ROOT)} ({len(resources)} entries)")

    if failed:
        print(f"\n{len(failed)} resource(s) failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="update.py", description=__doc__)
    parser.add_argument("ids", nargs="*", help="Restrict to these resource ids (default: all enabled).")
    parser.add_argument("--profile", help="Filter by profile name (full|ad|web|ctf).")
    parser.add_argument("--category", help="Filter by category (active-directory|linux|windows|web|wordlists|...).")
    parser.add_argument("--kind", choices=sorted(SUPPORTED_KINDS), help="Restrict to one kind.")
    parser.add_argument("--include-disabled", action="store_true", help="Process resources marked enabled=false too.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing files.")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without performing them.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return cmd_update(args)
    except CatalogError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
