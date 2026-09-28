/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const backend = process.env.VITE_BACKEND_URL ?? 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    headers: {
      'Cache-Control': 'no-store, no-cache, must-revalidate',
    },
    proxy: {
      '/api': { target: backend, changeOrigin: true, ws: true },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'], // e2e/ is Playwright's, not Vitest's
    css: false,
  },
})
