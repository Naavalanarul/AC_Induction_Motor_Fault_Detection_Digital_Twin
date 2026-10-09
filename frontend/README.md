# Frontend — Motor Digital Twin Dashboard

A modern, high-performance web application for the AC Induction Motor Digital Twin. Built with
React 19, TypeScript, Vite, Tailwind CSS v4, Recharts, and TanStack Query.

## Quick Start

```bash
npm ci
npm run dev          # http://localhost:5173 (proxies /api and WebSocket to :8000)
npm test             # run Vitest unit test suite (49 tests)
npm run lint         # ESLint check
npm run typecheck    # TypeScript compiler check (tsc -b)
npm run build        # production build in dist/
npx playwright test  # 7 E2E specs against running backend
```

## Application Modes & Views

### 1. Authentication & Mode Selector (`LoginForm.tsx`)
- **Press-and-Hold Password Reveal:** Equipped with an accessible eye icon (`Eye` / `EyeOff` from `lucide-react`). Passwords remain masked by default and are revealed exclusively while the button is actively held down via pointer events (`pointerdown`, `pointerup`, `pointercancel`, `pointerleave`) or keyboard keys (`Space` / `Enter` on `keydown`/`keyup`). Focus and text selection are preserved, and form submission is prevented.
- **Session Landing Mode:** Operators can choose their landing view prior to sign-in:
  - **Live twin** (default): Lands directly on the real-time telemetry deck and fleet manager.
  - **Static analysis**: Lands directly on the offline Static-Value Diagnosis Workbench.

### 2. Live Twin Operations (`App.tsx`, `TelemetryDeck.tsx`, `SadaControl.tsx`)
- **Real-Time Telemetry Deck:** Streams 10 Hz WebSocket telemetry with automatic reconnection, heartbeat, and backoff. Displays 3-phase stator current and voltage waveforms, speed, torque, 4-node LPTN thermal temperatures ($T_w, T_t, T_r, T_b$), Arrhenius insulation RUL, and tri-axial vibration.
- **Signal Analysis:** Fast Fourier Transform (FFT) vibration spectra, continuous wavelet scalograms, and high-resolution Motor Current Signature Analysis (MCSA) with automated $f_{BRB}$ and $f_{ecc}$ peak detection.
- **Sensor Channel Abstraction:** Toggle channels between simulated physical models and hardware sensors behind a circuit breaker.
- **Fault Injection Console:** Inject Stator ITSC, Broken Rotor Bars, Eccentricity, Bearing faults, Thermal stress, and Voltage unbalance with configurable severity and idempotency keys.
- **Supervisory Control (SADA):** Visualizes the Supervisory Anomaly Detection & Action finite state machine (NORMAL, WARNING, DERATE, TRIP, LOCKOUT) with operator acknowledge, manual load demand override, and thermal cooldown reset.
- **Fleet Grid & Provisioning:** Manage multiple induction motors, switch active streams, and provision motors using 7 industry presets (e.g. 1.5 kW NEMA B, 2.2 kW IEC, high-inertia) or custom equivalent-circuit parameters.
- **Interactive Engineering Book (`EngineeringDocsModal.tsx`):** 8-chapter documentation modal featuring book spine styling, turn-page navigation, mathematical state-space formulations, DSA algorithms, and research citations with DOI links.

### 3. Static-Value Diagnosis Workbench (`StaticDiagnosisPanel.tsx`)
An offline diagnostic mode for field service engineers and operators entering manual scalar measurements without requiring a running simulator or physical sensors:
- **Motor Identification:** Select any registered fleet motor to inherit its equivalent circuit parameters, or input custom nameplate ratings (rated power, voltage, current, speed, poles, frequency, insulation class).
- **Measurement Inputs:**
  - **Electrical:** 3-phase RMS voltages with basis selectors (`line_line` vs. `line_neutral` and `rms` vs. `peak`), 3-phase RMS currents, shaft speed (RPM), and line frequency (Hz).
  - **Thermal:** Winding and ambient temperatures (°C).
  - **Mechanical Vibration:** Overall RMS vibration (mm/s), 1X / 2X shaft harmonics, and bearing defect frequencies (BPFO, BPFI, BSF, FTF).
  - **MCSA Sidebands:** Current spectral sideband amplitudes in dB at $f(1 \pm 2ks)$ and $f \pm f_r$.
  - **Power & Supply:** Input active power, power factor, and voltage THD.
- **11 Physics-Derived Presets:** Pre-fills the form with verified steady-state operating points generated directly from motor physics:
  1. *Healthy Baseline* — Rated balanced 400 V, 50 Hz, 1425 RPM.
  2. *Voltage Sag* — 340 V supply sag triggering supply warning.
  3. *Voltage Imbalance* — 380 V / 415 V / 405 V creating negative-sequence currents.
  4. *Overload* — 4.2 A continuous draw above 3.5 A rated current.
  5. *Motor Stall* — 0 RPM locked rotor with 15.0 A inrush current.
  6. *Inter-turn Short Circuit (ITSC)* — Severe stator current unbalance and negative-sequence residual.
  7. *Broken Rotor Bars (BRB)* — Elevated MCSA sidebands (-28 dB).
  8. *Bearing Outer Race Fault* — Elevated BPFO vibration amplitude (3.8 mm/s).
  9. *Overheating* — 162 °C stator temperature exceeding Class F trip threshold.
  10. *High Vibration* — 8.2 mm/s overall RMS vibration indicating mechanical fault.
  11. *Supply Distortions* — 6.8 % voltage THD exceeding NEMA limits.
- **Diagnosis Results Deck:**
  - **Motor Health Index (MHI):** Visualized via SVG `HealthGauge` (0–100 scale) and color-coded condition zone (Normal, Watch, Alarm, Trip).
  - **Actionable Advisory:** Diagnostic verdict, standard error code, and advisory recommendations (strictly advisory; snapshots never drive physical SADA control actions).
  - **Input Coverage Strip:** Displays active assessment completeness and recommends optional parameters that would improve diagnostic certainty.
  - **Channel Breakdown Table:** Displays individual verdicts, confidence, and severity for Supply, Protection, Thermal, Electrical, Mechanical, and Spectral channels. Channels lacking required data report **"not assessable"** with explicit reasons rather than false-positive healthy verdicts.
  - **Analysis History:** Saves historical analyses to the backend database with retrieval and inspection.

### 4. Diagnosis History & Audit (`HistoryTable.tsx`)
- Historical database query tool with timestamp ranges, fault type filters, and severity thresholds.
- Audit alert feed for supervisory actions, forced operator overrides, and system events.

## Design System & Accessibility
- **Design Tokens:** Strict semantic color slots defined in `src/index.css`:
  - Phases: `Phase A` (amber), `Phase B` (sky blue), `Phase C` (emerald) — validated for color-vision deficiency.
  - SADA States: `NORMAL` (emerald), `WARNING` (amber), `DERATE` (orange), `TRIP` (rose), `LOCKOUT` (purple).
- **Screen Reader Support:** Full ARIA labeling (`aria-label`, `aria-pressed`, `aria-describedby`, `htmlFor` bindings).
- **Keyboard Navigation:** Full tab order and keyboard control for modals, forms, and reveal buttons.

## Testing

```bash
# Unit & component tests (49 tests across 6 suites)
npm test

# End-to-end browser tests via Playwright (7 tests in headless Chromium)
npx playwright test
```
