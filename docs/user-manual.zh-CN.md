# TechFlag IDP 社区版使用手册

[English](user-manual.md)

本文说明如何在本地启动 GitHub 社区版，并完成第一次文档处理体验。

## 1. 可以体验什么

社区版提供一个本地智能文档处理工作台：

- 上传 PDF 或图片文档。
- 即使解析失败，也保留原始文件可预览。
- 通过可配置的 MinerU provider 解析文档。
- 查看原文、识别结果、文档树、JSON 和抽取结果。
- 使用自己的 OpenAI-compatible 模型试跑基础 AI 抽取。
- 使用社区版单页/基础流程。

社区版不包含商业版长文档执行、批量处理、企业连接器、HITL 流程、完整发布/应用市场流程和商业恢复链路。

## 2. 启动系统

### 后端

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

### 前端

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

默认本地管理员：

```text
账号：idp-admin
密码：demo-pass
```

## 3. 语言

前端支持中文和英文。

- 首次访问会尽量使用浏览器语言。
- 可以在右上角语言切换控件中切换。
- 语言选择会保存到 `localStorage`，key 为 `idp.locale`。
- 上传文档内容、OCR 文本、模型输出、Skill Markdown、文件名和后端返回的业务数据不会被翻译。

可选环境变量：

```bash
VITE_DEFAULT_LOCALE=en-US
```

允许值为 `zh-CN` 和 `en-US`。

## 4. 数据库

社区版需要数据库，但默认本地启动不需要单独安装数据库服务器。

默认使用 SQLite：

```text
backend/.runtime/idp-community.db
```

启动脚本会自动执行数据库迁移。如果手动启动后端，请先执行：

```bash
cd backend
alembic -c alembic.ini upgrade head
python scripts/diagnose_auth.py --ensure-admin --password demo-pass
```

如果登录时报 `sqlite3.OperationalError: no such table: users`，说明表结构还没创建，执行上面的命令即可。

## 5. 上传文档

1. 使用 `idp-admin` 登录。
2. 打开默认本地空间 `场景应用`。
3. 点击上传按钮。
4. 选择 PDF 或图片文件。
5. 系统创建任务，并保留原始文件用于预览。

如果未配置解析 provider，上传仍会成功。原始文件仍可见，解析会以明确失败状态结束，不会长期 pending。

## 6. 配置 MinerU 解析

MinerU Token 申请地址：

```text
https://mineru.net/?source=github
```

写入 `backend/.env.local`：

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

Token 或公网文件 URL 缺失时，任务应明确失败，并保留可重试状态。

## 7. 配置 AI 抽取

在 `backend/.env.local` 配置 OpenAI-compatible 模型：

```bash
DASHSCOPE_API_KEY=你的 LLM Key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=qwen3.6-27b
```

没有 LLM Key 时，系统仍可启动并浏览基础页面。真实 AI 抽取会显示配置提示，不会长期 pending。

## 8. 运行基础抽取

1. 打开已解析任务。
2. 查看原文和识别结果。
3. 选择或确认目标内容。
4. 运行抽取。
5. 查看字段、表格、JSON 和证据。

社区版保持单页/基础体验。长文档、跨页商业执行链路不包含在 GitHub 社区仓库中。

## 9. 常见问题

### 后端能启动，但登录失败

执行数据库迁移和管理员初始化：

```bash
cd backend
alembic -c alembic.ini upgrade head
python scripts/diagnose_auth.py --ensure-admin --password demo-pass
```

### 上传成功，但解析失败

检查：

- 是否配置 `MINERU_TOKEN`。
- 上传文件 URL 是否能被 MinerU 云端访问。
- 真实云端解析是否配置 OSS 或 `BACKEND_PUBLIC_BASE_URL`。

### AI 抽取无法运行

检查：

- 是否配置 `DASHSCOPE_API_KEY`。
- `DASHSCOPE_BASE_URL` 和 `DASHSCOPE_MODEL` 是否正确。
- 修改 `.env.local` 后是否重启后端。

### 前端无法连接后端

Vite 开发服务默认把 `/idp-api` 代理到 `http://127.0.0.1:5006/api`。如果后端运行在其他地址，请设置 `VITE_PROXY_TARGET`。

## 10. 常用命令

```bash
# 后端测试
python3 -m pytest backend/tests -q

# 前端构建
cd frontend
npm run build

# 版本护栏
python3 scripts/edition_guardrail_agent.py
```
