# TechFlag IDP Community User Manual

[中文](user-manual.zh-CN.md)

This manual explains how to run the GitHub community edition locally and how to complete the first document-processing workflow.

## 1. What You Can Do

The community edition provides a local intelligent document processing workbench:

- Upload PDF or image documents.
- Keep the original file visible even when parsing fails.
- Parse documents through a configurable MinerU provider.
- Review source pages, recognition results, document tree, JSON, and extraction output.
- Try basic AI extraction with your own OpenAI-compatible model.
- Use the single-page/basic community workflow.

The community edition does not include commercial long-document execution, batch processing, enterprise connectors, HITL workflows, full publishing/marketplace flows, or commercial recovery chains.

## 2. Start the System

### Backend

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

Backend health check:

```text
http://127.0.0.1:5006/api/health
```

### Frontend

Open another terminal:

```bash
cd frontend
npm ci
npm run dev -- --host 0.0.0.0
```

Open:

```text
http://127.0.0.1:5173/idp/
```

Default local administrator:

```text
Username: idp-admin
Password: demo-pass
```

## 3. Language

The frontend supports Chinese and English.

- The first visit uses the browser language when possible.
- You can switch language from the top-right language control.
- The selection is stored in `localStorage` with key `idp.locale`.
- Uploaded document content, OCR text, model output, Skill Markdown, file names, and backend-returned business data are not translated.

Optional environment variable:

```bash
VITE_DEFAULT_LOCALE=en-US
```

Allowed values are `zh-CN` and `en-US`.

## 4. Database

The community edition needs a database, but you do not need to install a database server for the default local setup.

By default it uses SQLite:

```text
backend/.runtime/idp-community.db
```

The startup script runs database migration automatically. If you start the backend manually, run:

```bash
cd backend
alembic -c alembic.ini upgrade head
python scripts/diagnose_auth.py --ensure-admin --password demo-pass
```

If login fails with `sqlite3.OperationalError: no such table: users`, the database tables have not been created yet. Run the commands above.

## 5. Upload a Document

1. Log in as `idp-admin`.
2. Open the default local workspace named `场景应用`.
3. Click the upload button.
4. Select a PDF or image file.
5. The system creates a task and keeps the original file available for preview.

If parsing is not configured, upload still succeeds. The source file remains visible and parsing ends with a clear failure state instead of staying pending.

## 6. Configure MinerU Parsing

Apply for a MinerU token:

```text
https://mineru.net/?source=github
```

Add it to `backend/.env.local`:

```bash
MINERU_TOKEN=your-mineru-token
```

MinerU cloud must be able to fetch the uploaded file URL. With default local object storage, files are usually served as local backend URLs and cannot be fetched by MinerU cloud.

For real cloud parsing, use one of these options:

- Configure OSS so uploaded files get externally reachable URLs.
- Or expose the backend through a public URL and set:

```bash
BACKEND_PUBLIC_BASE_URL=https://your-public-backend.example.com
```

When the token or public file URL is missing, the task should fail clearly and remain retryable.

## 7. Configure AI Extraction

Configure an OpenAI-compatible model in `backend/.env.local`:

```bash
DASHSCOPE_API_KEY=your-llm-key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=qwen3.6-27b
```

Without an LLM key, you can still start the app and browse basic pages. Real AI extraction will show a configuration hint instead of entering a long pending state.

## 8. Run Basic Extraction

1. Open a parsed task.
2. Review the source page and recognition result.
3. Select or confirm the target content.
4. Run extraction.
5. Review the extracted fields, tables, JSON, and evidence.

For the community edition, keep the workflow single-page/basic. Long-document and cross-page commercial execution are not included in the GitHub community repository.

## 9. Troubleshooting

### The backend starts but login fails

Run database migration and admin bootstrap:

```bash
cd backend
alembic -c alembic.ini upgrade head
python scripts/diagnose_auth.py --ensure-admin --password demo-pass
```

### Upload works but parsing fails

Check:

- `MINERU_TOKEN` is configured.
- The uploaded file URL is reachable by MinerU cloud.
- OSS or `BACKEND_PUBLIC_BASE_URL` is configured for real cloud parsing.

### AI extraction does not run

Check:

- `DASHSCOPE_API_KEY` is configured.
- `DASHSCOPE_BASE_URL` and `DASHSCOPE_MODEL` are correct.
- The backend has been restarted after editing `.env.local`.

### The frontend cannot reach the backend

The Vite dev server proxies `/idp-api` to `http://127.0.0.1:5006/api` by default. If your backend runs elsewhere, set `VITE_PROXY_TARGET`.

## 10. Useful Commands

```bash
# Backend tests
python3 -m pytest backend/tests -q

# Frontend build
cd frontend
npm run build

# Edition guardrails
python3 scripts/edition_guardrail_agent.py
```
