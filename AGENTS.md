# TechFlag IDP Community Development Guardrails

This repository is the community edition of TechFlag IDP. Every change must keep the public edition startable, honest about its limits, and free of commercial-only implementation chains.

## Edition Decision First

For every new feature, route, provider, workflow, UI entry, runtime limit, or user-visible message, write or update a Feature Decision before coding:

- Feature name
- Applicable edition: `community`, `commercial`, or `both`
- Community behavior and capability level: `unavailable`, `demo`, `basic`, `limited`, or `full`
- Commercial behavior and capability level
- Required providers and no-configuration behavior
- Backend capability key and limit policy
- Frontend entry control
- Database migration impact
- i18n scope
- Test matrix

## Non-Negotiables

- Do not scatter `if edition == "community"` or equivalent checks through business code.
- Express edition differences through capability, limit, provider, extension, and policy layers.
- Do not maintain duplicate community and commercial product code for the same business workflow.
- Do not remove OCR, tables, document trees, evidence, artifacts, or result data to enforce community limits.
- Do not let community users enter a long-running pending state when a required provider token or key is missing.
- Do not add commercial full chains to the public community repository.
- Do not treat tunable limits such as `maxPagesPerRun` as commercial protection. Open-source users can edit constants; protection comes from not publishing full commercial chains.

## Community Boundary

The community edition must remain startable and understandable without cloud keys:

- Default storage must work locally and use SQLite unless an external database is explicitly enabled.
- MinerU may be available as a configurable provider, but missing tokens must point users to `https://mineru.net/?source=github`.
- BYO LLM must fail with clear setup guidance, not a silent pending run.
- Long-document behavior is limited to public single-page/basic flows.
- `document.longRun` is unavailable in the GitHub community snapshot.
- Application-run routes/services are community boundary stubs and must not be replaced with the full long-document planner.

## Capability Registry

Capability definitions are the source of truth for edition behavior. Frontend, backend, tests, documentation, and release checks must agree with the registry.

When adding or changing a capability:

- Update the registry or its public snapshot.
- Add or update tests for community no-config and community configured behavior where applicable.
- Keep public fixtures independent from private packages, private samples, and commercial regression data.

## Public Repository Hygiene

- Do not commit real `.env` files, tokens, passwords, internal endpoints, customer data, runtime artifacts, or generated dependency directories.
- Do not add internal maintainer runbooks, internal PRDs, private regression sets, or commercial implementation packages.
- Keep public checks passing: `python3 scripts/check_edition_policy.py` and `python3 scripts/check_public_export.py <export-dir>`.
