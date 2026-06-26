import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/agent-runs': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/chat': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/contexts': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/memories': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/providers': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/sessions': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/skills': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/tools': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
