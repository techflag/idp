# SPDX-FileCopyrightText: 2026 TechFlag
# SPDX-License-Identifier: MIT
"""ORM models for MySQL-backed primary storage."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


@compiles(LONGTEXT, "sqlite")
def _compile_longtext_sqlite(type_, compiler, **kw) -> str:
    return "TEXT"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_ids_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class CustomerModel(Base):
    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    project_code: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class DocumentModel(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    parse_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    uploaded_by_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    uploaded_by_name: Mapped[str] = mapped_column(String(255), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    markdown_url: Mapped[Optional[str]] = mapped_column(Text)
    raw_json_url: Mapped[Optional[str]] = mapped_column(Text)
    layout_url: Mapped[Optional[str]] = mapped_column(Text)
    block_list_url: Mapped[Optional[str]] = mapped_column(Text)
    model_json_url: Mapped[Optional[str]] = mapped_column(Text)
    artifact_base_url: Mapped[Optional[str]] = mapped_column(Text)
    parse_task_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    parse_error: Mapped[Optional[str]] = mapped_column(Text)
    latest_task_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)


class TaskModel(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    task_name: Mapped[str] = mapped_column(String(255), nullable=False)
    document_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role_scope_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    upload_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    prompt_run_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)


class ParseJobModel(Base):
    __tablename__ = "parse_jobs"

    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    mineru_state: Mapped[Optional[str]] = mapped_column(String(32))
    mineru_task_id: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    extracted_pages: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_pages: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    start_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    full_zip_source_url: Mapped[Optional[str]] = mapped_column(Text)
    full_zip_path: Mapped[Optional[str]] = mapped_column(Text)
    markdown_path: Mapped[Optional[str]] = mapped_column(Text)
    raw_json_path: Mapped[Optional[str]] = mapped_column(Text)
    layout_path: Mapped[Optional[str]] = mapped_column(Text)
    block_list_path: Mapped[Optional[str]] = mapped_column(Text)
    model_json_path: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class PromptConfigModel(Base):
    __tablename__ = "prompt_configs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    prompt_name: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    start_page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    end_page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    run_purpose: Mapped[str] = mapped_column(String(32), default="parse_prompt", nullable=False, index=True)
    source_template_id: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class PromptRunModel(Base):
    __tablename__ = "prompt_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    run_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    run_name: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt_name: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    start_page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    end_page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    run_phase: Mapped[str] = mapped_column(String(32), default="queued", nullable=False, index=True)
    run_purpose: Mapped[str] = mapped_column(String(32), default="parse_prompt", nullable=False, index=True)
    prompt_config_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    template_id: Mapped[Optional[str]] = mapped_column(String(128))
    schema_template_name: Mapped[Optional[str]] = mapped_column(String(255))
    schema_template_version: Mapped[Optional[str]] = mapped_column(String(64))
    llm_provider: Mapped[Optional[str]] = mapped_column(String(128))
    llm_model: Mapped[Optional[str]] = mapped_column(String(128))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    input_path: Mapped[Optional[str]] = mapped_column(Text)
    output_path: Mapped[Optional[str]] = mapped_column(Text)
    output_text: Mapped[Optional[str]] = mapped_column(Text)
    input_facts_snapshot_json: Mapped[Optional[str]] = mapped_column(LONGTEXT)
    schema_definition_json: Mapped[Optional[str]] = mapped_column(LONGTEXT)
    schema_output_json: Mapped[Optional[str]] = mapped_column(LONGTEXT)
    validation_errors_json: Mapped[Optional[str]] = mapped_column(LONGTEXT)
    structured_extraction_result_json: Mapped[Optional[str]] = mapped_column(LONGTEXT)
    structured_process_result_json: Mapped[Optional[str]] = mapped_column(LONGTEXT)
    structured_business_result_json: Mapped[Optional[str]] = mapped_column(LONGTEXT)
    evidence_block_ids_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    evidence_excerpts_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    phase_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class LlmCallTraceModel(Base):
    __tablename__ = "llm_call_traces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    request_kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    run_phase: Mapped[str] = mapped_column(String(32), default="model_processing", nullable=False, index=True)
    provider: Mapped[Optional[str]] = mapped_column(String(128))
    model: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    skill_id: Mapped[Optional[str]] = mapped_column(String(120), index=True)
    input_chars: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_chars: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    http_ms: Mapped[Optional[int]] = mapped_column(Integer)
    total_ms: Mapped[Optional[int]] = mapped_column(Integer)
    error_type: Mapped[Optional[str]] = mapped_column(String(128))
    request_object_key: Mapped[Optional[str]] = mapped_column(Text)
    response_object_key: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    __table_args__ = (
        Index("ix_llm_call_traces_run_stage", "run_id", "stage", "request_kind"),
        Index("ix_llm_call_traces_task_created", "task_id", "created_at"),
    )


class TaskResultArtifactModel(Base):
    __tablename__ = "task_result_artifacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    page_no: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    run_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    artifact_kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    summary_json: Mapped[Optional[str]] = mapped_column(LONGTEXT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    __table_args__ = (
        Index("ix_task_result_artifacts_scope", "task_id", "stage", "artifact_kind", "page_no"),
        Index("ix_task_result_artifacts_run_kind", "task_id", "run_id", "artifact_kind"),
    )


class TaskOperationTargetModel(Base):
    __tablename__ = "task_operation_targets"

    storage_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    page_no: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    target_id: Mapped[str] = mapped_column(String(191), nullable=False, index=True)
    source_run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    value_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    excerpt: Mapped[Optional[str]] = mapped_column(Text)
    block_position: Mapped[Optional[str]] = mapped_column(Text)
    field_key: Mapped[Optional[str]] = mapped_column(String(191))
    row_index: Mapped[Optional[int]] = mapped_column(Integer)
    row_count: Mapped[Optional[int]] = mapped_column(Integer)
    column_count: Mapped[Optional[int]] = mapped_column(Integer)
    headers_json: Mapped[str] = mapped_column(LONGTEXT, default="[]", nullable=False)
    block_ids_json: Mapped[str] = mapped_column(LONGTEXT, default="[]", nullable=False)
    group_label: Mapped[Optional[str]] = mapped_column(Text)
    data_object_key: Mapped[Optional[str]] = mapped_column(Text)
    data_content_hash: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    __table_args__ = (
        Index("ux_task_operation_targets_task_target", "task_id", "target_id", unique=True),
        Index("ix_task_operation_targets_page", "task_id", "page_no"),
        Index("ix_task_operation_targets_source", "task_id", "source_run_id"),
    )


class ApplicationWorkshopStepDraftModel(Base):
    __tablename__ = "application_workshop_step_drafts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="generated", nullable=False, index=True)
    data_type_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    goal: Mapped[str] = mapped_column(LONGTEXT, default="", nullable=False)
    expected_output: Mapped[str] = mapped_column(LONGTEXT, default="", nullable=False)
    source_title: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_scope: Mapped[str] = mapped_column(Text, default="", nullable=False)
    skill_text: Mapped[str] = mapped_column(LONGTEXT, default="", nullable=False)
    skill_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    errors_json: Mapped[str] = mapped_column(LONGTEXT, default="[]", nullable=False)
    model: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    sample_source_json: Mapped[str] = mapped_column(LONGTEXT, default="{}", nullable=False)
    sample_extraction_json: Mapped[str] = mapped_column(LONGTEXT, default="{}", nullable=False)
    sample_processing_json: Mapped[str] = mapped_column(LONGTEXT, default="{}", nullable=False)
    run_option_json: Mapped[str] = mapped_column(LONGTEXT, default="{}", nullable=False)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(String(128))
    updated_by_user_id: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    __table_args__ = (
        Index("ix_application_workshop_step_drafts_task_updated", "task_id", "updated_at"),
        Index("ix_application_workshop_step_drafts_customer_updated", "customer_id", "updated_at"),
    )


class SchemaTemplateModel(Base):
    __tablename__ = "schema_templates"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    document_type: Mapped[str] = mapped_column(String(128), default="", nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(32), default="page", nullable=False, index=True)
    instructions: Mapped[str] = mapped_column(Text, default="", nullable=False)
    schema_definition_json: Mapped[str] = mapped_column(LONGTEXT, default="{}", nullable=False)
    binding_config_json: Mapped[Optional[str]] = mapped_column(LONGTEXT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class BusinessSkillModel(Base):
    __tablename__ = "business_skills"

    storage_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    skill_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(191), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(128), default="business_operation", nullable=False, index=True)
    customer_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    tags_json: Mapped[str] = mapped_column(LONGTEXT, default="[]", nullable=False)
    source_types_json: Mapped[str] = mapped_column(LONGTEXT, default="[]", nullable=False)
    target_types_json: Mapped[str] = mapped_column(LONGTEXT, default="[]", nullable=False)
    executor: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    result_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    renderer: Mapped[str] = mapped_column(String(64), default="auto", nullable=False)
    config_schema_json: Mapped[str] = mapped_column(LONGTEXT, default="{}", nullable=False)
    output_schema_json: Mapped[str] = mapped_column(LONGTEXT, default="{}", nullable=False)
    prompt_template: Mapped[str] = mapped_column(LONGTEXT, default="", nullable=False)
    examples_json: Mapped[str] = mapped_column(LONGTEXT, default="[]", nullable=False)
    defaults_json: Mapped[str] = mapped_column(LONGTEXT, default="{}", nullable=False)
    skill_text_object_key: Mapped[Optional[str]] = mapped_column(String(512))
    skill_text_hash: Mapped[Optional[str]] = mapped_column(String(64))
    skill_text_size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skill_text_preview: Mapped[Optional[str]] = mapped_column(Text)
    latest_test_status: Mapped[Optional[str]] = mapped_column(String(32))
    sample_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    test_run_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_tested_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[Optional[str]] = mapped_column(String(128))
    updated_by: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class SkillSampleModel(Base):
    __tablename__ = "skill_samples"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    skill_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    instruction: Mapped[str] = mapped_column(Text, default="", nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), default="text/plain", nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), default="sample.txt", nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    preview: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class SkillTestRunModel(Base):
    __tablename__ = "skill_test_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    skill_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    sample_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="completed", nullable=False)
    valid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    errors_json: Mapped[str] = mapped_column(LONGTEXT, default="[]", nullable=False)
    summary_json: Mapped[Optional[str]] = mapped_column(LONGTEXT)
    input_object_key: Mapped[Optional[str]] = mapped_column(String(512))
    result_object_key: Mapped[Optional[str]] = mapped_column(String(512))
    facts_object_key: Mapped[Optional[str]] = mapped_column(String(512))
    llm_object_key: Mapped[Optional[str]] = mapped_column(String(512))
    result_json: Mapped[Optional[str]] = mapped_column(LONGTEXT)
    facts_json: Mapped[Optional[str]] = mapped_column(LONGTEXT)
    provider: Mapped[Optional[str]] = mapped_column(String(64))
    model: Mapped[Optional[str]] = mapped_column(String(128))
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    input_chars: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_chars: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class ApplicationModel(Base):
    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(32), default="private", nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    document_type: Mapped[str] = mapped_column(String(128), default="", nullable=False, index=True)
    scenario: Mapped[str] = mapped_column(Text, default="", nullable=False)
    cover_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    release_notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False, index=True)
    default_version: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    latest_published_version: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    source_task_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    source_document_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    step_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(String(128))
    created_by_name: Mapped[Optional[str]] = mapped_column(String(255))
    updated_by_user_id: Mapped[Optional[str]] = mapped_column(String(128))
    updated_by_name: Mapped[Optional[str]] = mapped_column(String(255))
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class ApplicationVersionModel(Base):
    __tablename__ = "application_versions"

    storage_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    document_type: Mapped[str] = mapped_column(String(128), default="", nullable=False, index=True)
    scenario: Mapped[str] = mapped_column(Text, default="", nullable=False)
    cover_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    release_notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="published", nullable=False, index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_task_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    source_document_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    step_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    published_by_user_id: Mapped[Optional[str]] = mapped_column(String(128))
    published_by_name: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class ApplicationStepModel(Base):
    __tablename__ = "application_steps"

    storage_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_label: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    skill_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    skill_version: Mapped[str] = mapped_column(String(64), nullable=False)
    skill_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    source_task_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    source_document_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    source_page_no: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    source_run_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    source_status: Mapped[Optional[str]] = mapped_column(String(32))
    run_purpose: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    operation_type: Mapped[Optional[str]] = mapped_column(String(32))
    result_mode: Mapped[Optional[str]] = mapped_column(String(32))
    skill_snapshot_json: Mapped[str] = mapped_column(LONGTEXT, default="{}", nullable=False)
    config_snapshot_json: Mapped[str] = mapped_column(LONGTEXT, default="{}", nullable=False)
    prompt_snapshot: Mapped[str] = mapped_column(LONGTEXT, default="", nullable=False)
    input_mapping_json: Mapped[str] = mapped_column(LONGTEXT, default="{}", nullable=False)
    target_mapping_json: Mapped[str] = mapped_column(LONGTEXT, default="{}", nullable=False)
    dependency_refs_json: Mapped[str] = mapped_column(LONGTEXT, default="{}", nullable=False)
    output_summary_json: Mapped[str] = mapped_column(LONGTEXT, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class ApplicationRunModel(Base):
    __tablename__ = "application_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="running", nullable=False, index=True)
    step_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_step_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    triggered_by_user_id: Mapped[Optional[str]] = mapped_column(String(128))
    triggered_by_name: Mapped[Optional[str]] = mapped_column(String(255))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class ApplicationRunStepModel(Base):
    __tablename__ = "application_run_steps"

    storage_id: Mapped[str] = mapped_column(String(191), primary_key=True)
    application_run_id: Mapped[str] = mapped_column(
        ForeignKey("application_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    skill_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    skill_version: Mapped[str] = mapped_column(String(64), nullable=False)
    skill_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    source_application_step_id: Mapped[Optional[str]] = mapped_column(String(191), index=True)
    source_page_no: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    source_run_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    execution_run_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="running", nullable=False, index=True)
    input_mapping_json: Mapped[str] = mapped_column(LONGTEXT, default="{}", nullable=False)
    target_mapping_json: Mapped[str] = mapped_column(LONGTEXT, default="{}", nullable=False)
    config_snapshot_json: Mapped[str] = mapped_column(LONGTEXT, default="{}", nullable=False)
    prompt_snapshot: Mapped[str] = mapped_column(LONGTEXT, default="", nullable=False)
    output_summary_json: Mapped[str] = mapped_column(LONGTEXT, default="{}", nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


Index("ix_documents_customer_updated", DocumentModel.customer_id, DocumentModel.updated_at)
Index("ix_tasks_customer_updated", TaskModel.customer_id, TaskModel.updated_at)
Index("ix_tasks_task_scope", TaskModel.document_id, TaskModel.owner_user_id)
Index(
    "ix_prompt_configs_task_scope",
    PromptConfigModel.task_id,
    PromptConfigModel.start_page_no,
    PromptConfigModel.end_page_no,
)
Index(
    "ix_prompt_runs_task_scope_updated",
    PromptRunModel.task_id,
    PromptRunModel.start_page_no,
    PromptRunModel.end_page_no,
    PromptRunModel.updated_at,
)
Index("ix_prompt_runs_task_type", PromptRunModel.task_id, PromptRunModel.run_type)
Index("ux_business_skills_scope", BusinessSkillModel.customer_id, BusinessSkillModel.skill_id, BusinessSkillModel.version, unique=True)
Index("ix_business_skills_status", BusinessSkillModel.category, BusinessSkillModel.status, BusinessSkillModel.customer_id)
Index("ix_skill_samples_scope_updated", SkillSampleModel.kind, SkillSampleModel.customer_id, SkillSampleModel.skill_id, SkillSampleModel.updated_at)
Index("ix_skill_test_runs_scope_updated", SkillTestRunModel.kind, SkillTestRunModel.customer_id, SkillTestRunModel.skill_id, SkillTestRunModel.updated_at)
Index("ix_applications_customer_status", ApplicationModel.customer_id, ApplicationModel.status, ApplicationModel.updated_at)
Index("ux_application_versions_scope", ApplicationVersionModel.application_id, ApplicationVersionModel.version, unique=True)
Index("ix_application_versions_default", ApplicationVersionModel.application_id, ApplicationVersionModel.is_default, ApplicationVersionModel.published_at)
Index("ux_application_steps_scope", ApplicationStepModel.application_id, ApplicationStepModel.version_label, ApplicationStepModel.step_order, unique=True)
Index("ix_application_steps_run", ApplicationStepModel.application_id, ApplicationStepModel.version_label, ApplicationStepModel.kind)
Index("ix_application_runs_scope", ApplicationRunModel.application_id, ApplicationRunModel.task_id, ApplicationRunModel.created_at)
Index("ux_application_run_steps_scope", ApplicationRunStepModel.application_run_id, ApplicationRunStepModel.step_order, unique=True)
