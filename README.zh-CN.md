# TechFlag IDP 社区版

[English README](README.md) · [使用手册](docs/user-manual.zh-CN.md) · [User Manual](docs/user-manual.md) · [GitHub 镜像](https://github.com/techflag/idp)

TechFlag IDP 是一个本地优先的智能文档处理工作台。它帮助开发者和文档 AI 构建者上传文档、解析版面、查看文档树、运行带证据的结构化抽取，并把可复用的抽取逻辑沉淀为基础工作流。

社区版用于本地启动、代码阅读和基础流程评估，默认按自带 provider 配置接入真实解析和模型服务。

## 核心能力

- 默认 `IDP_EDITION=community`。
- 默认使用 SQLite，首次启动不需要单独安装数据库服务器。
- 默认使用本地对象存储；需要公网文件 URL 时可以配置 OSS。
- 默认 OCR 和文档解析引擎是 MinerU。
- OpenAI-compatible LLM provider 用于真实 AI 抽取。
- 单页/基础文档流程，适合学习、评估和二次扩展。
- 前端支持中文和英文。

MinerU Token 申请地址：

```text
https://mineru.net/?source=github
```

## 系统截图

| 登录 | 工作区上传 |
|---|---|
| ![登录](docs/assets/screenshots/01-login.png) | ![工作区上传](docs/assets/screenshots/02-workspace-upload.png) |

| 文档审阅 | AI 抽取结果 |
|---|---|
| ![文档审阅和文档树](docs/assets/screenshots/03-document-review-tree.png) | ![AI 抽取结果](docs/assets/screenshots/04-ai-extraction-result.png) |

## 克隆仓库

Gitee:

```bash
git clone https://gitee.com/techflag/idp.git
cd idp
```

GitHub:

```bash
git clone https://github.com/techflag/idp.git
cd idp
```

## 首次启动

### 准备环境

建议版本：

- Python 3.10+
- Node.js 18+
- npm 9+

### 启动后端

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

后端健康检查：

```text
http://127.0.0.1:5006/api/health
```

默认本地管理员账号：

```text
账号：idp-admin
密码：demo-pass
```

停止后端：

```bash
cd backend
./stop.sh
```

### 启动前端

另开一个终端：

```bash
cd frontend
npm ci
npm run dev -- --host 0.0.0.0
```

浏览器打开：

```text
http://127.0.0.1:5173/idp/
```

登录后使用默认本地空间 `场景应用` 上传文档并体验社区版基础流程。

## 数据库

社区版需要数据库，但默认本地启动不需要单独安装数据库服务器。

后端默认使用 SQLite：

```text
backend/.runtime/idp-community.db
```

这个文件会在本地迁移后生成，不会提交到 Git。

下面这条命令会创建或升级本地表结构：

```bash
cd backend
alembic -c alembic.ini upgrade head
```

`backend/start.sh` 默认也会自动执行这一步。如果你手动用 `python -m app.main` 启动后端，请先执行 Alembic 命令。

如果登录时报 `sqlite3.OperationalError: no such table: users`，执行：

```bash
cd backend
alembic -c alembic.ini upgrade head
python scripts/diagnose_auth.py --ensure-admin --password demo-pass
```

第二条命令会创建或重置本地管理员账号，并确保默认 `场景应用` 空间存在。

## Provider 配置

不配置密钥时，社区版应能完成启动、登录和基础页面浏览。真实文档解析和真实 AI 抽取需要配置 provider。

本地社区版默认不需要 OSS。未配置 OSS 密钥时，上传文件和生成资产会保存到：

```text
backend/.runtime/objects
```

存储模式由 `backend/.env.local` 里的 `OBJECT_STORAGE_PROVIDER` 控制：

- `auto`：有有效 OSS 密钥时使用 OSS，否则使用本地存储
- `local`：始终使用 `backend/.runtime/objects`
- `oss`：强制使用 OSS，缺少密钥时直接报配置错误

默认 OCR 和文档解析引擎是 MinerU。真实文档解析需要配置：

```bash
MINERU_TOKEN=你的 MinerU Token
```

MinerU 云端必须能访问上传文件 URL。默认本地对象存储生成的通常是本地后端 URL，MinerU 云端无法读取。

真实云端解析请二选一：

- 配置 OSS，让上传文件生成公网可访问 URL。
- 或把后端暴露为公网地址，并设置：

```bash
BACKEND_PUBLIC_BASE_URL=https://你的公网后端地址
```

真实 AI 抽取需要配置 OpenAI-compatible 模型：

```bash
DASHSCOPE_API_KEY=你的 LLM Key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=qwen3.6-27b
```

如果没有配置 Token 或 Key，界面应该显示配置提示，不应该进入长期 pending。

## 文档

- [使用手册](docs/user-manual.zh-CN.md)
- [User Manual](docs/user-manual.md)
- [版本策略](docs/edition-policy.md)

## 常用检查

```bash
python3 scripts/check_edition_policy.py
python3 scripts/check_public_export.py /path/to/idp-community-export
```

前端构建：

```bash
cd frontend
npm run build
```

## License

Apache License 2.0. See [LICENSE](LICENSE).
