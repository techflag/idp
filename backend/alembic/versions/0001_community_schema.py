"""Create the community edition baseline schema.

Revision ID: 0001_community_schema
Revises:
Create Date: 2026-06-21 00:00:01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_community_schema"
down_revision = None
branch_labels = None
depends_on = None

COMMUNITY_SCHEMA_BASELINE = "COMMUNITY_SCHEMA_BASELINE"


def upgrade() -> None:
    op.create_table('business_skills',
    sa.Column('storage_id', sa.String(length=191), nullable=False),
    sa.Column('skill_id', sa.String(length=120), nullable=False),
    sa.Column('version', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=191), nullable=False),
    sa.Column('category', sa.String(length=128), nullable=False),
    sa.Column('customer_id', sa.String(length=64), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('tags_json', sa.Text(), nullable=False),
    sa.Column('source_types_json', sa.Text(), nullable=False),
    sa.Column('target_types_json', sa.Text(), nullable=False),
    sa.Column('executor', sa.String(length=64), nullable=False),
    sa.Column('result_kind', sa.String(length=32), nullable=False),
    sa.Column('renderer', sa.String(length=64), nullable=False),
    sa.Column('config_schema_json', sa.Text(), nullable=False),
    sa.Column('output_schema_json', sa.Text(), nullable=False),
    sa.Column('prompt_template', sa.Text(), nullable=False),
    sa.Column('examples_json', sa.Text(), nullable=False),
    sa.Column('defaults_json', sa.Text(), nullable=False),
    sa.Column('skill_text_object_key', sa.String(length=512), nullable=True),
    sa.Column('skill_text_hash', sa.String(length=64), nullable=True),
    sa.Column('skill_text_size_bytes', sa.Integer(), nullable=False),
    sa.Column('skill_text_preview', sa.Text(), nullable=True),
    sa.Column('latest_test_status', sa.String(length=32), nullable=True),
    sa.Column('sample_count', sa.Integer(), nullable=False),
    sa.Column('test_run_count', sa.Integer(), nullable=False),
    sa.Column('last_tested_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.String(length=128), nullable=True),
    sa.Column('updated_by', sa.String(length=128), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('storage_id')
    )
    op.create_index(op.f('ix_business_skills_category'), 'business_skills', ['category'], unique=False)
    op.create_index(op.f('ix_business_skills_customer_id'), 'business_skills', ['customer_id'], unique=False)
    op.create_index(op.f('ix_business_skills_executor'), 'business_skills', ['executor'], unique=False)
    op.create_index(op.f('ix_business_skills_name'), 'business_skills', ['name'], unique=False)
    op.create_index(op.f('ix_business_skills_skill_id'), 'business_skills', ['skill_id'], unique=False)
    op.create_index('ix_business_skills_status', 'business_skills', ['category', 'status', 'customer_id'], unique=False)
    op.create_index('ux_business_skills_scope', 'business_skills', ['customer_id', 'skill_id', 'version'], unique=True)
    op.create_table('customers',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('project_code', sa.String(length=128), nullable=False),
    sa.Column('owner', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_customers_project_code'), 'customers', ['project_code'], unique=False)
    op.create_table('schema_templates',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('document_type', sa.String(length=128), nullable=False),
    sa.Column('scope', sa.String(length=32), nullable=False),
    sa.Column('instructions', sa.Text(), nullable=False),
    sa.Column('schema_definition_json', sa.Text(), nullable=False),
    sa.Column('binding_config_json', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_schema_templates_document_type'), 'schema_templates', ['document_type'], unique=False)
    op.create_index(op.f('ix_schema_templates_name'), 'schema_templates', ['name'], unique=False)
    op.create_index(op.f('ix_schema_templates_scope'), 'schema_templates', ['scope'], unique=False)
    op.create_table('skill_samples',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('skill_id', sa.String(length=120), nullable=False),
    sa.Column('version', sa.String(length=64), nullable=False),
    sa.Column('customer_id', sa.String(length=64), nullable=True),
    sa.Column('instruction', sa.Text(), nullable=False),
    sa.Column('object_key', sa.String(length=512), nullable=False),
    sa.Column('content_type', sa.String(length=128), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('preview', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_skill_samples_customer_id'), 'skill_samples', ['customer_id'], unique=False)
    op.create_index(op.f('ix_skill_samples_kind'), 'skill_samples', ['kind'], unique=False)
    op.create_index('ix_skill_samples_scope_updated', 'skill_samples', ['kind', 'customer_id', 'skill_id', 'updated_at'], unique=False)
    op.create_index(op.f('ix_skill_samples_skill_id'), 'skill_samples', ['skill_id'], unique=False)
    op.create_table('skill_test_runs',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('skill_id', sa.String(length=120), nullable=False),
    sa.Column('version', sa.String(length=64), nullable=False),
    sa.Column('customer_id', sa.String(length=64), nullable=True),
    sa.Column('sample_id', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('valid', sa.Boolean(), nullable=False),
    sa.Column('errors_json', sa.Text(), nullable=False),
    sa.Column('summary_json', sa.Text(), nullable=True),
    sa.Column('input_object_key', sa.String(length=512), nullable=True),
    sa.Column('result_object_key', sa.String(length=512), nullable=True),
    sa.Column('facts_object_key', sa.String(length=512), nullable=True),
    sa.Column('llm_object_key', sa.String(length=512), nullable=True),
    sa.Column('result_json', sa.Text(), nullable=True),
    sa.Column('facts_json', sa.Text(), nullable=True),
    sa.Column('provider', sa.String(length=64), nullable=True),
    sa.Column('model', sa.String(length=128), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('input_chars', sa.Integer(), nullable=False),
    sa.Column('output_chars', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_skill_test_runs_customer_id'), 'skill_test_runs', ['customer_id'], unique=False)
    op.create_index(op.f('ix_skill_test_runs_kind'), 'skill_test_runs', ['kind'], unique=False)
    op.create_index(op.f('ix_skill_test_runs_sample_id'), 'skill_test_runs', ['sample_id'], unique=False)
    op.create_index('ix_skill_test_runs_scope_updated', 'skill_test_runs', ['kind', 'customer_id', 'skill_id', 'updated_at'], unique=False)
    op.create_index(op.f('ix_skill_test_runs_skill_id'), 'skill_test_runs', ['skill_id'], unique=False)
    op.create_table('users',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('username', sa.String(length=128), nullable=False),
    sa.Column('password_hash', sa.Text(), nullable=False),
    sa.Column('role', sa.String(length=32), nullable=False),
    sa.Column('display_name', sa.String(length=255), nullable=False),
    sa.Column('customer_ids_json', sa.Text(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)
    op.create_table('applications',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('customer_id', sa.String(length=64), nullable=False),
    sa.Column('scope', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('document_type', sa.String(length=128), nullable=False),
    sa.Column('scenario', sa.Text(), nullable=False),
    sa.Column('cover_text', sa.Text(), nullable=False),
    sa.Column('release_notes', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('default_version', sa.String(length=64), nullable=True),
    sa.Column('latest_published_version', sa.String(length=64), nullable=True),
    sa.Column('source_task_id', sa.String(length=64), nullable=True),
    sa.Column('source_document_id', sa.String(length=64), nullable=True),
    sa.Column('step_count', sa.Integer(), nullable=False),
    sa.Column('created_by_user_id', sa.String(length=128), nullable=True),
    sa.Column('created_by_name', sa.String(length=255), nullable=True),
    sa.Column('updated_by_user_id', sa.String(length=128), nullable=True),
    sa.Column('updated_by_name', sa.String(length=255), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_applications_customer_id'), 'applications', ['customer_id'], unique=False)
    op.create_index('ix_applications_customer_status', 'applications', ['customer_id', 'status', 'updated_at'], unique=False)
    op.create_index(op.f('ix_applications_default_version'), 'applications', ['default_version'], unique=False)
    op.create_index(op.f('ix_applications_document_type'), 'applications', ['document_type'], unique=False)
    op.create_index(op.f('ix_applications_latest_published_version'), 'applications', ['latest_published_version'], unique=False)
    op.create_index(op.f('ix_applications_scope'), 'applications', ['scope'], unique=False)
    op.create_index(op.f('ix_applications_source_document_id'), 'applications', ['source_document_id'], unique=False)
    op.create_index(op.f('ix_applications_source_task_id'), 'applications', ['source_task_id'], unique=False)
    op.create_index(op.f('ix_applications_status'), 'applications', ['status'], unique=False)
    op.create_table('documents',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('customer_id', sa.String(length=64), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=False),
    sa.Column('file_type', sa.String(length=64), nullable=False),
    sa.Column('source_url', sa.Text(), nullable=False),
    sa.Column('object_key', sa.Text(), nullable=False),
    sa.Column('page_count', sa.Integer(), nullable=False),
    sa.Column('parse_status', sa.String(length=32), nullable=False),
    sa.Column('uploaded_by_user_id', sa.String(length=128), nullable=False),
    sa.Column('uploaded_by_name', sa.String(length=255), nullable=False),
    sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('markdown_url', sa.Text(), nullable=True),
    sa.Column('raw_json_url', sa.Text(), nullable=True),
    sa.Column('layout_url', sa.Text(), nullable=True),
    sa.Column('block_list_url', sa.Text(), nullable=True),
    sa.Column('model_json_url', sa.Text(), nullable=True),
    sa.Column('artifact_base_url', sa.Text(), nullable=True),
    sa.Column('parse_task_id', sa.String(length=64), nullable=True),
    sa.Column('parse_error', sa.Text(), nullable=True),
    sa.Column('latest_task_id', sa.String(length=64), nullable=True),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_documents_customer_id'), 'documents', ['customer_id'], unique=False)
    op.create_index('ix_documents_customer_updated', 'documents', ['customer_id', 'updated_at'], unique=False)
    op.create_index(op.f('ix_documents_latest_task_id'), 'documents', ['latest_task_id'], unique=False)
    op.create_index(op.f('ix_documents_parse_task_id'), 'documents', ['parse_task_id'], unique=False)
    op.create_table('application_steps',
    sa.Column('storage_id', sa.String(length=191), nullable=False),
    sa.Column('application_id', sa.String(length=64), nullable=False),
    sa.Column('version_label', sa.String(length=64), nullable=False),
    sa.Column('step_order', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('skill_id', sa.String(length=120), nullable=False),
    sa.Column('skill_version', sa.String(length=64), nullable=False),
    sa.Column('skill_name', sa.String(length=255), nullable=False),
    sa.Column('source_task_id', sa.String(length=64), nullable=True),
    sa.Column('source_document_id', sa.String(length=64), nullable=True),
    sa.Column('source_page_no', sa.Integer(), nullable=True),
    sa.Column('source_run_id', sa.String(length=64), nullable=True),
    sa.Column('source_status', sa.String(length=32), nullable=True),
    sa.Column('run_purpose', sa.String(length=32), nullable=True),
    sa.Column('operation_type', sa.String(length=32), nullable=True),
    sa.Column('result_mode', sa.String(length=32), nullable=True),
    sa.Column('skill_snapshot_json', sa.Text(), nullable=False),
    sa.Column('config_snapshot_json', sa.Text(), nullable=False),
    sa.Column('prompt_snapshot', sa.Text(), nullable=False),
    sa.Column('input_mapping_json', sa.Text(), nullable=False),
    sa.Column('target_mapping_json', sa.Text(), nullable=False),
    sa.Column('dependency_refs_json', sa.Text(), nullable=False),
    sa.Column('output_summary_json', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('storage_id')
    )
    op.create_index(op.f('ix_application_steps_application_id'), 'application_steps', ['application_id'], unique=False)
    op.create_index(op.f('ix_application_steps_kind'), 'application_steps', ['kind'], unique=False)
    op.create_index('ix_application_steps_run', 'application_steps', ['application_id', 'version_label', 'kind'], unique=False)
    op.create_index(op.f('ix_application_steps_run_purpose'), 'application_steps', ['run_purpose'], unique=False)
    op.create_index(op.f('ix_application_steps_skill_id'), 'application_steps', ['skill_id'], unique=False)
    op.create_index(op.f('ix_application_steps_source_document_id'), 'application_steps', ['source_document_id'], unique=False)
    op.create_index(op.f('ix_application_steps_source_page_no'), 'application_steps', ['source_page_no'], unique=False)
    op.create_index(op.f('ix_application_steps_source_run_id'), 'application_steps', ['source_run_id'], unique=False)
    op.create_index(op.f('ix_application_steps_source_task_id'), 'application_steps', ['source_task_id'], unique=False)
    op.create_index(op.f('ix_application_steps_version_label'), 'application_steps', ['version_label'], unique=False)
    op.create_index('ux_application_steps_scope', 'application_steps', ['application_id', 'version_label', 'step_order'], unique=True)
    op.create_table('application_versions',
    sa.Column('storage_id', sa.String(length=191), nullable=False),
    sa.Column('application_id', sa.String(length=64), nullable=False),
    sa.Column('customer_id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('document_type', sa.String(length=128), nullable=False),
    sa.Column('scenario', sa.Text(), nullable=False),
    sa.Column('cover_text', sa.Text(), nullable=False),
    sa.Column('release_notes', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('source_task_id', sa.String(length=64), nullable=True),
    sa.Column('source_document_id', sa.String(length=64), nullable=True),
    sa.Column('step_count', sa.Integer(), nullable=False),
    sa.Column('published_by_user_id', sa.String(length=128), nullable=True),
    sa.Column('published_by_name', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('storage_id')
    )
    op.create_index(op.f('ix_application_versions_application_id'), 'application_versions', ['application_id'], unique=False)
    op.create_index(op.f('ix_application_versions_customer_id'), 'application_versions', ['customer_id'], unique=False)
    op.create_index('ix_application_versions_default', 'application_versions', ['application_id', 'is_default', 'published_at'], unique=False)
    op.create_index(op.f('ix_application_versions_document_type'), 'application_versions', ['document_type'], unique=False)
    op.create_index(op.f('ix_application_versions_source_document_id'), 'application_versions', ['source_document_id'], unique=False)
    op.create_index(op.f('ix_application_versions_source_task_id'), 'application_versions', ['source_task_id'], unique=False)
    op.create_index(op.f('ix_application_versions_status'), 'application_versions', ['status'], unique=False)
    op.create_index('ux_application_versions_scope', 'application_versions', ['application_id', 'version'], unique=True)
    op.create_table('tasks',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('customer_id', sa.String(length=64), nullable=False),
    sa.Column('document_id', sa.String(length=64), nullable=False),
    sa.Column('customer_name', sa.String(length=255), nullable=False),
    sa.Column('task_name', sa.String(length=255), nullable=False),
    sa.Column('document_name', sa.String(length=255), nullable=False),
    sa.Column('role_scope_json', sa.Text(), nullable=False),
    sa.Column('owner', sa.String(length=255), nullable=False),
    sa.Column('owner_user_id', sa.String(length=128), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('upload_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('page_count', sa.Integer(), nullable=False),
    sa.Column('prompt_run_count', sa.Integer(), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tasks_customer_id'), 'tasks', ['customer_id'], unique=False)
    op.create_index('ix_tasks_customer_updated', 'tasks', ['customer_id', 'updated_at'], unique=False)
    op.create_index(op.f('ix_tasks_document_id'), 'tasks', ['document_id'], unique=False)
    op.create_index(op.f('ix_tasks_owner_user_id'), 'tasks', ['owner_user_id'], unique=False)
    op.create_index(op.f('ix_tasks_status'), 'tasks', ['status'], unique=False)
    op.create_index('ix_tasks_task_scope', 'tasks', ['document_id', 'owner_user_id'], unique=False)
    op.create_table('application_runs',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('application_id', sa.String(length=64), nullable=False),
    sa.Column('customer_id', sa.String(length=64), nullable=False),
    sa.Column('task_id', sa.String(length=64), nullable=False),
    sa.Column('document_id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('step_count', sa.Integer(), nullable=False),
    sa.Column('completed_step_count', sa.Integer(), nullable=False),
    sa.Column('triggered_by_user_id', sa.String(length=128), nullable=True),
    sa.Column('triggered_by_name', sa.String(length=255), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_application_runs_application_id'), 'application_runs', ['application_id'], unique=False)
    op.create_index(op.f('ix_application_runs_customer_id'), 'application_runs', ['customer_id'], unique=False)
    op.create_index(op.f('ix_application_runs_document_id'), 'application_runs', ['document_id'], unique=False)
    op.create_index('ix_application_runs_scope', 'application_runs', ['application_id', 'task_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_application_runs_status'), 'application_runs', ['status'], unique=False)
    op.create_index(op.f('ix_application_runs_task_id'), 'application_runs', ['task_id'], unique=False)
    op.create_index(op.f('ix_application_runs_version'), 'application_runs', ['version'], unique=False)
    op.create_table('application_workshop_step_drafts',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('task_id', sa.String(length=64), nullable=False),
    sa.Column('customer_id', sa.String(length=64), nullable=False),
    sa.Column('document_id', sa.String(length=64), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('data_type_name', sa.String(length=255), nullable=False),
    sa.Column('goal', sa.Text(), nullable=False),
    sa.Column('expected_output', sa.Text(), nullable=False),
    sa.Column('source_title', sa.Text(), nullable=False),
    sa.Column('source_scope', sa.Text(), nullable=False),
    sa.Column('skill_text', sa.Text(), nullable=False),
    sa.Column('skill_name', sa.String(length=255), nullable=False),
    sa.Column('errors_json', sa.Text(), nullable=False),
    sa.Column('model', sa.String(length=128), nullable=False),
    sa.Column('sample_source_json', sa.Text(), nullable=False),
    sa.Column('sample_extraction_json', sa.Text(), nullable=False),
    sa.Column('sample_processing_json', sa.Text(), nullable=False),
    sa.Column('run_option_json', sa.Text(), nullable=False),
    sa.Column('created_by_user_id', sa.String(length=128), nullable=True),
    sa.Column('updated_by_user_id', sa.String(length=128), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_application_workshop_step_drafts_customer_id'), 'application_workshop_step_drafts', ['customer_id'], unique=False)
    op.create_index('ix_application_workshop_step_drafts_customer_updated', 'application_workshop_step_drafts', ['customer_id', 'updated_at'], unique=False)
    op.create_index(op.f('ix_application_workshop_step_drafts_document_id'), 'application_workshop_step_drafts', ['document_id'], unique=False)
    op.create_index(op.f('ix_application_workshop_step_drafts_kind'), 'application_workshop_step_drafts', ['kind'], unique=False)
    op.create_index(op.f('ix_application_workshop_step_drafts_status'), 'application_workshop_step_drafts', ['status'], unique=False)
    op.create_index(op.f('ix_application_workshop_step_drafts_task_id'), 'application_workshop_step_drafts', ['task_id'], unique=False)
    op.create_index('ix_application_workshop_step_drafts_task_updated', 'application_workshop_step_drafts', ['task_id', 'updated_at'], unique=False)
    op.create_table('llm_call_traces',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('task_id', sa.String(length=64), nullable=False),
    sa.Column('document_id', sa.String(length=64), nullable=False),
    sa.Column('run_id', sa.String(length=64), nullable=False),
    sa.Column('stage', sa.String(length=32), nullable=False),
    sa.Column('request_kind', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('run_phase', sa.String(length=32), nullable=False),
    sa.Column('provider', sa.String(length=128), nullable=True),
    sa.Column('model', sa.String(length=128), nullable=True),
    sa.Column('skill_id', sa.String(length=120), nullable=True),
    sa.Column('input_chars', sa.Integer(), nullable=False),
    sa.Column('output_chars', sa.Integer(), nullable=False),
    sa.Column('prompt_tokens', sa.Integer(), nullable=True),
    sa.Column('completion_tokens', sa.Integer(), nullable=True),
    sa.Column('total_tokens', sa.Integer(), nullable=True),
    sa.Column('http_ms', sa.Integer(), nullable=True),
    sa.Column('total_ms', sa.Integer(), nullable=True),
    sa.Column('error_type', sa.String(length=128), nullable=True),
    sa.Column('request_object_key', sa.Text(), nullable=True),
    sa.Column('response_object_key', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_llm_call_traces_document_id'), 'llm_call_traces', ['document_id'], unique=False)
    op.create_index(op.f('ix_llm_call_traces_model'), 'llm_call_traces', ['model'], unique=False)
    op.create_index(op.f('ix_llm_call_traces_request_kind'), 'llm_call_traces', ['request_kind'], unique=False)
    op.create_index(op.f('ix_llm_call_traces_run_id'), 'llm_call_traces', ['run_id'], unique=False)
    op.create_index(op.f('ix_llm_call_traces_run_phase'), 'llm_call_traces', ['run_phase'], unique=False)
    op.create_index('ix_llm_call_traces_run_stage', 'llm_call_traces', ['run_id', 'stage', 'request_kind'], unique=False)
    op.create_index(op.f('ix_llm_call_traces_skill_id'), 'llm_call_traces', ['skill_id'], unique=False)
    op.create_index(op.f('ix_llm_call_traces_stage'), 'llm_call_traces', ['stage'], unique=False)
    op.create_index(op.f('ix_llm_call_traces_status'), 'llm_call_traces', ['status'], unique=False)
    op.create_index('ix_llm_call_traces_task_created', 'llm_call_traces', ['task_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_llm_call_traces_task_id'), 'llm_call_traces', ['task_id'], unique=False)
    op.create_table('parse_jobs',
    sa.Column('task_id', sa.String(length=64), nullable=False),
    sa.Column('customer_id', sa.String(length=64), nullable=False),
    sa.Column('document_id', sa.String(length=64), nullable=False),
    sa.Column('state', sa.String(length=32), nullable=False),
    sa.Column('mineru_state', sa.String(length=32), nullable=True),
    sa.Column('mineru_task_id', sa.String(length=128), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('extracted_pages', sa.Integer(), nullable=False),
    sa.Column('total_pages', sa.Integer(), nullable=False),
    sa.Column('start_time', sa.DateTime(timezone=True), nullable=True),
    sa.Column('full_zip_source_url', sa.Text(), nullable=True),
    sa.Column('full_zip_path', sa.Text(), nullable=True),
    sa.Column('markdown_path', sa.Text(), nullable=True),
    sa.Column('raw_json_path', sa.Text(), nullable=True),
    sa.Column('layout_path', sa.Text(), nullable=True),
    sa.Column('block_list_path', sa.Text(), nullable=True),
    sa.Column('model_json_path', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('task_id')
    )
    op.create_index(op.f('ix_parse_jobs_customer_id'), 'parse_jobs', ['customer_id'], unique=False)
    op.create_index(op.f('ix_parse_jobs_document_id'), 'parse_jobs', ['document_id'], unique=False)
    op.create_index(op.f('ix_parse_jobs_mineru_task_id'), 'parse_jobs', ['mineru_task_id'], unique=False)
    op.create_index(op.f('ix_parse_jobs_state'), 'parse_jobs', ['state'], unique=False)
    op.create_table('prompt_configs',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('task_id', sa.String(length=64), nullable=False),
    sa.Column('prompt_name', sa.String(length=255), nullable=False),
    sa.Column('prompt_text', sa.Text(), nullable=False),
    sa.Column('start_page_no', sa.Integer(), nullable=False),
    sa.Column('end_page_no', sa.Integer(), nullable=False),
    sa.Column('run_purpose', sa.String(length=32), nullable=False),
    sa.Column('source_template_id', sa.String(length=128), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_prompt_configs_run_purpose'), 'prompt_configs', ['run_purpose'], unique=False)
    op.create_index(op.f('ix_prompt_configs_task_id'), 'prompt_configs', ['task_id'], unique=False)
    op.create_index('ix_prompt_configs_task_scope', 'prompt_configs', ['task_id', 'start_page_no', 'end_page_no'], unique=False)
    op.create_table('prompt_runs',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('task_id', sa.String(length=64), nullable=False),
    sa.Column('document_id', sa.String(length=64), nullable=False),
    sa.Column('run_type', sa.String(length=32), nullable=False),
    sa.Column('run_name', sa.String(length=255), nullable=False),
    sa.Column('prompt_name', sa.String(length=255), nullable=False),
    sa.Column('prompt_text', sa.Text(), nullable=False),
    sa.Column('start_page_no', sa.Integer(), nullable=False),
    sa.Column('end_page_no', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('run_phase', sa.String(length=32), nullable=False),
    sa.Column('run_purpose', sa.String(length=32), nullable=False),
    sa.Column('prompt_config_id', sa.String(length=64), nullable=True),
    sa.Column('template_id', sa.String(length=128), nullable=True),
    sa.Column('schema_template_name', sa.String(length=255), nullable=True),
    sa.Column('schema_template_version', sa.String(length=64), nullable=True),
    sa.Column('llm_provider', sa.String(length=128), nullable=True),
    sa.Column('llm_model', sa.String(length=128), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('input_path', sa.Text(), nullable=True),
    sa.Column('output_path', sa.Text(), nullable=True),
    sa.Column('output_text', sa.Text(), nullable=True),
    sa.Column('input_facts_snapshot_json', sa.Text(), nullable=True),
    sa.Column('schema_definition_json', sa.Text(), nullable=True),
    sa.Column('schema_output_json', sa.Text(), nullable=True),
    sa.Column('validation_errors_json', sa.Text(), nullable=True),
    sa.Column('structured_extraction_result_json', sa.Text(), nullable=True),
    sa.Column('structured_process_result_json', sa.Text(), nullable=True),
    sa.Column('structured_business_result_json', sa.Text(), nullable=True),
    sa.Column('evidence_block_ids_json', sa.Text(), nullable=False),
    sa.Column('evidence_excerpts_json', sa.Text(), nullable=False),
    sa.Column('phase_started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_heartbeat_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_prompt_runs_document_id'), 'prompt_runs', ['document_id'], unique=False)
    op.create_index(op.f('ix_prompt_runs_prompt_config_id'), 'prompt_runs', ['prompt_config_id'], unique=False)
    op.create_index(op.f('ix_prompt_runs_run_phase'), 'prompt_runs', ['run_phase'], unique=False)
    op.create_index(op.f('ix_prompt_runs_run_purpose'), 'prompt_runs', ['run_purpose'], unique=False)
    op.create_index(op.f('ix_prompt_runs_run_type'), 'prompt_runs', ['run_type'], unique=False)
    op.create_index(op.f('ix_prompt_runs_status'), 'prompt_runs', ['status'], unique=False)
    op.create_index(op.f('ix_prompt_runs_task_id'), 'prompt_runs', ['task_id'], unique=False)
    op.create_index('ix_prompt_runs_task_scope_updated', 'prompt_runs', ['task_id', 'start_page_no', 'end_page_no', 'updated_at'], unique=False)
    op.create_index('ix_prompt_runs_task_type', 'prompt_runs', ['task_id', 'run_type'], unique=False)
    op.create_table('task_operation_targets',
    sa.Column('storage_id', sa.String(length=191), nullable=False),
    sa.Column('task_id', sa.String(length=64), nullable=False),
    sa.Column('page_no', sa.Integer(), nullable=False),
    sa.Column('target_id', sa.String(length=191), nullable=False),
    sa.Column('source_run_id', sa.String(length=64), nullable=False),
    sa.Column('target_type', sa.String(length=64), nullable=False),
    sa.Column('label', sa.Text(), nullable=False),
    sa.Column('value_text', sa.Text(), nullable=False),
    sa.Column('excerpt', sa.Text(), nullable=True),
    sa.Column('block_position', sa.Text(), nullable=True),
    sa.Column('field_key', sa.String(length=191), nullable=True),
    sa.Column('row_index', sa.Integer(), nullable=True),
    sa.Column('row_count', sa.Integer(), nullable=True),
    sa.Column('column_count', sa.Integer(), nullable=True),
    sa.Column('headers_json', sa.Text(), nullable=False),
    sa.Column('block_ids_json', sa.Text(), nullable=False),
    sa.Column('group_label', sa.Text(), nullable=True),
    sa.Column('data_object_key', sa.Text(), nullable=True),
    sa.Column('data_content_hash', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('storage_id')
    )
    op.create_index('ix_task_operation_targets_page', 'task_operation_targets', ['task_id', 'page_no'], unique=False)
    op.create_index(op.f('ix_task_operation_targets_page_no'), 'task_operation_targets', ['page_no'], unique=False)
    op.create_index('ix_task_operation_targets_source', 'task_operation_targets', ['task_id', 'source_run_id'], unique=False)
    op.create_index(op.f('ix_task_operation_targets_source_run_id'), 'task_operation_targets', ['source_run_id'], unique=False)
    op.create_index(op.f('ix_task_operation_targets_target_id'), 'task_operation_targets', ['target_id'], unique=False)
    op.create_index(op.f('ix_task_operation_targets_target_type'), 'task_operation_targets', ['target_type'], unique=False)
    op.create_index(op.f('ix_task_operation_targets_task_id'), 'task_operation_targets', ['task_id'], unique=False)
    op.create_index('ux_task_operation_targets_task_target', 'task_operation_targets', ['task_id', 'target_id'], unique=True)
    op.create_table('task_result_artifacts',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('task_id', sa.String(length=64), nullable=False),
    sa.Column('document_id', sa.String(length=64), nullable=False),
    sa.Column('page_no', sa.Integer(), nullable=True),
    sa.Column('run_id', sa.String(length=64), nullable=True),
    sa.Column('stage', sa.String(length=32), nullable=False),
    sa.Column('artifact_kind', sa.String(length=64), nullable=False),
    sa.Column('object_key', sa.Text(), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('content_type', sa.String(length=128), nullable=False),
    sa.Column('summary_json', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_task_result_artifacts_artifact_kind'), 'task_result_artifacts', ['artifact_kind'], unique=False)
    op.create_index(op.f('ix_task_result_artifacts_document_id'), 'task_result_artifacts', ['document_id'], unique=False)
    op.create_index(op.f('ix_task_result_artifacts_page_no'), 'task_result_artifacts', ['page_no'], unique=False)
    op.create_index(op.f('ix_task_result_artifacts_run_id'), 'task_result_artifacts', ['run_id'], unique=False)
    op.create_index('ix_task_result_artifacts_run_kind', 'task_result_artifacts', ['task_id', 'run_id', 'artifact_kind'], unique=False)
    op.create_index('ix_task_result_artifacts_scope', 'task_result_artifacts', ['task_id', 'stage', 'artifact_kind', 'page_no'], unique=False)
    op.create_index(op.f('ix_task_result_artifacts_stage'), 'task_result_artifacts', ['stage'], unique=False)
    op.create_index(op.f('ix_task_result_artifacts_task_id'), 'task_result_artifacts', ['task_id'], unique=False)
    op.create_table('application_run_steps',
    sa.Column('storage_id', sa.String(length=191), nullable=False),
    sa.Column('application_run_id', sa.String(length=64), nullable=False),
    sa.Column('application_id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.String(length=64), nullable=False),
    sa.Column('step_order', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('skill_id', sa.String(length=120), nullable=False),
    sa.Column('skill_version', sa.String(length=64), nullable=False),
    sa.Column('skill_name', sa.String(length=255), nullable=False),
    sa.Column('source_application_step_id', sa.String(length=191), nullable=True),
    sa.Column('source_page_no', sa.Integer(), nullable=True),
    sa.Column('source_run_id', sa.String(length=64), nullable=True),
    sa.Column('execution_run_id', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('input_mapping_json', sa.Text(), nullable=False),
    sa.Column('target_mapping_json', sa.Text(), nullable=False),
    sa.Column('config_snapshot_json', sa.Text(), nullable=False),
    sa.Column('prompt_snapshot', sa.Text(), nullable=False),
    sa.Column('output_summary_json', sa.Text(), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['application_run_id'], ['application_runs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('storage_id')
    )
    op.create_index(op.f('ix_application_run_steps_application_id'), 'application_run_steps', ['application_id'], unique=False)
    op.create_index(op.f('ix_application_run_steps_application_run_id'), 'application_run_steps', ['application_run_id'], unique=False)
    op.create_index(op.f('ix_application_run_steps_execution_run_id'), 'application_run_steps', ['execution_run_id'], unique=False)
    op.create_index(op.f('ix_application_run_steps_kind'), 'application_run_steps', ['kind'], unique=False)
    op.create_index(op.f('ix_application_run_steps_skill_id'), 'application_run_steps', ['skill_id'], unique=False)
    op.create_index(op.f('ix_application_run_steps_source_application_step_id'), 'application_run_steps', ['source_application_step_id'], unique=False)
    op.create_index(op.f('ix_application_run_steps_source_page_no'), 'application_run_steps', ['source_page_no'], unique=False)
    op.create_index(op.f('ix_application_run_steps_source_run_id'), 'application_run_steps', ['source_run_id'], unique=False)
    op.create_index(op.f('ix_application_run_steps_status'), 'application_run_steps', ['status'], unique=False)
    op.create_index(op.f('ix_application_run_steps_version'), 'application_run_steps', ['version'], unique=False)
    op.create_index('ux_application_run_steps_scope', 'application_run_steps', ['application_run_id', 'step_order'], unique=True)


def downgrade() -> None:
    op.drop_table('application_run_steps')
    op.drop_table('task_result_artifacts')
    op.drop_table('task_operation_targets')
    op.drop_table('prompt_runs')
    op.drop_table('prompt_configs')
    op.drop_table('parse_jobs')
    op.drop_table('llm_call_traces')
    op.drop_table('application_workshop_step_drafts')
    op.drop_table('application_runs')
    op.drop_table('tasks')
    op.drop_table('application_versions')
    op.drop_table('application_steps')
    op.drop_table('documents')
    op.drop_table('applications')
    op.drop_table('users')
    op.drop_table('skill_test_runs')
    op.drop_table('skill_samples')
    op.drop_table('schema_templates')
    op.drop_table('customers')
    op.drop_table('business_skills')
