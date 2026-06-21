# IDP Frontend

[中文](README.zh-CN.md)

The community frontend is built with Vue 3, TypeScript, Vite, Pinia, and Arco Design.

For first-time setup, start with the root [README.md](../README.md).

The UI supports Chinese and English. Set `VITE_DEFAULT_LOCALE=zh-CN` or `VITE_DEFAULT_LOCALE=en-US` to choose the default locale; users can switch language in the global header.

## Local Development

```bash
cd frontend
npm ci
npm run dev -- --host 0.0.0.0
```

Default URL:

```text
http://127.0.0.1:5173/idp/
```

The development server proxies `/idp-api` to:

```text
http://127.0.0.1:5006/api
```

To change the proxy target, copy and adjust `VITE_PROXY_TARGET` from `.env.example`.

## Build

```bash
npm run build
```
