#!/usr/bin/env python3
"""Audit commercial/private implementation boundaries.

This check is intentionally deterministic. It does not decide product strategy;
it makes sure files that look like commercial implementation are either marked
and excluded, or replaced by a community stub in the sanitized export.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TEXT_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".vue", ".yml", ".yaml", ".json", ".md"}
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

COMMERCIAL_NAME_PATTERN = re.compile(
    r"(?:^|[/_-])("
    r"skillopt|skillnet|skill_prototype|skill-prototype|mainline_gate|published_skill"
    r")(?:$|[/_.-])",
    re.IGNORECASE,
)

COMMERCIAL_ALLOWED_SHARED_CONTRACTS = {
    Path("backend/app/api/routes/skill_prototypes.py"),
    Path("backend/app/schemas/skill_prototype.py"),
}

COMMERCIAL_OVERLAY_STUBS = {
    Path("backend/app/api/routes/applications.py"): "COMMUNITY_APPLICATION_ROUTES_STUB",
    Path("backend/app/services/application_assets.py"): "COMMUNITY_APPLICATION_ASSETS_STUB",
    Path("backend/app/services/skill_prototype_service.py"): "COMMUNITY_SKILL_PROTOTYPE_SERVICE_STUB",
    Path("backend/app/services/skill_prototype_job_service.py"): "COMMUNITY_SKILL_PROTOTYPE_JOB_SERVICE_STUB",
}

COMMERCIAL_ANNOTATIONS = (
    "@edition-scope commercial-only",
    "@community-export exclude",
)
COMMUNITY_STUB_MARKERS = (
    "@edition-scope community-stub",
    "COMMUNITY_APPLICATION_ROUTES_STUB",
    "COMMUNITY_APPLICATION_ASSETS_STUB",
    "COMMUNITY_SKILL_PROTOTYPE_SERVICE_STUB",
    "COMMUNITY_SKILL_PROTOTYPE_JOB_SERVICE_STUB",
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _iter_source_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        rel = path.relative_to(ROOT)
        if any(part in IGNORED_PARTS for part in rel.parts):
            continue
        if rel.parts[:2] == ("community", "overrides"):
            continue
        files.append(rel)
    return sorted(files)


def _is_listed(rel: Path, text: str) -> bool:
    return f'Path("{rel.as_posix()}")' in text


def check_named_commercial_files(files: list[Path]) -> list[str]:
    export_script = _text(ROOT / "scripts" / "export_community_snapshot.py")
    public_check = _text(ROOT / "scripts" / "check_public_export.py")
    errors: list[str] = []
    for rel in files:
        if rel in COMMERCIAL_ALLOWED_SHARED_CONTRACTS:
            continue
        if not rel.as_posix().startswith("backend/app/"):
            continue
        if not COMMERCIAL_NAME_PATTERN.search(rel.as_posix()):
            continue
        text = _text(ROOT / rel)
        if any(marker in text for marker in COMMUNITY_STUB_MARKERS):
            continue
        missing_annotations = [annotation for annotation in COMMERCIAL_ANNOTATIONS if annotation not in text]
        if missing_annotations:
            errors.append(f"{rel}: commercial-looking file must declare {', '.join(missing_annotations)}")
        if not _is_listed(rel, export_script):
            errors.append(f"{rel}: commercial-looking file must be excluded by export_community_snapshot.py")
        if not _is_listed(rel, public_check):
            errors.append(f"{rel}: commercial-looking file must be forbidden by check_public_export.py")
    return errors


def check_overlay_stubs() -> list[str]:
    public_check = _text(ROOT / "scripts" / "check_public_export.py")
    errors: list[str] = []
    for rel, marker in COMMERCIAL_OVERLAY_STUBS.items():
        overlay = ROOT / "community" / "overrides" / rel
        exported_stub = ROOT / rel
        if overlay.exists():
            stub_path = overlay
            label = Path("community") / "overrides" / rel
        elif exported_stub.exists():
            stub_path = exported_stub
            label = rel
        else:
            errors.append(f"{rel}: required community stub overlay or exported stub is missing")
            continue
        text = _text(stub_path)
        if marker not in text:
            errors.append(f"{label}: required stub marker {marker} is missing")
        if marker not in public_check:
            errors.append(f"scripts/check_public_export.py: must require stub marker {marker}")
    return errors


def check_capability_registry_boundary() -> list[str]:
    registry = ROOT / "backend" / "app" / "core" / "edition_policy.py"
    if not registry.exists():
        return ["backend/app/core/edition_policy.py: missing capability registry"]
    text = _text(registry)
    required_terms = {
        "skill.prototypeOptimization": "抽取反推 Skill / SkillOpt must stay unavailable in community.",
        "document.longRun": "Long-document full chain must stay unavailable in community.",
        "application.run": "Application run must stay lite/stub in community.",
        "application.authoring": "Application authoring must stay lite/stub in community.",
    }
    errors: list[str] = []
    for term, reason in required_terms.items():
        if term not in text:
            errors.append(f"backend/app/core/edition_policy.py: missing capability {term} ({reason})")
    if "community_implementation=\"public_stub\"" not in text:
        errors.append("backend/app/core/edition_policy.py: no public_stub community implementation declared")
    if "commercial_implementation=\"commercial_extension\"" not in text:
        errors.append("backend/app/core/edition_policy.py: no commercial_extension implementation declared")
    return errors


def main() -> int:
    files = _iter_source_files()
    errors = [
        *check_named_commercial_files(files),
        *check_overlay_stubs(),
        *check_capability_registry_boundary(),
    ]
    if errors:
        print("Commercial boundary audit failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Commercial boundary audit passed.")
    print("Protected commercial boundaries:")
    for rel in sorted(COMMERCIAL_OVERLAY_STUBS):
        print(f"- {rel} -> community stub overlay")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
