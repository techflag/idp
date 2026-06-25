#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT

"""Validate machine-readable Feature Decision records."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DECISION_DIR = ROOT / "docs" / "feature-decisions"
CAPABILITY_REGISTRY = ROOT / "backend" / "app" / "core" / "edition_policy.py"

APPLICABLE_EDITIONS = {"community", "commercial", "both"}
CAPABILITY_LEVELS = {"unavailable", "demo", "basic", "limited", "full"}
CONFIGURATION_STATES = {"configured", "not_configured", "optional", "managed", "not_applicable"}
MIGRATION_IMPACTS = {"none", "required", "not_applicable"}
I18N_SCOPES = {"none", "legacy_zh", "zh_cn", "en", "zh_cn_en"}
CORE_REUSE = {"shared_core", "private_extension", "not_applicable"}

REQUIRED_TOP_LEVEL = {
    "id",
    "featureName",
    "applicableEdition",
    "community",
    "commercial",
    "capabilityKeys",
    "providers",
    "noConfigurationBehavior",
    "frontendEntryControl",
    "backendPolicy",
    "databaseMigrationImpact",
    "i18nScope",
    "testMatrix",
    "dataIntegrity",
    "implementationBoundary",
    "coreReuse",
}

CODE_CHANGE_PREFIXES = (
    "backend/",
    "frontend/",
    "scripts/",
    "community/",
    ".github/workflows/",
)

IGNORED_CHANGE_PREFIXES = (
    "backend/tests/",
    "frontend/dist/",
    "docs/",
    "prd/",
)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError("decision file must contain a JSON object")
    return payload


def _registered_capabilities() -> set[str]:
    if not CAPABILITY_REGISTRY.exists():
        return set()
    text = CAPABILITY_REGISTRY.read_text(encoding="utf-8", errors="ignore")
    keys: set[str] = set()
    marker = "EditionCapability("
    offset = 0
    while True:
        start = text.find(marker, offset)
        if start < 0:
            break
        key_start = text.find('key="', start)
        if key_start >= 0:
            key_start += len('key="')
            key_end = text.find('"', key_start)
            if key_end >= 0:
                keys.add(text[key_start:key_end])
        offset = start + len(marker)
    return keys


def _require_non_empty(value: Any, path: str, errors: list[str]) -> None:
    if value is None:
        errors.append(f"{path}: value is required")
        return
    if isinstance(value, str) and not value.strip():
        errors.append(f"{path}: value cannot be empty")
        return
    if isinstance(value, (list, dict)) and not value:
        errors.append(f"{path}: value cannot be empty")


def _check_enum(value: Any, allowed: set[str], path: str, errors: list[str]) -> None:
    if value not in allowed:
        errors.append(f"{path}: expected one of {sorted(allowed)}, got {value!r}")


def _validate_edition_block(block: Any, path: str, errors: list[str]) -> None:
    if not isinstance(block, dict):
        errors.append(f"{path}: must be an object")
        return
    for key in ("capabilityLevel", "behavior"):
        _require_non_empty(block.get(key), f"{path}.{key}", errors)
    if "capabilityLevel" in block:
        _check_enum(block.get("capabilityLevel"), CAPABILITY_LEVELS, f"{path}.capabilityLevel", errors)


def _validate_provider(provider: Any, path: str, errors: list[str]) -> None:
    if not isinstance(provider, dict):
        errors.append(f"{path}: must be an object")
        return
    for key in ("key", "configurationState", "noConfigurationBehavior"):
        _require_non_empty(provider.get(key), f"{path}.{key}", errors)
    if "configurationState" in provider:
        _check_enum(provider.get("configurationState"), CONFIGURATION_STATES, f"{path}.configurationState", errors)


def _validate_test_matrix(items: Any, path: str, errors: list[str]) -> None:
    if not isinstance(items, list) or not items:
        errors.append(f"{path}: must be a non-empty list")
        return
    coverage = set()
    for index, item in enumerate(items):
        item_path = f"{path}[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_path}: must be an object")
            continue
        for key in ("edition", "scenario", "expected"):
            _require_non_empty(item.get(key), f"{item_path}.{key}", errors)
        edition = item.get("edition")
        if edition in {"community", "commercial"}:
            coverage.add(edition)
        if item.get("noConfiguration") is True:
            coverage.add("noConfiguration")
    for required in ("community", "noConfiguration"):
        if required not in coverage:
            errors.append(f"{path}: must include {required} coverage")


def validate_decision(path: Path, registered_capabilities: set[str]) -> list[str]:
    errors: list[str] = []
    try:
        payload = _load_json(path)
    except ValueError as error:
        return [f"{path.relative_to(ROOT)}: {error}"]

    missing = sorted(REQUIRED_TOP_LEVEL - set(payload))
    for key in missing:
        errors.append(f"{path.relative_to(ROOT)}: missing required field {key!r}")

    for key in ("id", "featureName", "noConfigurationBehavior", "frontendEntryControl", "backendPolicy", "dataIntegrity", "implementationBoundary"):
        _require_non_empty(payload.get(key), f"{path.relative_to(ROOT)}.{key}", errors)

    _check_enum(payload.get("applicableEdition"), APPLICABLE_EDITIONS, f"{path.relative_to(ROOT)}.applicableEdition", errors)
    _validate_edition_block(payload.get("community"), f"{path.relative_to(ROOT)}.community", errors)
    _validate_edition_block(payload.get("commercial"), f"{path.relative_to(ROOT)}.commercial", errors)
    _check_enum(payload.get("databaseMigrationImpact"), MIGRATION_IMPACTS, f"{path.relative_to(ROOT)}.databaseMigrationImpact", errors)
    _check_enum(payload.get("i18nScope"), I18N_SCOPES, f"{path.relative_to(ROOT)}.i18nScope", errors)
    _check_enum(payload.get("coreReuse"), CORE_REUSE, f"{path.relative_to(ROOT)}.coreReuse", errors)

    capability_keys = payload.get("capabilityKeys")
    if not isinstance(capability_keys, list) or not capability_keys:
        errors.append(f"{path.relative_to(ROOT)}.capabilityKeys: must be a non-empty list")
    else:
        for index, capability_key in enumerate(capability_keys):
            if capability_key not in registered_capabilities:
                errors.append(
                    f"{path.relative_to(ROOT)}.capabilityKeys[{index}]: {capability_key!r} is not registered"
                )

    providers = payload.get("providers")
    if not isinstance(providers, list) or not providers:
        errors.append(f"{path.relative_to(ROOT)}.providers: must be a non-empty list")
    else:
        for index, provider in enumerate(providers):
            _validate_provider(provider, f"{path.relative_to(ROOT)}.providers[{index}]", errors)

    _validate_test_matrix(payload.get("testMatrix"), f"{path.relative_to(ROOT)}.testMatrix", errors)
    return errors


def decision_files() -> list[Path]:
    if not DECISION_DIR.exists():
        return []
    return sorted(DECISION_DIR.glob("*.json"))


def _changed_files(base: str, head: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _needs_decision(changed_files: list[str]) -> bool:
    for path in changed_files:
        if path.startswith(IGNORED_CHANGE_PREFIXES):
            continue
        if path.startswith(CODE_CHANGE_PREFIXES):
            return True
    return False


def _changed_decisions(changed_files: list[str]) -> list[str]:
    return [
        path
        for path in changed_files
        if path.startswith("docs/feature-decisions/") and path.endswith(".json")
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Feature Decision records.")
    parser.add_argument("--require-decision-for-changes", action="store_true")
    parser.add_argument("--base", default="")
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args()

    files = decision_files()
    errors: list[str] = []
    if not files:
        errors.append("docs/feature-decisions: at least one Feature Decision JSON file is required")

    registered_capabilities = _registered_capabilities()
    for path in files:
        errors.extend(validate_decision(path, registered_capabilities))

    if args.require_decision_for_changes:
        if not args.base:
            errors.append("--base is required when --require-decision-for-changes is set")
        else:
            try:
                changed_files = _changed_files(args.base, args.head)
            except subprocess.CalledProcessError as error:
                errors.append(f"failed to inspect changed files: {error.stderr.strip()}")
            else:
                if _needs_decision(changed_files) and not _changed_decisions(changed_files):
                    errors.append(
                        "code changes require a docs/feature-decisions/*.json change in the same PR"
                    )

    if errors:
        print("Feature Decision check failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Feature Decision check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
