from __future__ import annotations

import re
from pathlib import Path


RUNTIME_ROOT = Path(__file__).resolve().parents[1] / "app"

FORBIDDEN_LITERALS = (
    "APPLICATION_FIELD_ALIASES",
    "SUPPLIER_ALIASES",
    "ORDER_FIELD_BOUNDARY_LABELS",
    "1.1项⽬推荐",
    "1.1项目推荐",
    "初诊病历",
    "项目推荐智能体",
    "项⽬推荐智能体",
)

FORBIDDEN_PATTERNS = (
    re.compile(r"(?m)^\s*[A-Z_]*(?:APPLICATION|SUPPLIER|ORDER|CONTRACT)[A-Z_]*(?:ALIASES|BOUNDARY_LABELS)\s*[:=]"),
    re.compile(r"""if\s+[^:\n]*(?:field|label|name)[^:\n]*==\s*["']供应商["']"""),
    re.compile(r"""if\s+[^:\n]*["']卖方["'][^:\n]*\s+in\s+[^:\n]*:"""),
    re.compile(r"""["']供应商["']\s*:\s*\["""),
)


def test_runtime_code_does_not_add_business_field_aliases() -> None:
    offenders: list[str] = []
    for path in sorted(RUNTIME_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for literal in FORBIDDEN_LITERALS:
            if literal in text:
                offenders.append(f"{path.relative_to(RUNTIME_ROOT)} contains {literal}")
        for pattern in FORBIDDEN_PATTERNS:
            if pattern.search(text):
                offenders.append(f"{path.relative_to(RUNTIME_ROOT)} matches {pattern.pattern}")

    assert not offenders, "业务语义应写入 Skill.md/评测集，不应写入 runtime 代码：\n" + "\n".join(offenders)
