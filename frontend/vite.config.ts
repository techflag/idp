import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const proxyTarget = env.VITE_PROXY_TARGET || env.VITE_DEV_API_PROXY_TARGET || 'http://127.0.0.1:5006'

  return {
    base: '/idp/',
    appType: 'spa',
    server: {
      proxy: {
        '/idp-api': {
          target: proxyTarget,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/idp-api/, '/api'),
        },
      },
    },
    plugins: [
      vue(),
      {
        name: 'idp-uploads-dev-rewrite',
        configureServer(server) {
          server.middlewares.use((req, _res, next) => {
            const request = req as typeof req & { url?: string }
            if (request.url?.startsWith('/idp-uploads/')) {
              request.url = request.url.replace(/^\/idp-uploads/, '')
            }
            next()
          })
        },
      },
    ],
  }
})
