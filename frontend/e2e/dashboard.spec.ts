import { expect, test } from '@playwright/test'

const USER = process.env.E2E_USER ?? 'admin'
const PASS = process.env.E2E_PASS ?? 'admin-pass-123'

test('fleet dashboard renders summary tiles and navigates to motor twin', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Username').fill(USER)
  await page.getByLabel('Password').fill(PASS)
  await page.getByRole('button', { name: 'Sign in' }).click()

  // Verify Fleet Dashboard elements
  await expect(page.getByText('Fleet Operations Grid')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText('Fleet Size')).toBeVisible()
  await expect(page.getByText('Avg Health Index')).toBeVisible()

  // Navigate to motor digital twin and open Maintenance section
  await page.getByRole('button', { name: /Open digital twin for/i }).first().click()
  await page.getByRole('button', { name: 'Maintenance', exact: true }).click()
  await expect(page.getByTestId('fused-fault')).toBeVisible({ timeout: 20_000 })
})

test('inject fault -> see it in the dashboard -> see SADA derate', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Username').fill(USER)
  await page.getByLabel('Password').fill(PASS)
  await page.getByRole('button', { name: 'Sign in' }).click()

  // Navigate to motor digital twin and open Maintenance section
  await page.getByRole('button', { name: /Open digital twin for/i }).first().click()
  await page.getByRole('button', { name: 'Maintenance', exact: true }).click()

  await expect(page.getByTestId('fused-fault')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByTestId('sada-state').first()).toHaveText(/Normal/, { timeout: 30_000 })
  await page.screenshot({ path: 'e2e-results/healthy.png', fullPage: true })

  await page.getByLabel('fault type').selectOption('bearing_outer')
  await page.getByRole('slider', { name: 'fault severity' }).fill('0.6')
  await page.getByRole('button', { name: 'Inject fault' }).click()

  await expect(page.getByTestId('fused-fault')).toHaveText(/bearing outer/, { timeout: 20_000 })
  await expect(page.getByTestId('sada-state').first()).toHaveText(/Watch|Derate|Trip/, { timeout: 30_000 })
  await page.screenshot({ path: 'e2e-results/faulted.png', fullPage: true })

  // clean up: clear the fault and reset trip if latched so reruns start healthy
  await page.getByRole('button', { name: /clear fault/ }).first().click()
  const resetBtn = page.getByRole('button', { name: /reset trip/i }).first()
  if (await resetBtn.isEnabled().catch(() => false)) {
    await resetBtn.click().catch(() => {})
  }
})
