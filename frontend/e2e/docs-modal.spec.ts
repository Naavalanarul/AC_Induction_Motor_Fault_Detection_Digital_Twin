import { test, expect } from '@playwright/test'

test('engineering physics docs book modal, sensor physics, fault detection, and footer verification', async ({ page }) => {
  // Set generous desktop viewport
  await page.setViewportSize({ width: 1440, height: 960 })

  // 1. Log in
  await page.goto('http://localhost:5173')
  await page.getByLabel('Username').fill('admin')
  await page.getByLabel('Password', { exact: true }).fill('admin-pass-123')
  await page.getByRole('button', { name: 'Sign in' }).click()

  // Wait for dashboard to load
  await expect(page.getByText('Fleet Operations Grid')).toBeVisible({ timeout: 15000 })

  // 2. Open Docs via the navbar profile icon
  const profileChip = page.locator('.nav-profile-chip')
  await expect(profileChip).toBeVisible()
  await profileChip.click()

  // Verify Profile modal opens
  await expect(page.getByText('Operator Profile & Database Settings')).toBeVisible({ timeout: 5000 })
  await expect(page.getByText('Physics Engine & Architecture Documentation')).toBeVisible()

  // Open Docs from the profile card button
  const profileOpenDocsBtn = page.getByTestId('profile-open-docs-btn')
  await expect(profileOpenDocsBtn).toBeVisible()
  await profileOpenDocsBtn.click()

  // Verify Engineering Docs Modal is opened
  await expect(page.getByText('AC Induction Motor Digital Twin Documentation')).toBeVisible({ timeout: 5000 })
  await expect(page.getByText('1. State-Space Physics')).toBeVisible()
  await expect(page.getByText('Continuous Electromechanical State-Space Model')).toBeVisible()
  await expect(page.getByText('Technology Stack & Scientific Libraries')).toBeVisible()

  // Capture screenshot of Chapter 1: State-Space Physics
  await page.screenshot({
    path: 'test-results/docs_tab1_physics.png',
  })

  // 3. Switch to Chapter 2: Mathematical Faults
  await page.getByRole('button', { name: '2. Mathematical Faults' }).click()
  await expect(page.getByText('1. Stator Inter-turn Short Circuit (ITSC)')).toBeVisible()
  await expect(page.getByText('2. Broken Rotor Bars (BRB)')).toBeVisible()
  await expect(page.getByText('3. Dynamic Air-Gap Eccentricity')).toBeVisible()
  await expect(page.getByText('4. Rolling Element Bearing Defect Kinematics')).toBeVisible()

  // Capture screenshot of Chapter 2: Mathematical Faults
  await page.screenshot({
    path: 'test-results/docs_tab2_faults.png',
  })

  // 4. Switch to Chapter 3: Sensor Simulation
  await page.getByRole('button', { name: '3. Sensor Simulation' }).click()
  await expect(page.getByText('How Sensor Values are Simulated: First-Principles Signal Synthesis')).toBeVisible()
  await expect(page.getByText('1. Three-Phase Stator Current Channels (IA, IB, IC)')).toBeVisible()
  await expect(page.getByText('2. Three-Phase Voltage Channels (VA, VB, VC)')).toBeVisible()
  await expect(page.getByText('3. Tri-Axial Accelerometer (Vibration x, y, z)')).toBeVisible()
  await expect(page.getByText('4. Acoustic Microphone Channel')).toBeVisible()
  await expect(page.getByText('5. Temperature Sensing (RTD / Thermocouple)')).toBeVisible()

  // Capture screenshot of Chapter 3: Sensor Simulation
  await page.screenshot({
    path: 'test-results/docs_tab3_sensors.png',
  })

  // 5. Switch to Chapter 4: Fault Detection
  await page.getByRole('button', { name: '4. Fault Detection' }).click()
  await expect(page.getByText('How Faults are Detected: The Multi-Modal Diagnostic Engine')).toBeVisible()
  await expect(page.getByText('1. The Digital Twin Current Residual Method')).toBeVisible()
  await expect(page.getByText('2. MCSA Spectral Welch PSD Peak Detection')).toBeVisible()
  await expect(page.getByText('3. Deep Learning Mechanical Classifier (Conv-BiLSTM)')).toBeVisible()
  await expect(page.getByText('4. Weighted Decision Fusion & SADA Supervisory Controller')).toBeVisible()

  // Capture screenshot of Chapter 4: Fault Detection
  await page.screenshot({
    path: 'test-results/docs_tab4_detection.png',
  })

  // 6. Switch to Chapter 5: MCSA & Thermal
  await page.getByRole('button', { name: '5. MCSA & Thermal' }).click()
  await expect(page.getByText('Motor Current Signature Analysis (MCSA) Pipeline')).toBeVisible()
  await expect(page.getByText('4-Node Lumped Parameter Thermal Network (LPTN)')).toBeVisible()
  await expect(page.getByText('Classical Arrhenius Thermal Insulation Life Model & Bearing ISO 281 L10h')).toBeVisible()

  // Capture screenshot of Chapter 5: MCSA & Thermal
  await page.screenshot({
    path: 'test-results/docs_tab5_thermal.png',
  })

  // 7. Switch to Chapter 6: System Architecture
  await page.getByRole('button', { name: '6. System Architecture' }).click()
  await expect(page.getByText('High-Level Software Pipeline Architecture')).toBeVisible()
  await expect(page.getByText('Dual Telemetry Ingestion Modes')).toBeVisible()

  // Capture screenshot of Chapter 6: Architecture
  await page.screenshot({
    path: 'test-results/docs_tab6_architecture.png',
  })

  // 8. Switch to Chapter 7: DSA Foundations
  await page.getByRole('button', { name: '7. DSA Foundations' }).click()
  await expect(page.getByText('Data Structures & Algorithmic Principles in Industrial Twins')).toBeVisible()
  await expect(page.getByText('1. Binary Heap Priority Queue (Fleet Operations Triage)')).toBeVisible()
  await expect(page.getByText('2. Circular Sliding Ring Buffers (Zero-Allocation Telemetry Streams)')).toBeVisible()
  await expect(page.getByText('3. Finite State Machine (FSM) with Asymmetric Hysteresis Debouncing')).toBeVisible()
  await expect(page.getByText('Algorithmic Complexity & Architecture Reference')).toBeVisible()

  // Capture screenshot of Chapter 7: DSA Foundations
  await page.screenshot({
    path: 'test-results/docs_tab7_dsa.png',
  })

  // 9. Switch to Chapter 8: Research Papers & Standards
  await page.getByRole('button', { name: '8. Research Papers & Standards' }).click()
  await expect(page.getByText('Canonical Research Papers & IEEE Standards')).toBeVisible()
  await expect(page.getByText('Current signature analysis to detect induction motor faults')).toBeVisible()

  // Scroll to see more papers
  const nandi = page.getByText('Condition monitoring and fault diagnosis of electrical motors')
  await nandi.scrollIntoViewIfNeeded()
  await expect(nandi).toBeVisible()

  const ieeeStd = page.getByText('IEEE Std 841 & ISO 10816-3 Machine Condition Standards')
  await ieeeStd.scrollIntoViewIfNeeded()
  await expect(ieeeStd).toBeVisible()

  // Capture screenshot of Chapter 8: Research Papers & Standards
  await page.screenshot({
    path: 'test-results/docs_tab8_papers.png',
  })

  // 10. Verify Book Pagination and Page-turning Controls
  await expect(page.getByText('Page 8 of 8')).toBeVisible()

  // Click Previous Chapter button
  await page.getByRole('button', { name: 'Previous Chapter' }).click()
  await expect(page.getByText('Page 7 of 8')).toBeVisible()
  await expect(page.getByText('Data Structures & Algorithmic Principles in Industrial Twins')).toBeVisible()

  // Click Next Chapter button
  await page.getByRole('button', { name: 'Next Chapter' }).click()
  await expect(page.getByText('Page 8 of 8')).toBeVisible()

  // Test Keyboard Arrow Page Turning (Left Arrow)
  await page.keyboard.press('ArrowLeft')
  await expect(page.getByText('Page 7 of 8')).toBeVisible()

  // Test Keyboard Arrow Page Turning (Right Arrow)
  await page.keyboard.press('ArrowRight')
  await expect(page.getByText('Page 8 of 8')).toBeVisible()

  // Close documentation modal via header close button
  await page.getByLabel('Close documentation dialog').click()
  await expect(page.getByText('AC Induction Motor Digital Twin Documentation')).not.toBeVisible()

  // 11. Verify Main Dashboard Global Footer Link & Details
  const appFooter = page.locator('.app-footer')
  await expect(appFooter).toBeVisible()
  const githubLink = appFooter.getByRole('link')
  await expect(githubLink).toBeVisible()
  await expect(githubLink).toHaveAttribute('href', 'https://github.com/Naavalanarul/AC_Induction_Motor_Fault_Detection_Digital_Twin')
  await expect(appFooter.getByText('2026', { exact: true })).toBeVisible()
  await expect(appFooter.getByText('Naavalanarul', { exact: true })).toBeVisible()
  await expect(appFooter.getByText('MIT License', { exact: true })).toBeVisible()

  // 11. Test footer button in Profile modal opens Docs
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
