# TechFlag IDP 社区版

[English README](README.md) · [使用手册](docs/user-manual.zh-CN.md) · [User Manual](docs/user-manual.md) · [GitHub 镜像](https://github.com/techflag/idp)

从真实文件构建文档 AI 工作流：OCR、文档树、证据化抽取和可复用文档应用，都在一个本地优先的工作台里完成。

![License](https://img.shields.io/badge/license-Apache--2.0-blue)
![Edition](https://img.shields.io/badge/edition-community-16a34a)
![Backend](https://img.shields.io/badge/backend-FastAPI-009688)
![Frontend](https://img.shields.io/badge/frontend-Vue%203-42b883)

## 项目概览

TechFlag IDP 社区版是一个开源智能文档处理工作台，面向开发者、文档 AI 构建者，以及正在探索 LLM 结构化抽取的团队。

它提供一条完整的本地体验链路：

1. 上传 PDF 或图片。
2. 通过 OCR 和版面识别解析文档。
3. 查看文档树、OCR 块、表格和证据。
4. 基于命中的证据运行 AI 结构化抽取。
5. 将可复用的抽取逻辑沉淀为基础文档应用。

社区版目标是容易启动、容易阅读、容易扩展。默认使用 SQLite 和本地对象存储；当你需要真实解析和真实 AI 抽取时，可以接入自己的 OCR 和 LLM provider。

## 最新动态

- **2026-06-21**：首次公开社区版快照，包含中英文 UI、SQLite 本地初始化、MinerU provider 支持，以及 GitHub/Gitee 发布打包。

## 你可以用它做什么

| 场景 | 社区版提供什么 |
|---|---|
| 文档审阅 | 上传文件，查看 OCR 内容、表格、页码和文档树结构。 |
| 证据化抽取 | 从定位后的文档证据中抽取结构化 JSON，而不是把整份文档盲目交给模型。 |
| 临时抽取 | 输入想提取的数据，系统自动定位相关内容并执行一次性抽取。 |
| 基础文档应用 | 将可重复的抽取步骤保存为轻量工作流，用于同类文档。 |
| 本地评估 | 使用 SQLite 和本地存储快速体验，再按需引入外部基础设施。 |

## 工作原理

### 1. 解析文档

MinerU 是默认 OCR 和文档解析引擎。TechFlag IDP 会保存原始文件，在配置后把可访问的文件 URL 提交给 MinerU，并标准化返回的文本、表格、识别块和版面元数据。

### 2. 构建可审阅证据

系统将解析结果组织为可审阅内容：页面文本、表格、OCR 块、文档树节点和证据引用。目标是让模型输入可见、可查、可解释。

### 3. 先定位，再抽取

抽取不是简单地把所有内容丢给 LLM。系统会先根据当前页、选区或文档树证据缩小目标范围，再基于命中证据进行结构化抽取。

### 4. 复用成功流程

当某个抽取目标可以复用时，可以将它保存为基础文档应用步骤，并在相似文档上再次运行。

## 系统截图

当前图片是公开安全占位图。正式发布自己的 fork 时，可以用干净社区版演示环境截图替换同名文件。

| 登录 | 工作区上传 |
|---|---|
| ![登录](docs/assets/screenshots/01-login.png) | ![工作区上传](docs/assets/screenshots/02-workspace-upload.png) |

| 文档审阅 | AI 抽取结果 |
|---|---|
| ![文档审阅和文档树](docs/assets/screenshots/03-document-review-tree.png) | ![AI 抽取结果](docs/assets/screenshots/04-ai-extraction-result.png) |

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+
- npm 9+

### 1. 克隆仓库

```bash
git clone https://github.com/techflag/idp.git
cd idp
```

国内镜像：

```bash
git clone https://gitee.com/techflag/idp.git
cd idp
```

### 2. 启动后端

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

### 3. 启动前端

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

## 数据库

默认社区版不需要单独安装数据库服务器。

后端默认使用 SQLite：

```text
backend/.runtime/idp-community.db
```

创建或升级数据库：

```bash
cd backend
alembic -c alembic.ini upgrade head
```

`backend/start.sh` 默认也会自动执行迁移。如果登录时报 `sqlite3.OperationalError: no such table: users`，执行：

```bash
cd backend
alembic -c alembic.ini upgrade head
python scripts/diagnose_auth.py --ensure-admin --password demo-pass
```

## Provider 配置

不配置 provider key 时，应用仍然可以启动和登录。真实 OCR 解析和真实 AI 抽取需要配置 provider。

### MinerU OCR 和文档解析

MinerU 是默认 OCR 和文档解析引擎。MinerU Token 申请地址：

```text
https://mineru.net/?source=github
```

配置：

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

### 对象存储

本地社区版默认不需要 OSS。未配置 OSS 密钥时，上传文件和生成资产会保存到：

```text
backend/.runtime/objects
```

存储模式由 `backend/.env.local` 里的 `OBJECT_STORAGE_PROVIDER` 控制：

- `auto`：有有效 OSS 密钥时使用 OSS，否则使用本地存储
- `local`：始终使用 `backend/.runtime/objects`
- `oss`：强制使用 OSS，缺少密钥时直接报配置错误

### LLM 抽取

真实 AI 抽取需要配置 OpenAI-compatible 模型：

```bash
DASHSCOPE_API_KEY=你的 LLM Key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=qwen3.6-27b
```

如果没有配置 Token 或 Key，界面应该显示配置提示，不应该进入长期 pending。

## 功能特性

- 本地优先的后端和前端。
- SQLite 首次启动体验。
- 本地对象存储兜底。
- MinerU OCR 和文档解析 provider。
- OpenAI-compatible LLM 抽取 provider。
- 文档树、OCR 块、表格和证据审阅。
- 临时抽取和基础可复用文档应用。
- 前端支持中文和英文。
- 社区版公开导出护栏。

## 社区版范围

这个仓库面向本地启动、代码阅读、provider 集成和基础文档 AI 流程评估。社区版聚焦单页/基础流程，同时保留可扩展的架构。

## FAQ

**必须使用 MinerU 吗？**  
系统可以不配置 MinerU Token 启动，但真实文档解析需要 `MINERU_TOKEN`。MinerU 是默认 OCR 和解析引擎。

**需要数据库服务器吗？**  
不需要。默认社区版使用本地 SQLite。

**为什么 MinerU 需要公网文件 URL？**  
MinerU 云端需要拉取上传文件。`127.0.0.1` 这类本地地址无法从云端访问。

**可以使用自己的 LLM provider 吗？**  
可以。社区版使用 OpenAI-compatible provider 接口。

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

## 沟通

- Bug 和功能建议请使用 GitHub Issues。
- 使用问题、想法和社区反馈可以放到 GitHub Discussions。

## License

Apache License 2.0. See [LICENSE](LICENSE).
