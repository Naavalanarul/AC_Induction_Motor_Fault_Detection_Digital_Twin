import { expect, test } from '@playwright/test'

const USER = process.env.E2E_USER ?? 'admin'
const PASS = process.env.E2E_PASS ?? 'admin-pass-123'

test('inject fault -> see it in the dashboard -> see SADA derate', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Username').fill(USER)
  await page.getByLabel('Password').fill(PASS)
  await page.getByRole('button', { name: 'Sign in' }).click()

  await expect(page.getByTestId('fused-fault')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByTestId('sada-state')).toHaveText(/Normal/, { timeout: 30_000 })
  await page.screenshot({ path: 'e2e-results/healthy.png', fullPage: true })

  await page.getByLabel('fault type').selectOption('bearing_outer')
  await page.getByRole('slider', { name: 'fault severity' }).fill('0.6')
  await page.getByRole('button', { name: 'Inject fault' }).click()

  await expect(page.getByTestId('fused-fault')).toHaveText(/bearing outer/, { timeout: 20_000 })
  await expect(page.getByTestId('sada-state')).toHaveText(/Watch|Derate|Trip/, { timeout: 30_000 })
  await page.screenshot({ path: 'e2e-results/faulted.png', fullPage: true })

  // clean up: clear the fault so reruns start healthy
  await page.getByRole('button', { name: /clear fault/ }).first().click()
})
