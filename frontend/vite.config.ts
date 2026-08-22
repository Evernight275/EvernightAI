import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

const defaultApiTarget = 'http://127.0.0.1:8000'
const apiPaths = [
  '/agent-runs',
  '/contexts',
  '/data-analysis',
  '/health',
  '/logs',
  '/memories',
  '/providers',
  '/ready',
  '/sessions',
  '/skills',
  '/tools',
]

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiTarget = normalizeApiTarget(
    env.EVERNIGHTAI_API_PROXY_TARGET || defaultApiTarget,
  )

  return {
    plugins: [vue()],
    build: {
      rollupOptions: {
        input: ['index.html', 'chat.html'],
      },
    },
    server: {
      proxy: {
        ...Object.fromEntries(apiPaths.map((path) => [path, {
          target: apiTarget,
          changeOrigin: true,
        }])),
        '^/chat(?:$|/)': {
          target: apiTarget,
          changeOrigin: true,
        },
        '/ws': {
          target: apiTarget,
          changeOrigin: true,
          ws: true,
        },
      },
    },
  }
})

function normalizeApiTarget(value: string): string {
  return value.trim().replace(/\/+$/, '') || defaultApiTarget
}
