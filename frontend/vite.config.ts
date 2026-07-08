import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

const defaultApiTarget = 'http://127.0.0.1:8000'
const apiProxyPaths = [
  '/agent-runs',
  '/chat',
  '/contexts',
  '/health',
  '/logs',
  '/memories',
  '/providers',
  '/sessions',
  '/skills',
  '/tools',
]

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiTarget = normalizeApiTarget(
    env.VITE_EVERNIGHTAI_API_BASE || env.EVERNIGHTAI_API_BASE || defaultApiTarget,
  )

  return {
    plugins: [vue()],
    server: {
      proxy: {
        ...Object.fromEntries(
          apiProxyPaths.map((path) => [
            path,
            {
              target: apiTarget,
              changeOrigin: true,
            },
          ]),
        ),
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
