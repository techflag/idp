# Public Screenshot Rules

Screenshots in this directory are used by the public GitHub/Gitee README files.
The current PNG files are public-safe placeholder preview images. Replace them
with real screenshots using the same filenames when the final community demo
environment is ready.

Use real product screenshots only when they are captured from a clean community
edition instance with sanitized demo data. Do not capture screenshots from a
commercial, production, or day-to-day development database.

Before replacing these files, verify that the screenshots do not expose:

- Customer names, project names, contracts, reports, invoices, or uploaded files.
- Access tokens, API keys, cookies, local file paths, database URLs, or internal hosts.
- Commercial-only features, internal workflow labels, or private implementation details.

Recommended capture source:

- `IDP_EDITION=community`
- Local SQLite database initialized from the community baseline
- Local object storage or public-safe demo OSS objects
- Demo documents created specifically for open-source screenshots
