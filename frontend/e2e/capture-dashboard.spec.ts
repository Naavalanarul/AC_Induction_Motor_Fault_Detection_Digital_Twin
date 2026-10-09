import { test, expect } from '@playwright/test'

test('capture updated live dashboard screenshot for readme docs', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1100 })

  // 1. Log in
  await page.goto('http://localhost:5173')
  await page.getByLabel('Username').fill('admin')
  await page.getByLabel('Password').fill('admin-pass-123')
  await page.getByRole('button', { name: 'Sign in' }).click()

  // Wait for fleet dashboard to load
  await expect(page.getByText('Fleet Operations Grid')).toBeVisible({ timeout: 20000 })

  // 2. Open first motor digital twin (navigates to live telemetry deck)
  await page.getByRole('button', { name: /Open digital twin for/i }).first().click()

  // Wait for live telemetry HUD to appear
  await expect(page.getByText('SHAFT DYNAMICS')).toBeVisible({ timeout: 20000 })
  await expect(page.getByText('LIVE SENSOR NETWORK')).toBeVisible({ timeout: 10000 })

  // 3. Inject bearing outer fault to match the README description
  const faultSelect = page.getByLabel('fault type')
  if (await faultSelect.isVisible()) {
    await faultSelect.selectOption('bearing_outer')
    const slider = page.getByRole('slider', { name: 'fault severity' })
    if (await slider.isVisible()) {
      await slider.fill('0.6')
    }
    const injectBtn = page.getByRole('button', { name: 'Inject fault' })
    if (await injectBtn.isVisible()) {
      await injectBtn.click()
    }
  }

  // Wait for telemetry frames to stabilize and diagnosis to reflect the fault
  await page.waitForTimeout(4000)

  // 4. Capture screenshot of the modern live operational deck
  await page.screenshot({
    path: 'docs/dashboard.png',
    fullPage: false,
  })

  // Also capture full page screenshot showing footer
  await page.screenshot({
    path: 'test-results/dashboard_with_footer.png',
    fullPage: true,
  })
})
