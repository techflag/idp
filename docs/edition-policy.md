# Edition Policy

This policy defines how TechFlag IDP keeps the community and commercial editions compatible without developing two separate products.

## Core Rules

- Every feature starts with an Edition Impact decision.
- Shared product behavior lives in one core.
- Edition differences are declared through capabilities, limits, provider requirements, and private extensions.
- Community restrictions must be explicit and user-visible.
- Commercial full chains must not be shipped in the GitHub community repository.
- Tunable values such as `maxPagesPerRun` are not a protection boundary. They support UX and validation only; the public repository must not contain the full commercial chain behind the limit.
- API contracts may remain shared when that reduces maintenance cost. The edition boundary is the implementation/provider layer and the sanitized export check, not a second set of route paths.

## Capability Levels

| Level | Meaning | User Experience |
| --- | --- | --- |
| `unavailable` | The edition does not include the capability. | Hide the entry or show an upgrade explanation; do not allow execution. |
| `demo` | Sample-only or read-only demonstration. | Clearly label as demo; do not process production user data. |
| `basic` | Minimal real workflow. | Usable with clear boundaries. |
| `limited` | Real workflow with significant limits. | Show limits before execution and enforce them on the backend. |
| `full` | Production-grade complete capability. | Available for commercial/full validation. |

## Community Baseline

Community edition behavior should be honest and runnable:

- SQLite or local-friendly storage should be the default target for community distribution once the database migration plan is implemented.
- MinerU is an allowed default parser provider, but users must configure their own token.
- The GitHub community repository must not ship a default shared MinerU account, MinerU token, LLM key, OSS key, or other private provider credential.
- Missing MinerU configuration must link to `https://mineru.net/?source=github`.
- BYO OpenAI-compatible LLM configuration is allowed.
- Missing LLM keys must show setup guidance instead of entering pending runs.
- Long documents may be uploaded only when the UI and backend make the community page/run limit explicit.
- The community repository must not include the full commercial long-document chain.
- `document.run` may be limited for single-page/basic flows, but `document.longRun` is unavailable in the GitHub community snapshot.
- `application.authoring` and `application.run` are limited in the GitHub community snapshot. Community may expose a single-page Lite or sample-level experience, but full authoring, publishing, marketplace/use flows, long-document application runs, and recovery chains must be backed by stubs or explicit 403 boundaries instead of exposing the commercial chain.
- `skill.prototypeOptimization` is unavailable in the GitHub community snapshot. The route/schema contract may remain shared, but SkillPrototype services must be community stubs and full SkillOpt, SkillNet, training/evaluation, gate, publishing, and private regression implementations must be excluded.

## Commercial Boundary

Commercial-only or full capabilities include, but are not limited to:

- Full long-document execution, cross-page evidence expansion, queueing, long-table review, full audit, and failure recovery.
- Full document application authoring, multi-step orchestration, template asset hardening, publishing, application marketplace/use flows, and application run recovery.
- Batch orchestration, concurrency control, and SLA scheduling.
- HITL approval pause/resume, approval history, timeout policy, and enterprise review workflows.
- Enterprise connectors such as SAP, Yonyou, Kingdee, Oracle, enterprise IM, and approval systems.
- SSO, compliance audit exports, enterprise security controls, active learning, and managed provider operations.

Commercial implementations must enter through private providers or extensions and must not duplicate shared core product code.

## Provider Rules

| Provider Type | Community Rule | Commercial Rule |
| --- | --- | --- |
| Storage | Public local-friendly provider or clearly documented BYO setup. | Managed or enterprise storage may be private. |
| Parser | MinerU can be public and configurable. | Managed parsing and production long-document processing can be private. |
| LLM | BYO compatible model with setup guidance. | Managed model routing, cost control, and enterprise model governance can be private. |
| Connector | Public generic file, HTTP, or basic SQL examples only. | Enterprise connectors remain private. |

Provider configuration status must be reported as `configured`, `not_configured`, `optional`, or `managed`.

If a frictionless public demo is needed, expose it through a separately operated proxy service with authentication, rate limits, quota controls, abuse monitoring, and revocation. Do not place the underlying MinerU account or token in public source code, examples, docs, or default configuration.

## Code Annotation Rules

Edition annotations are lightweight source markers used by humans and deterministic checks:

| Annotation | Meaning |
| --- | --- |
| `@edition-scope shared-api-contract` | Shared API route, schema, or contract that may be published in community. |
| `@edition-scope community-stub` | Public stub or empty implementation for unavailable community capabilities. |
| `@edition-scope commercial-only` | Implementation that must never appear in GitHub community exports. |
| `@edition-action <name> community=<mode> commercial=<mode>` | Method-level API/action behavior for mixed shared contract files. |
| `@capability <key>` | Capability registry key controlled by the file. |
| `@community-export include` | File may appear in sanitized community snapshots. |
| `@community-export exclude` | File must be excluded from sanitized community snapshots. |

Commercial-only annotations must be backed by automation: the file must be excluded by `scripts/export_community_snapshot.py`, forbidden by `scripts/check_public_export.py`, and absent from generated GitHub community snapshots. This allows a shared API shell with different implementation bindings, avoiding two separate products while keeping commercial implementations out of public source.
When a backend route file is marked `shared-api-contract`, every `@router.*` endpoint must carry method-level `@edition-action` and `@capability` annotations. File-level annotations answer whether the file can be exported; method-level annotations answer how each action behaves in community and commercial editions.

## Limit Rules

Limits are product behavior, not commercial protection by themselves. Open-source users can change parameters, so commercial protection comes from not publishing complete commercial chains.

Capability and limit parameters select the user-visible mode and enforce validation; they are not the protection boundary. A GitHub community build must not contain a full commercial implementation that can be unlocked by changing `maxPagesPerRun`, `application.authoring`, or any other local parameter.

| Limit | Community Direction | Commercial Direction |
| --- | --- | --- |
| Pages per run | Public single-page/basic flow. | Full long-document execution. |
| File size | Local experience friendly. | Larger files with queueing and recovery. |
| Batch | Not available or basic single-file flow. | Batch upload and execution. |
| Concurrency | Low local concurrency. | Queueing, concurrency control, and SLA. |
| Audit retention | Basic logs only. | Compliance audit and export. |

## Automated Guardrail Agent

Edition checks must be automated. Do not rely on a reviewer or an AI agent remembering the rules.

Use the guardrail agent before feature implementation and before community release:

```bash
python3 scripts/edition_guardrail_agent.py
```

For PR-style checks, require code changes to include a machine-readable Feature Decision change:

```bash
python3 scripts/edition_guardrail_agent.py --require-decision-for-changes --base origin/main --head HEAD
```

For community release preflight:

```bash
python3 scripts/edition_guardrail_agent.py --release-community
```

To validate and sync the sanitized community export directory:

```bash
python3 scripts/edition_guardrail_agent.py --release-community --sync-community-export
```

The agent currently verifies:

- Edition references stay in policy/capability/provider layers.
- Feature Decision JSON files are complete and use registered capability keys.
- The community export passes public boundary checks.
- The community backend no-config tests pass.
- The exported community frontend builds.
- Build artifacts and dependencies are cleaned before syncing the community export.

## Feature Decision Template

Every new feature, bugfix with product impact, provider, route, UI entry, or runtime policy change must answer:

- Feature name
- Applicable edition: `community`, `commercial`, or `both`
- Community capability level and behavior
- Commercial capability level and behavior
- Required provider
- No-configuration behavior
- Backend capability key
- Limit policy
- Frontend entry control
- Implementation boundary: community allowed / community excluded
- Database migration impact
- i18n scope
- Test matrix

Feature Decisions must be stored as machine-readable JSON files under `docs/feature-decisions/*.json`; PR text alone is not enough. The guardrail agent checks required fields, enum values, registered capability keys, provider no-config behavior, and minimum community/no-config test coverage.

## GitHub Public Boundary

The GitHub community repository must be created and updated from a sanitized export, not by pushing internal source history.

Public GitHub content may include:

- Community source code and public docs.
- Public community tests.
- Public community capability snapshot or fixture.
- Public sample data that has been cleared for release.

Public GitHub content must not include:

- Real `.env` files, tokens, secrets, internal endpoints, or customer data.
- Shared default MinerU accounts/tokens, LLM keys, OSS keys, or provider credentials intended to make public installs use TechFlag-owned quota directly.
- Internal PRDs, internal samples, private regression sets, or runtime artifacts.
- Commercial full implementations or private packages.
- Full application-run planner, cross-page semantic application orchestration, commercial long-document queue/recovery chain, or any equivalent implementation hidden behind a numeric limit.
- Internal source commit history if it contains internal-only work.

## Public Export Stubs

The sanitized GitHub snapshot must replace full commercial implementation modules with community boundary stubs:

- `backend/app/api/routes/applications.py` must carry `COMMUNITY_APPLICATION_ROUTES_STUB`.
- `backend/app/services/application_assets.py` must carry `COMMUNITY_APPLICATION_ASSETS_STUB`.
- `backend/app/services/skill_prototype_service.py` must carry `COMMUNITY_SKILL_PROTOTYPE_SERVICE_STUB`.
- `backend/app/services/skill_prototype_job_service.py` must carry `COMMUNITY_SKILL_PROTOTYPE_JOB_SERVICE_STUB`.

These stubs keep the community backend startable while making it clear that full application runs, long-document orchestration, and SkillOpt-style candidate optimization are not shipped publicly. Community `limited` means Lite/stub capability is present; it does not mean the full commercial backend implementation is available behind a configurable page-count constant.
