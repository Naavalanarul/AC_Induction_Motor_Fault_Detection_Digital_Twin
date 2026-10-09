import { test, expect } from '@playwright/test'

test('profile database modal, add motor modal, and sign out modal verification', async ({ page }) => {
  // Set viewport
  await page.setViewportSize({ width: 1400, height: 900 })

  // 1. Log in
  await page.goto('http://localhost:5173')
  await page.getByLabel('Username').fill('admin')
  await page.getByLabel('Password', { exact: true }).fill('admin-pass-123')
  await page.getByRole('button', { name: 'Sign in' }).click()

  // Wait for dashboard to load
  await expect(page.getByText('Fleet Operations Grid')).toBeVisible({ timeout: 15000 })

  // 2. Click the profile chip in the navbar
  const profileChip = page.locator('.nav-profile-chip')
  await expect(profileChip).toBeVisible()
  await profileChip.click()

  // Verify Profile & Database modal opens
  await expect(page.getByText('Operator Profile & Database Settings')).toBeVisible({ timeout: 5000 })
  await expect(page.getByText('DATABASE CONNECTED (ONLINE)')).toBeVisible({ timeout: 5000 })
  await expect(page.getByText('Add MySQL Password & Connection')).toBeVisible()

  // Enter a test MySQL password
  const passwordInput = page.getByPlaceholder('Enter MySQL password')
  await expect(passwordInput).toBeVisible()
  await passwordInput.fill('secret-mysql-pw')

  // Click Test Connection
  await page.getByRole('button', { name: 'Test Connection' }).click()

  // Wait for test feedback banner
  await expect(page.locator('.modal-body').getByText(/Cannot reach MySQL server|Connection failed|Successfully connected|Access denied/i)).toBeVisible({ timeout: 10000 })

  // Capture screenshot of profile modal
  await page.screenshot({
    path: 'test-results/profile_database_modal.png',
  })

  // Close profile modal
  await page.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(page.getByText('Operator Profile & Database Settings')).not.toBeVisible()

  // 3. Open Add Motor modal
  await page.getByRole('button', { name: 'Add Motor' }).click()
  await expect(page.getByText('Add Induction Motor Twin')).toBeVisible()

  // Capture screenshot of Add Motor modal with background color
  await page.screenshot({
    path: 'test-results/add_motor_modal_page_bg.png',
  })

  // Close Add Motor modal
  await page.getByRole('button', { name: 'Cancel' }).click()
  await expect(page.getByText('Add Induction Motor Twin')).not.toBeVisible()

  // 4. Open Sign Out modal
  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page.getByText('Confirm Sign Out')).toBeVisible()

  // Capture screenshot of Sign Out modal with background color
  await page.screenshot({
    path: 'test-results/signout_modal_page_bg.png',
  })

  // Cancel sign out
  await page.getByRole('button', { name: 'Cancel' }).click()
  await expect(page.getByText('Confirm Sign Out')).not.toBeVisible()
})
