#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""Check or add standard source attribution headers."""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LICENSE_ID = "AGPL-3.0-only"


def _detect_license_id() -> str:
    license_file = ROOT / "LICENSE"
    if not license_file.exists():
        return DEFAULT_LICENSE_ID
    text = license_file.read_text(encoding="utf-8", errors="ignore")
    if "MIT License" in text and "Permission is hereby granted" in text:
        return "MIT"
    if "GNU AFFERO GENERAL PUBLIC LICENSE" in text:
        return "AGPL-3.0-only"
    return DEFAULT_LICENSE_ID


LICENSE_ID = _detect_license_id()

TARGET_ROOTS = (
    Path("backend/app"),
    Path("community/overrides/backend/app"),
    Path("frontend/src"),
    Path("scripts"),
)

COMMENT_STYLES = {
    ".py": "#",
    ".ts": "//",
    ".tsx": "//",
    ".js": "//",
    ".jsx": "//",
}

VUE_HEADER = (
    "<!--\n"
    "SPDX-FileCopyrightText: 2026 TechFlag\n"
    f"SPDX-License-Identifier: {LICENSE_ID}\n"
    "-->\n"
)

IGNORED_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".runtime",
    "node_modules",
    "dist",
    "build",
}


def _line_header(prefix: str) -> str:
    return (
        f"{prefix} SPDX-FileCopyrightText: 2026 TechFlag\n"
        f"{prefix} SPDX-License-Identifier: {LICENSE_ID}\n"
    )


def _has_header(text: str) -> bool:
    return (
        "SPDX-FileCopyrightText: 2026 TechFlag" in text
        and f"SPDX-License-Identifier: {LICENSE_ID}" in text
    )


def _target_files() -> list[Path]:
    files: list[Path] = []
    for root in TARGET_ROOTS:
        absolute_root = ROOT / root
        if not absolute_root.exists():
            continue
        for path in absolute_root.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(ROOT)
            if any(part in IGNORED_PARTS for part in rel.parts):
                continue
            if path.suffix in COMMENT_STYLES or path.suffix == ".vue":
                files.append(rel)
    return sorted(files)


def _insert_line_header(text: str, prefix: str) -> str:
    lines = text.splitlines(keepends=True)
    insert_at = 0
    if lines and lines[0].startswith("#!"):
        insert_at = 1
    if len(lines) > insert_at and "coding" in lines[insert_at] and lines[insert_at].lstrip().startswith("#"):
        insert_at += 1
    header = _line_header(prefix)
    if insert_at > 0 and insert_at < len(lines) and lines[insert_at].strip():
        header += "\n"
    lines.insert(insert_at, header)
    return "".join(lines)


def _with_header(path: Path, text: str) -> str:
    if path.suffix == ".vue":
        return VUE_HEADER + ("\n" if text and not text.startswith("\n") else "") + text
    prefix = COMMENT_STYLES[path.suffix]
    return _insert_line_header(text, prefix)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", action="store_true", help="Add missing source attribution headers.")
    args = parser.parse_args()

    missing: list[Path] = []
    for rel in _target_files():
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", errors="ignore")
        if _has_header(text):
            continue
        missing.append(rel)
        if args.fix:
            path.write_text(_with_header(path, text), encoding="utf-8")

    if missing and not args.fix:
        print("Source attribution check failed:")
        for rel in missing:
            print(f"- {rel}: missing SPDX/TechFlag source attribution header")
        return 1

    if missing and args.fix:
        print("Source attribution headers added:")
        for rel in missing:
            print(f"- {rel}")
        return 0

    print("Source attribution check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
