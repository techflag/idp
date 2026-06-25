# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""Shared SKILL.md parsing and constrained script validation."""

from __future__ import annotations

import ast
from dataclasses import dataclass
import re
from typing import Any

import yaml


ALLOWED_SKILL_EXECUTORS = {
    "llm_structured",
    "local_transform",
    "quality_check",
    "export_data",
    "http_connector",
    "controlled_python",
    "external_connector",
}


@dataclass(frozen=True)
class ParsedSkillMarkdown:
    frontmatter: dict[str, Any]
    body: str
    text: str


def parse_skill_markdown(markdown_text: str) -> ParsedSkillMarkdown:
    text = markdown_text.strip()
    if not text.startswith("---"):
        raise ValueError("SKILL.md 必须以 frontmatter 开头。")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError("SKILL.md frontmatter 未闭合。")
    raw_frontmatter = parts[1].strip()
    body = parts[2].strip()
    if not raw_frontmatter:
        raise ValueError("SKILL.md frontmatter 不能为空。")
    try:
        payload = yaml.safe_load(raw_frontmatter) or {}
    except yaml.YAMLError as exc:
        repaired_frontmatter = _drop_redundant_required_sequence(raw_frontmatter)
        try:
            payload = yaml.safe_load(repaired_frontmatter) or {}
        except yaml.YAMLError:
            repaired = _move_frontmatter_rules_to_body(repaired_frontmatter, body)
            if not repaired:
                raise ValueError(f"SKILL.md frontmatter 解析失败：{exc}") from exc
            repaired_frontmatter, repaired_body = repaired
            try:
                payload = yaml.safe_load(repaired_frontmatter) or {}
            except yaml.YAMLError:
                raise ValueError(f"SKILL.md frontmatter 解析失败：{exc}") from exc
            body = repaired_body.strip()
        text = f"---\n{repaired_frontmatter.strip()}\n---\n\n{body}".strip()
    if not isinstance(payload, dict):
        raise ValueError("SKILL.md frontmatter 顶层必须是对象。")
    return ParsedSkillMarkdown(frontmatter=payload, body=body, text=text)


def extract_fenced_code(markdown_body: str, language: str) -> str:
    pattern = re.compile(rf"```{re.escape(language)}\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
    match = pattern.search(markdown_body)
    return match.group(1).strip() if match else ""


def _drop_redundant_required_sequence(raw_frontmatter: str) -> str:
    lines = raw_frontmatter.splitlines()
    kept: list[str] = []
    skip_child_indent: int | None = None
    changed = False
    for line in lines:
        if skip_child_indent is not None:
            stripped = line.strip()
            if not stripped:
                changed = True
                continue
            indent = len(line) - len(line.lstrip(" "))
            if indent > skip_child_indent:
                changed = True
                continue
            skip_child_indent = None

        kept.append(line)
        match = re.match(r"^(\s*)required\s*:\s*(.+?)\s*(?:#.*)?$", line)
        if match and match.group(2).strip():
            skip_child_indent = len(match.group(1))
    return "\n".join(kept) if changed else raw_frontmatter


def _move_frontmatter_rules_to_body(raw_frontmatter: str, body: str) -> tuple[str, str] | None:
    lines = raw_frontmatter.splitlines()
    kept: list[str] = []
    rule_lines: list[str] = []
    in_rules = False
    found_rules = False
    for line in lines:
        if not in_rules and re.match(r"^rules\s*:\s*(?:#.*)?$", line):
            in_rules = True
            found_rules = True
            continue
        if in_rules:
            if re.match(r"^[A-Za-z_][\w-]*\s*:", line):
                in_rules = False
                kept.append(line)
            else:
                rule_lines.append(line)
            continue
        kept.append(line)
    if not found_rules:
        return None
    cleaned_rules = "\n".join(
        line[2:] if line.startswith("  ") else line
        for line in rule_lines
    ).strip()
    if not cleaned_rules:
        return "\n".join(kept), body
    if re.search(r"(?m)^#\s+规则\s*$", body):
        repaired_body = body
    elif re.search(r"(?m)^#\s+输出格式\s*$", body):
        repaired_body = re.sub(
            r"(?m)^#\s+输出格式\s*$",
            f"# 规则\n\n{cleaned_rules}\n\n# 输出格式",
            body,
            count=1,
        )
    else:
        repaired_body = f"{body.rstrip()}\n\n# 规则\n\n{cleaned_rules}"
    return "\n".join(kept), repaired_body


def extract_markdown_rules(markdown_body: str) -> list[str]:
    body = str(markdown_body or "")
    match = re.search(r"(?m)^#\s+规则\s*\n([\s\S]*?)(?=\n#\s+|\Z)", body)
    if not match:
        return []
    rules: list[str] = []
    for line in match.group(1).splitlines():
        value = re.match(r"^\s*(?:[-*]|\d+[.)])\s+(.+?)\s*$", line)
        if value:
            rules.append(value.group(1).strip())
    return rules


def validate_controlled_python_code(code: str) -> None:
    if not code.strip():
        raise ValueError("controlled_python Skill 缺少 Python 代码块。")
    if len(code.encode("utf-8")) > 32_000:
        raise ValueError("controlled_python 代码过大，限制为 32KB。")
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ValueError(f"controlled_python 代码语法错误：{exc}") from exc

    dangerous_names = {
        "__import__",
        "compile",
        "eval",
        "exec",
        "globals",
        "input",
        "locals",
        "open",
        "vars",
    }
    dangerous_attrs = {
        "connect",
        "environ",
        "getenv",
        "popen",
        "remove",
        "rmdir",
        "rmtree",
        "socket",
        "system",
        "unlink",
    }
    has_run = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise ValueError("controlled_python 不允许 import；第三方接口请使用 http_connector。")
        if isinstance(node, ast.FunctionDef) and node.name == "run":
            has_run = True
        if isinstance(node, ast.Name) and node.id in dangerous_names:
            raise ValueError(f"controlled_python 不允许使用 {node.id}。")
        if isinstance(node, ast.Attribute) and node.attr in dangerous_attrs:
            raise ValueError(f"controlled_python 不允许访问属性 {node.attr}。")
    if not has_run:
        raise ValueError("controlled_python 必须定义 run(input, config, context)。")


def as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        source = value.splitlines() if "\n" in value else value.split(",")
        return [item.strip() for item in source if item.strip()]
    return []
