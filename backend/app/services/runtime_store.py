# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""Disk-backed state and artifact persistence for runtime-created records."""

from __future__ import annotations

import json
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.core.config import AppSettings
from app.domain.models import CustomerRecord, DocumentRecord, ParseJobRecord, PromptConfigRecord, PromptRunRecord, TaskRecord


@dataclass
class RuntimeStateSnapshot:
    customers: list[CustomerRecord]
    documents: list[DocumentRecord]
    tasks: list[TaskRecord]
    parseJobs: list[ParseJobRecord]
    promptConfigs: list[PromptConfigRecord]
    promptRuns: list[PromptRunRecord]


class JsonRuntimeStore:
    """Persist mutable backend state and extracted artifacts under `.runtime/`."""

    def __init__(self, settings: AppSettings) -> None:
        self._root = settings.runtime_data_dir
        self._state_dir = self._root / "state"
        self._artifacts_dir = self._root / "artifacts"
        self._logs_dir = self._root / "logs"
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._logs_dir.mkdir(parents=True, exist_ok=True)

    def load_state(self) -> RuntimeStateSnapshot:
        return RuntimeStateSnapshot(
            customers=self._load_records("customers.json", CustomerRecord),
            documents=self._load_records("documents.json", DocumentRecord),
            tasks=self._load_records("tasks.json", TaskRecord),
            parseJobs=self._load_records("parse_jobs.json", ParseJobRecord),
            promptConfigs=self._load_records("prompt_configs.json", PromptConfigRecord),
            promptRuns=self._load_records("prompt_runs.json", PromptRunRecord),
        )

    def save_state(
        self,
        *,
        customers: list[CustomerRecord],
        documents: list[DocumentRecord],
        tasks: list[TaskRecord],
        parseJobs: list[ParseJobRecord],
        promptConfigs: list[PromptConfigRecord],
        promptRuns: list[PromptRunRecord],
    ) -> None:
        self._write_records("customers.json", customers)
        self._write_records("documents.json", documents)
        self._write_records("tasks.json", tasks)
        self._write_records("parse_jobs.json", parseJobs)
        self._write_records("prompt_configs.json", promptConfigs)
        self._write_records("prompt_runs.json", promptRuns)

    def persist_result_bundle(self, taskId: str, bundle: bytes) -> dict[str, str]:
        """Extract the MinerU zip and return relative paths for known artifacts."""

        task_root = self._artifacts_dir / taskId
        extracted_dir = task_root / "bundle"
        extracted_dir.mkdir(parents=True, exist_ok=True)
        bundle_path = task_root / "result.zip"
        bundle_path.write_bytes(bundle)

        with zipfile.ZipFile(bundle_path) as archive:
            archive.extractall(extracted_dir)

        return {
            "fullZipPath": self._relative_to_root(bundle_path),
            "markdownPath": self._find_known_artifact(extracted_dir, {"full.md"}),
            "rawJsonPath": self._find_known_artifact(extracted_dir, {"content_list_v2.json"}, suffix="_content_list_v2.json"),
            "layoutPath": self._find_known_artifact(extracted_dir, {"layout.json", "middle.json"}),
            "blockListPath": self._find_known_artifact(extracted_dir, {"block_list.json"}),
            "modelJsonPath": self._find_known_artifact(extracted_dir, {"model.json"}, suffix="_model.json"),
        }

    def resolve_artifact_path(self, taskId: str, artifactPath: str) -> Path:
        task_root = (self._artifacts_dir / taskId).resolve()
        target = (task_root / artifactPath).resolve()
        target.relative_to(task_root)
        return target

    def read_json_artifact(self, relativePath: str | None) -> Any:
        if not relativePath:
            return None
        path = self._root / relativePath
        return json.loads(path.read_text(encoding="utf-8"))

    def read_text_artifact(self, relativePath: str | None) -> str | None:
        if not relativePath:
            return None
        path = self._root / relativePath
        return path.read_text(encoding="utf-8")

    def write_json_artifact(self, taskId: str, category: str, fileName: str, payload: Any) -> str:
        target = self._artifacts_dir / taskId / category / fileName
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._relative_to_root(target)

    def write_text_artifact(self, taskId: str, category: str, fileName: str, content: str) -> str:
        target = self._artifacts_dir / taskId / category / fileName
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return self._relative_to_root(target)

    def write_json_log(self, category: str, taskId: str, fileName: str, payload: Any) -> str:
        target = self._logs_dir / category / taskId / fileName
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._relative_to_root(target)

    def write_text_log(self, category: str, taskId: str, fileName: str, content: str) -> str:
        target = self._logs_dir / category / taskId / fileName
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return self._relative_to_root(target)

    def _find_known_artifact(self, extracted_dir: Path, exact_names: set[str], suffix: str | None = None) -> str | None:
        for path in extracted_dir.rglob("*"):
            if not path.is_file():
                continue
            if path.name in exact_names:
                return self._relative_to_root(path)
            if suffix and path.name.endswith(suffix):
                return self._relative_to_root(path)
        return None

    def _relative_to_root(self, path: Path) -> str:
        return str(path.resolve().relative_to(self._root.resolve()))

    def _load_records(self, file_name: str, record_type: type[Any]) -> list[Any]:
        path = self._state_dir / file_name
        if not path.exists():
            return []
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [record_type(**item) for item in raw]

    def _write_records(self, file_name: str, records: list[Any]) -> None:
        path = self._state_dir / file_name
        payload = [asdict(record) for record in records]
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
            encoding="utf-8",
        )


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")
