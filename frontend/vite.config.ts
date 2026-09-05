import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  return {
    // The staging preview is intentionally mounted below the still-live Jinja
    // app. Production builds stay rooted at / for the eventual Caddy cutover.
    base: mode === 'preview' ? '/preview/' : '/',
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        '@': path.resolve(import.meta.dirname, './src'),
      },
    },
    server: {
      // Caddy owns this split after the SPA cutover. The development proxy keeps
      // browser cookies same-origin while FastAPI continues on its own port.
      proxy: {
        '/api': {
          target: env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8321',
          changeOrigin: true,
        },
      },
    },
  }
})
