# IDP 前端

[English](README.md)

社区版前端基于 Vue 3、TypeScript、Vite、Pinia 和 Arco Design。

首次启动请优先阅读项目根目录 [README.md](../README.md)。

前端支持中文和英文。可以通过 `VITE_DEFAULT_LOCALE=zh-CN` 或 `VITE_DEFAULT_LOCALE=en-US` 设置默认语言；用户也可以在全局 Header 中切换。

## 本地开发

```bash
cd frontend
npm ci
npm run dev -- --host 0.0.0.0
```

默认访问地址：

```text
http://127.0.0.1:5173/idp/
```

开发环境会把 `/idp-api` 代理到后端：

```text
http://127.0.0.1:5006/api
```

如需修改代理目标，请复制并调整 `.env.example` 中的 `VITE_PROXY_TARGET`。

## 构建

```bash
npm run build
```
