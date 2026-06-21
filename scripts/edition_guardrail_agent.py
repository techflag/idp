#!/usr/bin/env python3
"""Edition guardrail agent.

This deterministic agent orchestrates repository checks that protect the
community/commercial boundary. It is intentionally non-LLM: CI should fail on
missing decisions, scattered edition checks, and public export leaks without
depending on a reviewer remembering the rules.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
DEFAULT_COMMUNITY_VERIFY_DIR = PROJECT_ROOT / "idp-community-export-verify"
DEFAULT_COMMUNITY_EXPORT_DIR = PROJECT_ROOT / "idp-community-export"


@dataclass(frozen=True)
class Check:
    name: str
    command: list[str]
    required: bool = True
    cwd: Path = ROOT


@dataclass(frozen=True)
class CheckResult:
    name: str
    command: list[str]
    exit_code: int
    elapsed_seconds: float
    output: str

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


def run_check(check: Check) -> CheckResult:
    started_at = time.monotonic()
    completed = subprocess.run(
        check.command,
        cwd=check.cwd,
        capture_output=True,
        text=True,
    )
    output = "\n".join(part for part in (completed.stdout.strip(), completed.stderr.strip()) if part)
    return CheckResult(
        name=check.name,
        command=check.command,
        exit_code=completed.returncode,
        elapsed_seconds=time.monotonic() - started_at,
        output=output,
    )


def build_checks(args: argparse.Namespace) -> list[Check]:
    python = sys.executable
    feature_decision_command = [python, "scripts/check_feature_decisions.py"]
    if args.require_decision_for_changes:
        feature_decision_command.extend(
            [
                "--require-decision-for-changes",
                "--base",
                args.base,
                "--head",
                args.head,
            ]
        )

    checks = [
        Check("Edition policy static check", [python, "scripts/check_edition_policy.py"]),
        Check("Feature Decision registry check", feature_decision_command),
    ]

    if args.community_export:
        checks.append(
            Check(
                "Community public export check",
                [python, "scripts/check_public_export.py", args.community_export],
            )
        )
    return checks


def run_command(name: str, command: list[str], *, cwd: Path = ROOT) -> CheckResult:
    return run_check(Check(name=name, command=command, cwd=cwd))


def print_result(result: CheckResult) -> None:
    status = "PASS" if result.passed else "FAIL"
    command = " ".join(result.command)
    print(f"[{status}] {result.name} ({result.elapsed_seconds:.2f}s)")
    print(f"  $ {command}")
    if result.output:
        for line in result.output.splitlines():
            print(f"  {line}")


def _remove_path(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def _clean_community_release_artifacts(snapshot_dir: Path) -> CheckResult:
    started_at = time.monotonic()
    removed: list[str] = []
    errors: list[str] = []
    for rel in (Path("frontend/node_modules"), Path("frontend/dist")):
        path = snapshot_dir / rel
        if not path.exists():
            continue
        try:
            shutil.rmtree(path)
            removed.append(str(rel))
        except Exception as error:  # pragma: no cover - CLI guardrail
            errors.append(f"{rel}: {error}")
    return CheckResult(
        name="Clean community release build artifacts",
        command=["cleanup", str(snapshot_dir)],
        exit_code=1 if errors else 0,
        elapsed_seconds=time.monotonic() - started_at,
        output="\n".join(errors) if errors else f"removed: {', '.join(removed) if removed else 'none'}",
    )


def _copy_public_snapshot(source: Path, target: Path) -> CheckResult:
    started_at = time.monotonic()
    if source.resolve() == target.resolve():
        return CheckResult(
            name="Sync community export",
            command=["rsync", str(source), str(target)],
            exit_code=1,
            elapsed_seconds=time.monotonic() - started_at,
            output="source and target must be different paths",
        )
    target.mkdir(parents=True, exist_ok=True)
    command = [
        "rsync",
        "-a",
        "--delete",
        "--exclude=.git",
        "--exclude=backend/.env",
        "--exclude=backend/.env.local",
        "--exclude=backend/.env.production.local",
        "--exclude=backend/.runtime",
        "--exclude=frontend/.env.local",
        "--exclude=frontend/.env.production.local",
        "--exclude=__pycache__",
        "--exclude=.pytest_cache",
        f"{source}/",
        f"{target}/",
    ]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    output = "\n".join(
        part
        for part in (
            completed.stdout.strip(),
            completed.stderr.strip(),
            f"synced to {target}" if completed.returncode == 0 else "",
        )
        if part
    )
    return CheckResult(
        name="Sync community export",
        command=command,
        exit_code=completed.returncode,
        elapsed_seconds=time.monotonic() - started_at,
        output=output,
    )


def run_community_release(args: argparse.Namespace) -> bool:
    python = sys.executable
    verify_dir = Path(args.community_verify_dir).expanduser()
    export_dir = Path(args.community_export_dir).expanduser()
    print("Community Release Preflight")
    print("===========================")

    _remove_path(verify_dir)
    release_checks = [
        run_command(
            "Export community snapshot",
            [python, "scripts/export_community_snapshot.py", str(verify_dir)],
        ),
        run_command(
            "Community public export check",
            [python, "scripts/check_public_export.py", str(verify_dir)],
        ),
        run_command(
            "Community backend tests",
            [
                python,
                "-m",
                "pytest",
                "tests/test_community_sqlite_bootstrap.py",
                "tests/test_config.py",
                "tests/test_edition_policy.py",
                "tests/test_mineru_service.py",
                "-q",
            ],
            cwd=verify_dir / "backend",
        ),
        run_command(
            "Community frontend build",
            ["bash", "-lc", "npm ci && npm run build"],
            cwd=verify_dir / "frontend",
        ),
    ]
    failed = False
    for result in release_checks:
        print_result(result)
        failed = failed or not result.passed
    if failed:
        print("Community release preflight: FAIL")
        return False

    cleanup_result = _clean_community_release_artifacts(verify_dir)
    print_result(cleanup_result)
    if not cleanup_result.passed:
        print("Community release preflight: FAIL")
        return False

    if args.sync_community_export:
        result = _copy_public_snapshot(verify_dir, export_dir)
        print_result(result)
        if not result.passed:
            print("Community release preflight: FAIL")
            return False
    else:
        print(f"Community release preflight: PASS, verify snapshot at {verify_dir}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Run edition guardrail checks.")
    parser.add_argument("--require-decision-for-changes", action="store_true")
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument(
        "--community-export",
        default="",
        help="Optional path to a generated community export snapshot to validate.",
    )
    parser.add_argument("--release-community", action="store_true", help="Export and validate a community release snapshot.")
    parser.add_argument(
        "--sync-community-export",
        action="store_true",
        help="After --release-community passes, sync the verified snapshot to the community export directory.",
    )
    parser.add_argument("--community-verify-dir", default=str(DEFAULT_COMMUNITY_VERIFY_DIR))
    parser.add_argument("--community-export-dir", default=str(DEFAULT_COMMUNITY_EXPORT_DIR))
    args = parser.parse_args()

    if args.require_decision_for_changes and not args.base:
        parser.error("--base is required with --require-decision-for-changes")

    checks = build_checks(args)
    print("Edition Guardrail Agent")
    print("=======================")
    failed = False
    for check in checks:
        result = run_check(check)
        print_result(result)
        if check.required and not result.passed:
            failed = True
    if failed:
        print("Guardrail result: FAIL")
        return 1
    if args.release_community:
        if not run_community_release(args):
            return 1
    print("Guardrail result: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
