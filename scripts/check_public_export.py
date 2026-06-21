#!/usr/bin/env python3
"""Sanity checks for a sanitized GitHub community export directory."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ACCESS_KEY_PATTERN = re.compile(r"AKIA[0-9A-Z]{16}")
ENV_SECRET_ASSIGNMENT = re.compile(
    r"^\s*(?:export\s+)?[A-Z0-9_]*(?:_KEY|_TOKEN|_SECRET|_PASSWORD|PASSWORD|TOKEN|SECRET|KEY)\s*=\s*['\"]?([^'\"\s#]+)"
)
PUBLIC_SECRET_ASSIGNMENT = re.compile(
    r"^\s*(?:export\s+)?(?:MINERU_TOKEN|DASHSCOPE_API_KEY|OSS_ACCESS_KEY_ID|OSS_ACCESS_KEY_SECRET|AUTH_SECRET)\s*[:=]\s*['\"]?([^'\"\s#]+)"
)
PRIVATE_KEY_MARKER = "-----BEGIN "

FORBIDDEN_PARTS = {
    ".runtime",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
}

IGNORED_PARTS = {
    ".git",
}

FORBIDDEN_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".DS_Store",
}

FORBIDDEN_NAMES = {
    ".DS_Store",
    ".env",
    ".env.local",
    ".env.production.local",
}

FORBIDDEN_RELATIVE_PATHS = {
    Path("backend/extraction_skills"),
    Path("backend/skills"),
    Path("backend/app/services/mainline_gate_service.py"),
    Path("backend/app/services/published_skill_registry.py"),
    Path("backend/app/services/sample_dataset.py"),
    Path("backend/app/services/skill_prototype_workspace.py"),
    Path("backend/app/services/skillnet_service.py"),
    Path("backend/app/services/skillopt_adapter.py"),
    Path("backend/app/services/skillopt_dataset_exporter.py"),
    Path("backend/app/services/skillopt_evaluation_service.py"),
    Path("backend/app/services/skillopt_extraction_runner.py"),
    Path("backend/app/services/skillopt_run_artifacts.py"),
    Path("community/overrides"),
    Path("docs/internal"),
    Path("docs/github-release-runbook.md"),
}

REQUIRED_PUBLIC_STUB_MARKERS = {
    Path("AGENTS.md"): "TechFlag IDP Community Development Guardrails",
    Path("backend/alembic/versions/0001_community_schema.py"): "COMMUNITY_SCHEMA_BASELINE",
    Path("backend/app/api/routes/applications.py"): "COMMUNITY_APPLICATION_ROUTES_STUB",
    Path("backend/app/services/application_assets.py"): "COMMUNITY_APPLICATION_ASSETS_STUB",
    Path("backend/app/services/skill_prototype_service.py"): "COMMUNITY_SKILL_PROTOTYPE_SERVICE_STUB",
    Path("backend/app/services/skill_prototype_job_service.py"): "COMMUNITY_SKILL_PROTOTYPE_JOB_SERVICE_STUB",
}

COMMUNITY_ALEMBIC_VERSION = Path("backend/alembic/versions/0001_community_schema.py")
COMMUNITY_ALEMBIC_VERSIONS_DIR = Path("backend/alembic/versions")

FORBIDDEN_PUBLIC_TEXT = {
    "/Users/" "techflag",
    "customer-" "poly",
    "\"customer-" "lab\"",
    "seed/customer-" "lab",
    "普利" "药业",
    "实验室" "验证 PoC",
}

FORBIDDEN_PUBLIC_ANNOTATION_PATTERNS = (
    re.compile(r"^\s*(?:#|//|/\*|<!--)\s*@edition-scope\s+commercial-only\b", re.MULTILINE),
    re.compile(r"^\s*(?:#|//|/\*|<!--)\s*@community-export\s+exclude\b", re.MULTILINE),
)


def is_text_file(path: Path) -> bool:
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".xlsx", ".xls"}:
        return False
    return True


def should_scan_env_assignments(path: Path) -> bool:
    return path.name.startswith(".env") or path.suffix.lower() in {".env", ".ini", ".yml", ".yaml"}


def is_placeholder_secret(value: str) -> bool:
    normalized = value.strip().strip("'\"").lower()
    if not normalized:
        return True
    return (
        normalized.startswith("replace-with-")
        or normalized.startswith("your-")
        or normalized.startswith("example-")
        or normalized.startswith("demo-")
        or normalized.startswith("你的")
        or normalized in {"changeme", "change-me", "your-secret", "your-token", "your-api-key"}
        or "replace-with-your" in normalized
    )


def find_secret_line(path: Path, text: str) -> int | None:
    for line_no, line in enumerate(text.splitlines(), start=1):
        if ACCESS_KEY_PATTERN.search(line) or line.lstrip().startswith(PRIVATE_KEY_MARKER):
            return line_no
        public_secret = PUBLIC_SECRET_ASSIGNMENT.search(line)
        if public_secret and not is_placeholder_secret(public_secret.group(1)):
            return line_no
        if not should_scan_env_assignments(path):
            continue
        assignment = ENV_SECRET_ASSIGNMENT.search(line)
        if assignment and not is_placeholder_secret(assignment.group(1)):
            return line_no
    return None


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: scripts/check_public_export.py <export-dir>")
        return 2

    export_dir = Path(argv[1]).resolve()
    if not export_dir.exists() or not export_dir.is_dir():
        print(f"Export directory does not exist: {export_dir}")
        return 2

    errors: list[str] = []
    forbidden_root_hits: set[Path] = set()
    required_stub_hits: dict[Path, bool] = {rel: False for rel in REQUIRED_PUBLIC_STUB_MARKERS}
    for path in export_dir.rglob("*"):
        rel = path.relative_to(export_dir)
        if any(part in IGNORED_PARTS for part in rel.parts):
            continue
        if (
            path.is_file()
            and COMMUNITY_ALEMBIC_VERSIONS_DIR in rel.parents
            and rel != COMMUNITY_ALEMBIC_VERSION
            and path.suffix == ".py"
        ):
            errors.append(f"{rel}: public export must use the single community baseline migration")
            continue
        forbidden_root = next(
            (forbidden for forbidden in FORBIDDEN_RELATIVE_PATHS if rel == forbidden or forbidden in rel.parents),
            None,
        )
        if forbidden_root is not None:
            if forbidden_root not in forbidden_root_hits:
                errors.append(f"{forbidden_root}: forbidden path for public export")
                forbidden_root_hits.add(forbidden_root)
            continue
        if any(part in FORBIDDEN_PARTS for part in rel.parts):
            errors.append(f"{rel}: forbidden generated/internal path")
            continue
        if path.is_dir():
            continue
        if path.name in FORBIDDEN_NAMES or path.suffix in FORBIDDEN_SUFFIXES:
            errors.append(f"{rel}: forbidden file for public export")
            continue
        if is_text_file(path):
            text = path.read_text(encoding="utf-8", errors="ignore")
            marker = REQUIRED_PUBLIC_STUB_MARKERS.get(rel)
            if marker is not None:
                if marker not in text:
                    errors.append(f"{rel}: public export must use community stub marker {marker}")
                else:
                    required_stub_hits[rel] = True
            for forbidden_text in FORBIDDEN_PUBLIC_TEXT:
                if forbidden_text in text:
                    errors.append(f"{rel}: forbidden internal text {forbidden_text!r}")
                    break
            for annotation_pattern in FORBIDDEN_PUBLIC_ANNOTATION_PATTERNS:
                if annotation_pattern.search(text):
                    errors.append(f"{rel}: forbidden public annotation {annotation_pattern.pattern!r}")
                    break
            secret_line = find_secret_line(path, text)
            if secret_line is not None:
                errors.append(f"{rel}:{secret_line}: possible secret pattern")

    for rel, found in required_stub_hits.items():
        if not found:
            errors.append(f"{rel}: required community stub file is missing")

    if errors:
        print("Public export check failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Public export check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
