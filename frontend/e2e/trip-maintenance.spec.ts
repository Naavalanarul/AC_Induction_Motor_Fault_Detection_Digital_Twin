import { expect, test } from '@playwright/test'

const USER = process.env.E2E_USER ?? 'admin'
const PASS = process.env.E2E_PASS ?? 'admin-pass-123'

// Regression for the TRIP flow: Maintenance tab must show the latched fault and the correct
// recommendation, and the trip must be resettable from the UI after the fault is cleared.
test('trip -> maintenance tab shows latched fault -> clear + reset restores the motor', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Username').fill(USER)
  await page.getByLabel('Password', { exact: true }).fill(PASS)
  await page.getByRole('button', { name: 'Sign in' }).click()

  await page.getByRole('button', { name: /Open digital twin for/i }).first().click()
  await page.getByRole('button', { name: 'Parameters Studio', exact: true }).click()
  await expect(page.getByTestId('fused-fault')).toBeVisible({ timeout: 20_000 })

  await page.getByLabel('fault type').selectOption('bearing_outer')
  await page.getByRole('slider', { name: 'fault severity' }).fill('0.95')
  await page.getByRole('button', { name: 'Inject fault' }).click()

  await expect(page.getByText(/EMERGENCY TRIP ACTIVE/)).toBeVisible({ timeout: 40_000 })
  await expect(page.getByTestId('fault-console-trip')).toBeVisible()

  await page.getByRole('button', { name: 'Maintenance', exact: true }).click()
  await expect(page.getByTestId('maintenance-trip-state')).toContainText(/No prognosis: motor tripped on bearing outer/, {
    timeout: 20_000,
  })
  await expect(page.getByTestId('latched-fault')).toContainText('bearing outer')
  await expect(page.getByTestId('fused-latched-fault').first()).toContainText('Motor tripped on bearing outer')
  await expect(page.getByText(/Bearing/).first()).toBeVisible()
  await page.screenshot({ path: 'e2e-results/maintenance-tripped.png', fullPage: true })

  await page.getByRole('button', { name: 'Parameters Studio', exact: true }).click()
  await page.getByRole('button', { name: /clear fault/ }).first().click()
  await expect(page.getByText(/stays tripped \(latched\)/)).toBeVisible()

  // the backend refuses a reset during the 5 s cooldown; retry until accepted
  await expect(async () => {
    await page.getByTestId('fault-console-trip').getByRole('button', { name: 'Reset trip' }).click()
    await expect(page.getByText('Trip reset: motor restarting')).toBeVisible({ timeout: 2_000 })
  }).toPass({ timeout: 45_000 })
  await expect(page.getByText(/EMERGENCY TRIP ACTIVE/)).toBeHidden({ timeout: 30_000 })
  await expect(page.getByTestId('sada-state').first()).toHaveText(/Normal/, { timeout: 30_000 })
})
