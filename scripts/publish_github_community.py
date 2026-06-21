#!/usr/bin/env python3
"""Create and optionally push the sanitized GitHub community snapshot."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REMOTE = "https://github.com/techflag/idp.git"


def run(cmd: list[str], *, cwd: Path = ROOT, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd))
    return subprocess.run(cmd, cwd=cwd, check=check, text=True)


def ensure_git_snapshot(export_dir: Path, remote_url: str, commit_message: str) -> None:
    git_dir = export_dir / ".git"
    if not git_dir.exists():
        run(["git", "init"], cwd=export_dir)
    run(["git", "add", "."], cwd=export_dir)
    diff_result = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=export_dir)
    if diff_result.returncode == 0:
        print("No snapshot changes to commit.")
    else:
        run(["git", "commit", "-m", commit_message], cwd=export_dir)
    run(["git", "branch", "-M", "main"], cwd=export_dir)
    existing_remote = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=export_dir,
        text=True,
        capture_output=True,
    )
    if existing_remote.returncode == 0:
        run(["git", "remote", "set-url", "origin", remote_url], cwd=export_dir)
    else:
        run(["git", "remote", "add", "origin", remote_url], cwd=export_dir)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_dir", help="Directory outside this worktree for the sanitized snapshot.")
    parser.add_argument("--remote", default=DEFAULT_REMOTE, help=f"GitHub remote URL. Default: {DEFAULT_REMOTE}")
    parser.add_argument("--message", default="Initial community edition snapshot", help="Snapshot commit message.")
    parser.add_argument("--no-push", action="store_true", help="Create and verify the snapshot without pushing.")
    args = parser.parse_args(argv)

    export_dir = Path(args.export_dir).resolve()

    run(["python3", "scripts/check_edition_policy.py"])
    run(["python3", "scripts/export_community_snapshot.py", str(export_dir)])
    run(["python3", "scripts/check_public_export.py", str(export_dir)])
    run(["python3", str(export_dir / "scripts/check_edition_policy.py")], cwd=export_dir)
    ensure_git_snapshot(export_dir, args.remote, args.message)

    if args.no_push:
        print(f"Snapshot is ready at {export_dir}. Push skipped by --no-push.")
        return 0

    push = run(["git", "push", "-u", "origin", "main"], cwd=export_dir, check=False)
    if push.returncode != 0:
        print(
            "\nGitHub push failed. Authenticate with GitHub, then rerun this command "
            "or push from the export directory.",
            file=sys.stderr,
        )
        return push.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

