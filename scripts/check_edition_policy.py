#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT

"""Static checks for community/commercial edition guardrails."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TEXT_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".vue",
    ".yml",
    ".yaml",
    ".json",
}

IGNORED_PARTS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".runtime",
    "prd",
    "tabletest",
}

EDITION_ALLOWED = {
    Path("backend/app/core/config.py"),
    Path("backend/app/core/edition_policy.py"),
    Path("backend/app/schemas/system.py"),
    Path("backend/app/api/routes/system.py"),
    Path("backend/tests/test_config.py"),
    Path("backend/tests/test_community_sqlite_bootstrap.py"),
    Path("backend/tests/test_edition_policy.py"),
    Path(".github/workflows/edition-policy.yml"),
    Path("frontend/src/types/system.ts"),
    Path("frontend/src/stores/capabilities.ts"),
    Path("scripts/check_edition_policy.py"),
    Path("scripts/check_feature_decisions.py"),
    Path("scripts/audit_commercial_boundary.py"),
    Path("scripts/edition_guardrail_agent.py"),
    Path("scripts/export_community_snapshot.py"),
    Path("scripts/publish_github_community.py"),
}

EDITION_PATTERNS = (
    "IDP_EDITION",
    "idp_edition",
)

DUPLICATE_NAME_PATTERN = re.compile(r"\b(?:community|commercial)_[A-Za-z0-9_]+|[A-Za-z0-9_]+_(?:community|commercial)\b")
COMMUNITY_EXPORT_EXCLUDE_ANNOTATIONS = (
    "@edition-scope commercial-only",
    "@community-export exclude",
)


def iter_text_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(part in IGNORED_PARTS for part in rel.parts):
            continue
        if path.suffix not in TEXT_SUFFIXES:
            continue
        files.append(rel)
    return sorted(files)


def read_text(rel: Path) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="ignore")


def check_edition_references(files: list[Path]) -> list[str]:
    errors: list[str] = []
    for rel in files:
        if rel.parts[:2] == ("docs", "feature-decisions"):
            continue
        text = read_text(rel)
        if not any(pattern in text for pattern in EDITION_PATTERNS):
            continue
        if rel not in EDITION_ALLOWED:
            errors.append(f"{rel}: edition references must stay in config/policy/capability layers")
    return errors


def check_duplicate_edition_names(files: list[Path]) -> list[str]:
    errors: list[str] = []
    for rel in files:
        if rel in EDITION_ALLOWED:
            continue
        text = read_text(rel)
        for line_no, line in enumerate(text.splitlines(), start=1):
            if DUPLICATE_NAME_PATTERN.search(line):
                errors.append(f"{rel}:{line_no}: avoid duplicate community/commercial product code names")
                break
    return errors


def check_frontend_routes() -> list[str]:
    router = ROOT / "frontend/src/router/index.ts"
    if not router.exists():
        return []
    text = router.read_text(encoding="utf-8", errors="ignore")
    errors: list[str] = []
    route_blocks = re.finditer(r"\{\s*\n\s*path:\s*['\"][^'\"]+['\"][\s\S]*?\n\s*\},", text)
    for match in route_blocks:
        block = match.group(0)
        if "component:" not in block and "redirect:" not in block:
            continue
        if "capability:" not in block and "publicCore:" not in block:
            line_no = text[: match.start()].count("\n") + 1
            first_line = block.strip().splitlines()[0].strip()
            errors.append(f"frontend/src/router/index.ts:{line_no}: route must declare capability or publicCore ({first_line})")
    return errors


def check_community_export_annotations(files: list[Path]) -> list[str]:
    export_script = read_text(Path("scripts/export_community_snapshot.py"))
    public_check = read_text(Path("scripts/check_public_export.py"))
    scanner_files = {
        Path("scripts/audit_commercial_boundary.py"),
        Path("scripts/check_edition_policy.py"),
        Path("scripts/check_public_export.py"),
    }
    errors: list[str] = []
    for rel in files:
        if rel in scanner_files:
            continue
        if rel.parts[:2] == ("community", "overrides"):
            continue
        text = read_text(rel)
        if not any(annotation in text for annotation in COMMUNITY_EXPORT_EXCLUDE_ANNOTATIONS):
            continue
        rel_text = str(rel)
        rel_marker = f'Path("{rel_text}")'
        if rel_marker not in export_script:
            errors.append(f"{rel}: commercial-only file must be excluded by export_community_snapshot.py")
        if rel_marker not in public_check:
            errors.append(f"{rel}: commercial-only file must be forbidden by check_public_export.py")
    return errors


def check_shared_api_action_annotations(files: list[Path]) -> list[str]:
    errors: list[str] = []
    for rel in files:
        if rel.parts[:3] != ("backend", "app", "api") or rel.name == "__init__.py":
            continue
        text = read_text(rel)
        if "@edition-scope shared-api-contract" not in text:
            continue
        lines = text.splitlines()
        for index, line in enumerate(lines):
            if not line.lstrip().startswith("@router."):
                continue
            window = "\n".join(lines[max(0, index - 4) : index + 1])
            if "@edition-action" not in window:
                errors.append(f"{rel}:{index + 1}: shared API route must declare @edition-action")
            if "@capability" not in window:
                errors.append(f"{rel}:{index + 1}: shared API route must declare @capability")
    return errors


def main() -> int:
    files = iter_text_files()
    errors = [
        *check_edition_references(files),
        *check_duplicate_edition_names(files),
        *check_community_export_annotations(files),
        *check_shared_api_action_annotations(files),
        *check_frontend_routes(),
    ]
    if errors:
        print("Edition policy check failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Edition policy check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
