import { test, expect } from '@playwright/test'

test('engineering physics docs modal and profile docs button verification', async ({ page }) => {
  // Set generous desktop viewport
  await page.setViewportSize({ width: 1440, height: 960 })

  // 1. Log in
  await page.goto('http://localhost:5173')
  await page.getByLabel('Username').fill('admin')
  await page.getByLabel('Password').fill('admin-pass-123')
  await page.getByRole('button', { name: 'Sign in' }).click()

  // Wait for dashboard to load
  await expect(page.getByText('Fleet Operations Grid')).toBeVisible({ timeout: 15000 })

  // 2. Click Docs button directly from navbar
  const navbarDocsBtn = page.getByTestId('navbar-docs-btn')
  await expect(navbarDocsBtn).toBeVisible()
  await navbarDocsBtn.click()

  // Verify Engineering Docs Modal is opened
  await expect(page.getByText('AC Induction Motor Digital Twin Documentation')).toBeVisible({ timeout: 5000 })
  await expect(page.getByText('1. State-Space Physics')).toBeVisible()
  await expect(page.getByText('Continuous Electromechanical State-Space Model')).toBeVisible()

  // Capture screenshot of Tab 1: State-Space Physics
  await page.screenshot({
    path: '/Users/naavalanarul/.gemini/antigravity/brain/c5c295fc-927e-4ee2-ad31-d20f0b87e5b6/docs_tab1_physics.png',
  })

  // 3. Switch to Tab 2: Mathematical Faults
  await page.getByRole('button', { name: '2. Mathematical Faults' }).click()
  await expect(page.getByText('1. Stator Inter-turn Short Circuit (ITSC)')).toBeVisible()
  await expect(page.getByText('2. Broken Rotor Bars (BRB)')).toBeVisible()
  await expect(page.getByText('3. Dynamic Air-Gap Eccentricity')).toBeVisible()
  await expect(page.getByText('4. Rolling Element Bearing Defect Kinematics')).toBeVisible()

  // Capture screenshot of Tab 2: Mathematical Faults
  await page.screenshot({
    path: '/Users/naavalanarul/.gemini/antigravity/brain/c5c295fc-927e-4ee2-ad31-d20f0b87e5b6/docs_tab2_faults.png',
  })

  // 4. Switch to Tab 3: MCSA & 4-Node LPTN
  await page.getByRole('button', { name: '3. MCSA & 4-Node LPTN' }).click()
  await expect(page.getByText('Motor Current Signature Analysis (MCSA) Pipeline')).toBeVisible()
  await expect(page.getByText('4-Node Lumped Parameter Thermal Network (LPTN)')).toBeVisible()
  await expect(page.getByText('Classical Arrhenius Thermal Insulation Life Model')).toBeVisible()

  // 5. Switch to Tab 4: System Architecture
  await page.getByRole('button', { name: '4. System Architecture' }).click()
  await expect(page.getByText('High-Level Software Pipeline Architecture')).toBeVisible()
  await expect(page.getByText('Dual Telemetry Ingestion Modes')).toBeVisible()

  // 6. Switch to Tab 5: Research Papers & Standards
  await page.getByRole('button', { name: '5. Research Papers & Standards' }).click()
  await expect(page.getByText('Canonical Research Papers & IEEE Standards')).toBeVisible()
  await expect(page.getByText('Current signature analysis to detect induction motor faults')).toBeVisible()

  // Scroll to see more papers (some may be below the fold)
  const nandi = page.getByText('Condition monitoring and fault diagnosis of electrical motors')
  await nandi.scrollIntoViewIfNeeded()
  await expect(nandi).toBeVisible()

  const ieeeStd = page.getByText('IEEE Std 841 & ISO 10816-3 Machine Condition Standards')
  await ieeeStd.scrollIntoViewIfNeeded()
  await expect(ieeeStd).toBeVisible()

  // Capture screenshot of Tab 5: Research Papers & Standards
  await page.screenshot({
    path: '/Users/naavalanarul/.gemini/antigravity/brain/c5c295fc-927e-4ee2-ad31-d20f0b87e5b6/docs_tab5_papers.png',
  })

  // Close documentation modal via header close button
  await page.getByLabel('Close documentation dialog').click()
  await expect(page.getByText('AC Induction Motor Digital Twin Documentation')).not.toBeVisible()

  // 7. Verify opening Docs from inside the Profile section
  const profileChip = page.locator('.nav-profile-chip')
  await expect(profileChip).toBeVisible()
  await profileChip.click()

  // Verify Profile modal opens
  await expect(page.getByText('Operator Profile & Database Settings')).toBeVisible({ timeout: 5000 })
  await expect(page.getByText('Physics Engine & Architecture Documentation')).toBeVisible()

  // Click the Open Docs button inside the profile card
  const profileOpenDocsBtn = page.getByTestId('profile-open-docs-btn')
  await expect(profileOpenDocsBtn).toBeVisible()
  await profileOpenDocsBtn.click()

  // Profile modal should close and docs modal should open
  await expect(page.getByText('AC Induction Motor Digital Twin Documentation')).toBeVisible({ timeout: 5000 })

  // Close docs modal via bottom button
  await page.getByRole('button', { name: 'Close Documentation', exact: true }).click()
  await expect(page.getByText('AC Induction Motor Digital Twin Documentation')).not.toBeVisible()

  // 8. Test footer button in Profile modal
  await profileChip.click()
  await expect(page.getByText('Operator Profile & Database Settings')).toBeVisible({ timeout: 5000 })

  // Click the footer docs button
  const footerDocsBtn = page.getByTestId('profile-footer-docs-btn')
  await expect(footerDocsBtn).toBeVisible()
  await footerDocsBtn.click()

  // Profile modal should close and docs modal should open again
  await expect(page.getByText('AC Induction Motor Digital Twin Documentation')).toBeVisible({ timeout: 5000 })

  // Close docs modal
  await page.getByLabel('Close documentation dialog').click()
  await expect(page.getByText('AC Induction Motor Digital Twin Documentation')).not.toBeVisible()
})
