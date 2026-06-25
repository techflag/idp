# IDP 后端

[English](README.md)

后端基于 FastAPI、SQLAlchemy、Alembic 和本地 runtime artifacts。社区版默认使用 SQLite，本地启动不需要单独安装数据库服务器。

首次启动请优先阅读项目根目录 [README.md](../README.md)。

## 本地启动

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

健康检查：

```text
http://127.0.0.1:5006/api/health
```

停止服务：

```bash
./stop.sh
```

## 数据库

社区版后端要不要数据库？

要，但默认本地启动不需要单独安装数据库服务器。

后端默认使用 SQLite。数据库文件是：

```text
backend/.runtime/idp-community.db
```

这个文件会在本地迁移后生成，不会提交到 Git。

全新社区版初始化只会创建本地管理员账号和一个默认空间 `场景应用`，不会内置客户资料或私有业务样例数据。

创建或升级表结构：

```bash
alembic -c alembic.ini upgrade head
```

`./start.sh` 默认会自动执行这一步。如果你手动用 `python -m app.main` 启动后端，请先执行 Alembic 命令。

如果要重置本地开发数据，可以先停止后端，删除 `backend/.runtime/idp-community.db`，再重新执行 Alembic 命令。

如果登录时报 `sqlite3.OperationalError: no such table: users`，说明数据库表还没有创建。执行：

```bash
alembic -c alembic.ini upgrade head
python scripts/diagnose_auth.py --ensure-admin --password demo-pass
```

第二条命令会创建或重置本地管理员账号，并确保默认 `场景应用` 空间存在。

## 常用配置

- `IDP_EDITION=community`
- `RUNTIME_DATA_DIR`：运行时文件目录，默认 `backend/.runtime`
- `DATABASE_URL`：社区版默认 SQLite；非 SQLite 地址会被忽略，除非显式设置 `IDP_COMMUNITY_ALLOW_EXTERNAL_DATABASE=true`
- `MINERU_TOKEN`：真实文档解析所需 Token，申请地址 https://mineru.net/?source=github
- `DASHSCOPE_API_KEY`：真实 AI 抽取所需 BYO LLM Key
- `OBJECT_STORAGE_PROVIDER`：可选 `auto`、`local`、`oss`；默认 `auto`
- `OSS_ACCESS_KEY_ID` / `OSS_ACCESS_KEY_SECRET`：可选；未配置 OSS 时使用本地 runtime 对象存储
- `BACKEND_PUBLIC_BASE_URL`：可选；使用本地对象存储并希望云端 MinerU 读取文件时，需要配置为公网可访问的后端地址
- `SAMPLE_DOC_DIR`：可选样例 bundle 目录

## 账号诊断

查看数据库、迁移和管理员账号状态：

```bash
python scripts/diagnose_auth.py
```

创建或重置本地管理员，并确保默认 `场景应用` 空间存在：

```bash
python scripts/diagnose_auth.py --ensure-admin --password demo-pass
```

## 主要接口

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

缺少 MinerU Token 或 LLM Key 时，真实解析/抽取接口应该返回配置提示，不应该进入长期 pending。只配置 MinerU Token 但文件仍是本地 `/api/objects/...` 地址时，也会明确失败并提示配置 OSS 或 `BACKEND_PUBLIC_BASE_URL`。

GitHub 社区版不开放完整文档应用制作、发布、应用市场使用和跨页应用运行链路；这些入口由 `application.authoring` / `application.run` capability 控制，并在社区版中隐藏或返回 403。
