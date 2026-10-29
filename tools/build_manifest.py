#!/usr/bin/env python3
"""
Build manifest.json from apps/*/app.json and the files beside them.

    python3 tools/build_manifest.py          # write manifest.json
    python3 tools/build_manifest.py --check  # exit 1 if manifest.json is stale

Each app folder needs an app.json:

    {
      "name": "Hello Den",
      "description": "One line for the store listing",
      "version": "1.0.0",
      "author": "Gond-ul",
      "exclude": ["notes/*"]          # optional, extra files to keep off the badge
    }

The folder name is the slug the badge installs it under (/system/apps/<slug>).
"""

import fnmatch
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APPS = ROOT / "apps"
MANIFEST = ROOT / "manifest.json"

SLUG = re.compile(r"^[a-z0-9_]+$")
PROTECTED = {"menu"}
# repo-only files that the badge never needs
EXCLUDE = [
    "app.json",
    "*.md",
    "*.svg",
    "screenshot*",
    ".*",
    "*/.*",
    "__pycache__/*",
    "*/__pycache__/*",
    "*.pyc",
]


def excluded(path, patterns):
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def describe(folder):
    slug = folder.name
    if not SLUG.match(slug):
        raise SystemExit(f"{slug}: folder names must be lowercase letters, digits and _")
    if slug in PROTECTED:
        raise SystemExit(f"{slug}: is protected and can't be published")

    meta = json.loads((folder / "app.json").read_text())
    patterns = EXCLUDE + meta.get("exclude", [])
    files = []
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        relative = path.relative_to(folder).as_posix()
        if excluded(relative, patterns):
            continue
        data = path.read_bytes()
        files.append({"path": relative, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})

    if not any(f["path"] in ("__init__.py", "__init__.mpy") for f in files):
        raise SystemExit(f"{slug}: needs an __init__.py for the launcher to show it")

    return {
        "slug": slug,
        "name": meta.get("name", slug.replace("_", " ").title()),
        "description": meta.get("description", ""),
        "version": str(meta.get("version", "")),
        "author": meta.get("author", ""),
        "files": files,
    }


def build():
    apps = [describe(folder) for folder in sorted(APPS.iterdir()) if (folder / "app.json").is_file()]
    return json.dumps({"schema": 1, "apps": apps}, indent=2) + "\n"


def main():
    manifest = build()
    if "--check" in sys.argv:
        current = MANIFEST.read_text() if MANIFEST.exists() else ""
        if current != manifest:
            print("manifest.json is out of date: run python3 tools/build_manifest.py")
            sys.exit(1)
        print("manifest.json is up to date")
        return
    MANIFEST.write_text(manifest)
    count = manifest.count('"slug"')
    print(f"wrote manifest.json with {count} app{'s' if count != 1 else ''}")


if __name__ == "__main__":
    main()
