import { existsSync } from 'node:fs'
import { defineConfig } from '@playwright/test'

// Chromium binary: PW_CHROMIUM_PATH wins; otherwise use the pre-installed browser of the cloud dev
// container when present (its revision is older than the one @playwright/test downloads). Elsewhere,
// including CI, Playwright's own `npx playwright install chromium` browser is used.
const PREINSTALLED_CHROMIUM = '/opt/pw-browsers/chromium'
const chromiumPath =
  process.env.PW_CHROMIUM_PATH || (existsSync(PREINSTALLED_CHROMIUM) ? PREINSTALLED_CHROMIUM : undefined)

// E2E expects the backend on :8000 (admin/admin-pass-123) and runs the Vite dev server itself.
// CI starts the backend; locally: see README "End-to-end tests".
export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  use: {
    baseURL: 'http://localhost:5173',
    launchOptions: chromiumPath ? { executablePath: chromiumPath } : {},
  },
  webServer: {
    command: 'npm run dev -- --port 5173 --strictPort',
    url: 'http://localhost:5173',
    reuseExistingServer: true,
  },
})
