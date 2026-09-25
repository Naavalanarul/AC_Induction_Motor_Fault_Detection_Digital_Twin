import { defineConfig } from '@playwright/test'

// E2E expects the backend on :8000 (admin/admin-pass-123) and runs the Vite dev server itself.
// CI starts the backend; locally: see README "End-to-end tests".
export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  use: {
    baseURL: 'http://localhost:5173',
    launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {},
  },
  webServer: {
    command: 'npm run dev -- --port 5173 --strictPort',
    url: 'http://localhost:5173',
    reuseExistingServer: true,
  },
})
