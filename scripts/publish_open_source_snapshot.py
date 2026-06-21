#!/usr/bin/env python3
"""Create GitHub and Gitee open-source community snapshots."""

from __future__ import annotations

import argparse
import datetime as dt
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
DEFAULT_GITHUB_REMOTE = "https://github.com/techflag/idp.git"
DEFAULT_GITEE_REMOTE = "https://gitee.com/techflag/idp.git"
DEFAULT_GITHUB_EXPORT_DIR = PROJECT_ROOT / "idp-community-export-github"
DEFAULT_GITEE_EXPORT_DIR = PROJECT_ROOT / "idp-community-export-gitee"

TOKEN_MARKERS = (
    "github_pat_",
    "ghp_",
    "gho_",
    "ghu_",
    "glpat-",
)


def default_tag() -> str:
    return f"v{dt.date.today().strftime('%Y%m%d')}"


def run(command: list[str], *, cwd: Path = ROOT, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(command))
    return subprocess.run(command, cwd=cwd, check=check, text=True)


def run_capture(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True)


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def validate_tag(tag: str) -> None:
    if not re.fullmatch(r"v\d{8}", tag):
        fail(f"tag must use vYYYYMMDD format, got: {tag}")


def validate_remote(name: str, url: str) -> None:
    lower = url.lower()
    if any(marker in lower for marker in TOKEN_MARKERS):
        fail(f"{name} remote must not contain an access token")
    if re.match(r"https://[^/\s]+@", url):
        fail(f"{name} remote must not embed credentials")


def ensure_outside_worktree(path: Path) -> None:
    resolved = path.resolve()
    if resolved == ROOT or ROOT in resolved.parents:
        fail(f"export directory must be outside the development worktree: {resolved}")


def prepare_target(target: Path) -> None:
    ensure_outside_worktree(target)
    target.mkdir(parents=True, exist_ok=True)
    for child in target.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def copy_snapshot(source: Path, target: Path) -> None:
    prepare_target(target)
    for item in source.rglob("*"):
        rel = item.relative_to(source)
        if ".git" in rel.parts or item.is_dir():
            continue
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, destination)


def clean_generated_artifacts(snapshot_dir: Path) -> None:
    remove_dirs = [
        snapshot_dir / "frontend" / "node_modules",
        snapshot_dir / "frontend" / "dist",
        snapshot_dir / "backend" / ".runtime",
        snapshot_dir / "frontend" / ".vite",
    ]
    for directory in remove_dirs:
        if directory.exists():
            shutil.rmtree(directory)
    for path in snapshot_dir.rglob("*"):
        if path.is_dir() and path.name in {"__pycache__", ".pytest_cache"}:
            shutil.rmtree(path)
            continue
        if path.is_file() and (path.suffix in {".pyc", ".pyo"} or path.name.endswith(".tsbuildinfo")):
            path.unlink()


def ensure_release_notes(snapshot_dir: Path, tag: str) -> None:
    notes_dir = snapshot_dir / "docs" / "releases"
    notes_dir.mkdir(parents=True, exist_ok=True)
    english = notes_dir / f"{tag}.md"
    chinese = notes_dir / f"{tag}.zh-CN.md"
    if not english.exists():
        english.write_text(
            f"# TechFlag IDP Community {tag}\n\n"
            "This release publishes the sanitized TechFlag IDP community snapshot.\n",
            encoding="utf-8",
        )
    if not chinese.exists():
        chinese.write_text(
            f"# TechFlag IDP 社区版 {tag}\n\n"
            "这个版本发布 TechFlag IDP 社区版公开快照。\n",
            encoding="utf-8",
        )


def apply_github_readme(snapshot_dir: Path) -> None:
    ensure_release_notes(snapshot_dir, current_tag)


def apply_gitee_readme(snapshot_dir: Path) -> None:
    readme = snapshot_dir / "README.md"
    readme_zh = snapshot_dir / "README.zh-CN.md"
    readme_en = snapshot_dir / "README.en-US.md"
    if not readme.exists() or not readme_zh.exists():
        fail("README.md and README.zh-CN.md are required before creating the Gitee variant")

    english = readme.read_text(encoding="utf-8")
    chinese = readme_zh.read_text(encoding="utf-8")
    english = english.replace("[中文 README](README.zh-CN.md)", "[中文 README](README.md)")
    english = english.replace(
        "[Gitee Mirror](https://gitee.com/techflag/idp)",
        "[GitHub Mirror](https://github.com/techflag/idp)",
    )
    chinese = chinese.replace("[English README](README.md)", "[English README](README.en-US.md)")

    readme_en.write_text(english, encoding="utf-8")
    readme.write_text(chinese, encoding="utf-8")
    readme_zh.unlink()
    ensure_release_notes(snapshot_dir, current_tag)


def run_public_checks(snapshot_dir: Path) -> None:
    run([sys.executable, "scripts/check_public_export.py", str(snapshot_dir)])
    run([sys.executable, "scripts/edition_guardrail_agent.py"], cwd=snapshot_dir)


def build_frontend(snapshot_dir: Path) -> None:
    frontend_dir = snapshot_dir / "frontend"
    run(["bash", "-lc", "npm ci && npm run build"], cwd=frontend_dir)
    clean_generated_artifacts(snapshot_dir)


def ensure_git_snapshot(snapshot_dir: Path, remote_url: str, commit_message: str, tag: str) -> None:
    if not (snapshot_dir / ".git").exists():
        run(["git", "init"], cwd=snapshot_dir)
    run(["git", "add", "."], cwd=snapshot_dir)
    diff_result = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=snapshot_dir)
    if diff_result.returncode == 0:
        print(f"No snapshot changes to commit in {snapshot_dir}.")
    else:
        run(["git", "commit", "-m", commit_message], cwd=snapshot_dir)
    run(["git", "branch", "-M", "main"], cwd=snapshot_dir)
    existing_remote = run_capture(["git", "remote", "get-url", "origin"], cwd=snapshot_dir)
    if existing_remote.returncode == 0:
        run(["git", "remote", "set-url", "origin", remote_url], cwd=snapshot_dir)
    else:
        run(["git", "remote", "add", "origin", remote_url], cwd=snapshot_dir)
    ensure_tag(snapshot_dir, tag)


def ensure_tag(snapshot_dir: Path, tag: str) -> None:
    head = run_capture(["git", "rev-parse", "HEAD"], cwd=snapshot_dir)
    if head.returncode != 0:
        fail(f"cannot resolve HEAD in {snapshot_dir}")
    head_sha = head.stdout.strip()
    existing = run_capture(["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"], cwd=snapshot_dir)
    if existing.returncode == 0:
        existing_commit = run_capture(["git", "rev-list", "-n", "1", tag], cwd=snapshot_dir)
        if existing_commit.stdout.strip() != head_sha:
            fail(f"{snapshot_dir}: tag {tag} already exists on another commit; use a new date tag")
        print(f"Tag {tag} already points at HEAD in {snapshot_dir}.")
        return
    run(["git", "tag", "-a", tag, "-m", f"TechFlag IDP Community {tag}"], cwd=snapshot_dir)


def push_snapshot(snapshot_dir: Path, tag: str) -> None:
    run(["git", "push", "-u", "origin", "main"], cwd=snapshot_dir)
    run(["git", "push", "origin", tag], cwd=snapshot_dir)


def print_release_help(github_export_dir: Path, tag: str) -> None:
    print("\nGitHub release command:")
    print(f"cd {github_export_dir}")
    print(
        "gh release create "
        f"{tag} --repo techflag/idp "
        f"--title \"TechFlag IDP Community {tag}\" "
        f"--notes-file docs/releases/{tag}.md --verify-tag --latest"
    )
    print("\nGitee release note:")
    print(f"Use docs/releases/{tag}.zh-CN.md as the Gitee release description.")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--github-export-dir", default=str(DEFAULT_GITHUB_EXPORT_DIR))
    parser.add_argument("--gitee-export-dir", default=str(DEFAULT_GITEE_EXPORT_DIR))
    parser.add_argument("--github-remote", default=DEFAULT_GITHUB_REMOTE)
    parser.add_argument("--gitee-remote", default=DEFAULT_GITEE_REMOTE)
    parser.add_argument("--tag", default=default_tag())
    parser.add_argument("--message", default="")
    parser.add_argument("--no-push", action="store_true")
    parser.add_argument("--skip-build", action="store_true", help="Skip the frontend build preflight.")
    args = parser.parse_args(argv)

    global current_tag
    current_tag = args.tag

    validate_tag(args.tag)
    validate_remote("GitHub", args.github_remote)
    validate_remote("Gitee", args.gitee_remote)

    github_export_dir = Path(args.github_export_dir).expanduser().resolve()
    gitee_export_dir = Path(args.gitee_export_dir).expanduser().resolve()
    commit_message = args.message or f"Publish community snapshot {args.tag}"

    with tempfile.TemporaryDirectory(prefix="idp-open-source-base-") as temp_dir:
        base_dir = Path(temp_dir) / "snapshot"
        run([sys.executable, "scripts/check_edition_policy.py"])
        run([sys.executable, "scripts/export_community_snapshot.py", str(base_dir)])
        clean_generated_artifacts(base_dir)
        run([sys.executable, "scripts/check_public_export.py", str(base_dir)])

        copy_snapshot(base_dir, github_export_dir)
        apply_github_readme(github_export_dir)

        copy_snapshot(base_dir, gitee_export_dir)
        apply_gitee_readme(gitee_export_dir)

    if not args.skip_build:
        build_frontend(github_export_dir)

    clean_generated_artifacts(github_export_dir)
    clean_generated_artifacts(gitee_export_dir)
    run_public_checks(github_export_dir)
    run_public_checks(gitee_export_dir)

    ensure_git_snapshot(github_export_dir, args.github_remote, commit_message, args.tag)
    ensure_git_snapshot(gitee_export_dir, args.gitee_remote, commit_message, args.tag)

    if args.no_push:
        print(f"Snapshots are ready. Push skipped by --no-push:\n- {github_export_dir}\n- {gitee_export_dir}")
        print_release_help(github_export_dir, args.tag)
        return 0

    push_snapshot(github_export_dir, args.tag)
    push_snapshot(gitee_export_dir, args.tag)
    print_release_help(github_export_dir, args.tag)
    return 0


current_tag = default_tag()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
