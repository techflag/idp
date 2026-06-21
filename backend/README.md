# IDP Backend

[中文](README.zh-CN.md)

The backend is built with FastAPI, SQLAlchemy, Alembic, and local runtime artifacts. The community edition uses SQLite by default, so no separate database server is required for local startup.

For first-time setup, start with the root [README.md](../README.md).

## Local Startup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
cp .env.local.example .env.local
alembic -c alembic.ini upgrade head
python scripts/diagnose_auth.py --ensure-admin --password demo-pass
./start.sh
```

Health check:

```text
http://127.0.0.1:5006/api/health
```

Stop service:

```bash
./stop.sh
```

## Database

Does the community backend need a database?

Yes, but the default local setup does not require a separate database server.

The backend uses SQLite by default. The database file is:

```text
backend/.runtime/idp-community.db
```

This file is created locally after database migration and is not committed to Git.

A fresh community bootstrap only creates the local admin user and one default workspace, `场景应用`. It does not include built-in customer records or private business sample data.

Create or upgrade tables with:

```bash
alembic -c alembic.ini upgrade head
```

`./start.sh` runs this migration automatically by default. If you start the backend manually with `python -m app.main`, run the Alembic command first.

To reset local development data, stop the backend, delete `backend/.runtime/idp-community.db`, and run the Alembic command again.

If login fails with `sqlite3.OperationalError: no such table: users`, the database tables have not been created yet. Run:

```bash
alembic -c alembic.ini upgrade head
python scripts/diagnose_auth.py --ensure-admin --password demo-pass
```

The second command creates or resets the local admin account and ensures the default `场景应用` workspace exists.

## Common Configuration

- `IDP_EDITION=community`
- `RUNTIME_DATA_DIR`: runtime file directory, default `backend/.runtime`
- `DATABASE_URL`: SQLite is used by default in community mode; non-SQLite URLs are ignored unless `IDP_COMMUNITY_ALLOW_EXTERNAL_DATABASE=true` is explicitly set
- `MINERU_TOKEN`: token for real document parsing, apply at https://mineru.net/?source=github
- `DASHSCOPE_API_KEY`: BYO LLM key for real AI extraction
- `OBJECT_STORAGE_PROVIDER`: `auto`, `local`, or `oss`; default `auto`
- `OSS_ACCESS_KEY_ID` / `OSS_ACCESS_KEY_SECRET`: optional; local runtime object storage is used when OSS is not configured
- `BACKEND_PUBLIC_BASE_URL`: optional; required when local object storage must be fetched by a cloud MinerU parser
- `SAMPLE_DOC_DIR`: optional parsed sample bundle directory

## Auth Diagnostics

Check database, migration, and admin account state:

```bash
python scripts/diagnose_auth.py
```

Create or reset the local admin account and ensure the default `场景应用` workspace:

```bash
python scripts/diagnose_auth.py --ensure-admin --password demo-pass
```

## Main APIs

- `GET /api/health`
- `POST /api/auth/login`
- `GET /api/system/capabilities`
- `GET /api/workbench/dataset`
- `GET /api/workbench/tasks/{taskId}`
- `GET /api/customers`
- `POST /api/customers`
- `POST /api/tasks/{taskId}/parse`
- `GET /api/tasks/{taskId}/parse`
- `POST /api/tasks/{taskId}/prompt-runs`
- `POST /api/skills/sample-extract-from-sample`

When MinerU Token or LLM Key is missing, real parsing or extraction APIs should return a configuration hint instead of entering a long pending state. If MinerU Token is configured but the file URL is still local `/api/objects/...`, parsing fails clearly and asks for OSS or `BACKEND_PUBLIC_BASE_URL`.

The GitHub community edition does not expose full document application authoring, publishing, application marketplace/use flows, or cross-page application runs. These entries are controlled by `application.authoring` / `application.run` capabilities and are hidden or blocked with 403 in community mode.
