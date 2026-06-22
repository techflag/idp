#!/usr/bin/env python3
"""Export a sanitized community snapshot for GitHub publication."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMUNITY_OVERLAY_ROOT = ROOT / "community" / "overrides"
INTERNAL_DOCS_ROOT = ROOT / "docs" / "internal"

COPY_FILES = [
    "AGENTS.md",
    "LICENSE",
    "README.md",
    "README.zh-CN.md",
    "requirements.txt",
    ".gitignore",
    ".github/pull_request_template.md",
    ".github/workflows/edition-policy.yml",
    "backend/.env.local.example",
    "backend/.env.server.example",
    "backend/.gitignore",
    "backend/README.md",
    "backend/README.zh-CN.md",
    "backend/alembic.ini",
    "backend/pyproject.toml",
    "backend/requirements.txt",
    "backend/start.sh",
    "backend/stop.sh",
    "backend/restart.sh",
    "backend/scripts/__init__.py",
    "backend/scripts/diagnose_auth.py",
    "frontend/.env.example",
    "frontend/.gitignore",
    "frontend/README.md",
    "frontend/README.zh-CN.md",
    "frontend/index.html",
    "frontend/package-lock.json",
    "frontend/package.json",
    "frontend/tsconfig.app.json",
    "frontend/tsconfig.json",
    "frontend/tsconfig.node.json",
    "frontend/vite.config.ts",
    "scripts/check_edition_policy.py",
    "scripts/check_feature_decisions.py",
    "scripts/audit_commercial_boundary.py",
    "scripts/edition_guardrail_agent.py",
    "scripts/export_community_snapshot.py",
    "scripts/check_public_export.py",
    "scripts/publish_github_community.py",
    "scripts/publish_open_source_snapshot.py",
]

COPY_DIRS = [
    "backend/alembic",
    "backend/app",
    "community",
    "docs",
    "frontend/public",
    "frontend/src",
]

COPY_TESTS = [
    "backend/tests/test_community_sqlite_bootstrap.py",
    "backend/tests/test_config.py",
    "backend/tests/test_edition_policy.py",
    "backend/tests/test_mineru_service.py",
    "backend/tests/test_no_business_hardcoding.py",
]

EXCLUDE_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".runtime",
    "node_modules",
    "dist",
    "idp",
    ".DS_Store",
    "idp_poc_backend.egg-info",
    "tmp",
}

EXCLUDE_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".tsbuildinfo",
}

EXCLUDE_RELATIVE_PATHS = {
    Path("backend/alembic/versions"),
    Path("backend/app/services/mainline_gate_service.py"),
    Path("backend/app/services/published_skill_registry.py"),
    Path("backend/app/services/sample_dataset.py"),
    Path("backend/app/services/skill_prototype_job_service.py"),
    Path("backend/app/services/skill_prototype_service.py"),
    Path("backend/app/services/skill_prototype_workspace.py"),
    Path("backend/app/services/skillnet_service.py"),
    Path("backend/app/services/skillopt_adapter.py"),
    Path("backend/app/services/skillopt_dataset_exporter.py"),
    Path("backend/app/services/skillopt_evaluation_service.py"),
    Path("backend/app/services/skillopt_extraction_runner.py"),
    Path("backend/app/services/skillopt_run_artifacts.py"),
}


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def should_skip(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if is_relative_to(path, COMMUNITY_OVERLAY_ROOT) or is_relative_to(path, INTERNAL_DOCS_ROOT):
        return True
    if any(rel == excluded or excluded in rel.parents for excluded in EXCLUDE_RELATIVE_PATHS):
        return True
    if any(part in EXCLUDE_PARTS for part in rel.parts):
        return True
    if path.name.startswith(".env") and path.name not in {".env.example", ".env.local.example", ".env.server.example"}:
        return True
    return path.suffix in EXCLUDE_SUFFIXES


def copy_file(rel: str, target: Path) -> None:
    source = ROOT / rel
    if not source.exists():
        return
    destination = target / rel
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def copy_dir(rel: str, target: Path) -> None:
    source_root = ROOT / rel
    if not source_root.exists():
        return
    for source in source_root.rglob("*"):
        if source.is_dir() or should_skip(source):
            continue
        destination = target / source.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def apply_community_overlays(target: Path) -> None:
    if not COMMUNITY_OVERLAY_ROOT.exists():
        return
    for source in COMMUNITY_OVERLAY_ROOT.rglob("*"):
        if source.is_dir():
            continue
        rel = source.relative_to(COMMUNITY_OVERLAY_ROOT)
        if any(part in EXCLUDE_PARTS for part in rel.parts) or source.suffix in EXCLUDE_SUFFIXES:
            continue
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def prepare_target(target: Path) -> None:
    if not target.exists():
        target.mkdir(parents=True)
        return
    if not target.is_dir():
        print(f"Export target must be a directory: {target}")
        raise SystemExit(2)

    for child in target.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: scripts/export_community_snapshot.py <export-dir>")
        return 2

    target = Path(argv[1]).resolve()
    if target == ROOT or ROOT in target.parents:
        print("Export directory must be outside the current worktree.")
        return 2
    prepare_target(target)

    for rel in COPY_FILES:
        copy_file(rel, target)
    for rel in COPY_DIRS:
        copy_dir(rel, target)
    for rel in COPY_TESTS:
        copy_file(rel, target)
    apply_community_overlays(target)

    print(f"Community snapshot exported to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
