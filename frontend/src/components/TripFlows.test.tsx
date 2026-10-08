// Regression tests for the fault-injection / trip / Maintenance-tab bugs (Part 1, bugs 1-3).
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { formatDetail, saveSession } from '../api/client'
import { FAULT_TYPES, type Frame, type Motor } from '../api/types'
import { supervisory } from '../test/fixtures'
import { DEFAULT_FAULT_SEVERITY, FaultConsole } from './FaultConsole'
import { HealthMaintenanceTab } from './HealthMaintenanceTab'
import { formatTimeToThreshold, historyFaultLabel } from './maintenanceFormat'
import { TripBanner } from './TripBanner'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

beforeEach(() => saveSession({ access_token: 'tok', refresh_token: 'r', role: 'operator', username: 'op' }))
afterEach(() => {
  vi.unstubAllGlobals()
  saveSession(null)
})

describe('Bug 1: fault types offered by the UI', () => {
  it('lists only backend-injectable fault types (no diagnosis-only labels)', () => {
    for (const diagOnly of ['overheating', 'supply_anomaly', 'voltage_sag', 'overload', 'overcurrent', 'stall', 'phase_loss']) {
      expect(FAULT_TYPES as readonly string[]).not.toContain(diagOnly)
    }
    expect(FAULT_TYPES).toContain('voltage_anomaly')
  })

  it('renders FastAPI 422 validation errors readably', () => {
    expect(formatDetail([{ loc: ['body', 'fault_type'], msg: 'Input should be ...' }])).toBe('fault_type: Input should be ...')
    expect(formatDetail('plain')).toBe('plain')
  })
})

describe('Bug 3: default severity and trip reset UX', () => {
  it('defaults the severity slider below the DERATE threshold', () => {
    expect(DEFAULT_FAULT_SEVERITY).toBeLessThan(0.5)
    render(<FaultConsole motorId={1} faults={[]} canOperate />)
    expect(screen.getByRole('slider', { name: 'fault severity' })).toHaveValue(String(DEFAULT_FAULT_SEVERITY))
  })

  it('shows a trip notice with a reset button in the fault console', async () => {
    const fetch = vi.fn(async () => json({ id: 1 }))
    vi.stubGlobal('fetch', fetch)
    render(<FaultConsole motorId={3} faults={[]} canOperate tripped tripReason="TRIP_BEARING_OUTER" />)
    expect(screen.getByTestId('fault-console-trip')).toHaveTextContent(/stays stopped until the trip is\s+reset/)
    await userEvent.click(screen.getByRole('button', { name: 'Reset trip' }))
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/v1/motors/3/supervisory/override')
    expect(JSON.parse(init.body as string)).toEqual({ action: 'reset' })
  })

  it('explains that clearing a fault while tripped does not restart the motor', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ id: 4 })))
    render(
      <FaultConsole motorId={2} faults={[{ id: 4, fault_type: 'bearing_outer', severity: 0.9, params: {} }]} canOperate tripped />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'clear fault 4' }))
    expect(await screen.findByText(/stays tripped \(latched\) until you reset/)).toBeInTheDocument()
  })

  it('keeps an acknowledged trip in the banner and offers reset, surfacing a refusal', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ detail: 'cannot reset: minimum cooldown of 5.0s not elapsed' }, 409)))
    render(
      <TripBanner
        trippedMotors={[{ id: 1, name: 'Pump', reason_code: 'TRIP_BEARING_OUTER', acknowledged: true, latched_fault: 'bearing_outer', latched_severity: 0.83 }]}
      />,
    )
    expect(screen.getByText(/latched bearing outer \(sev 0.83\) · acknowledged/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Acknowledge/ })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Reset trip Pump' }))
    expect(await screen.findByText(/Reset refused: cannot reset: minimum cooldown/)).toBeInTheDocument()
  })
})

describe('Bug 2: Maintenance tab after a trip', () => {
  const motor = { id: 1, name: 'Pump', rated_power: 1500, rated_speed: 1450, rated_torque: 10, base_load_nm: 8 } as Motor
  const trippedFrame = {
    health_index: 0,
    zone: 'D',
    error_code: 'VIB-BRGO-D',
    supervisory: { ...supervisory, state: 'TRIP', trip: true, latched_fault: 'bearing_outer', latched_severity: 0.83 },
    diagnosis: { fault_type: 'indeterminate', severity: 0.83, confidence: 0.4, per_sensor_scores: {}, secondary: [] },
  } as unknown as Frame

  function renderTab(frame: Frame, prognosis: unknown, prognosisStatus = 200) {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.includes('/prognosis')) return json(prognosis, prognosisStatus)
        if (url.includes('/recommendation'))
          return json({ fault_type: 'bearing_outer', title: 'CRITICAL: Imminent Bearing Seizure', urgency: 'immediate', zone: 'D', mhi: 0, action: 'Replace bearing', checklist: [] })
        return json({ total: 0, limit: 10, offset: 0, items: [] })
      }),
    )
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return render(
      <QueryClientProvider client={qc}>
        <HealthMaintenanceTab motor={motor} frame={frame} />
      </QueryClientProvider>,
    )
  }

  it('shows an explicit tripped state with the latched fault and severity', async () => {
    renderTab(trippedFrame, { current_severity: 0.83, slope_per_s: 0, time_to_derate_s: null, time_to_trip_s: null, trend: 'stable', sample_count: 120 })
    expect(screen.getByTestId('maintenance-trip-state')).toHaveTextContent(/No prognosis: motor tripped on bearing outer, latched severity 0.83/)
    expect(screen.getByTestId('latched-fault')).toHaveTextContent('bearing outer (severity 0.83)')
    expect(await screen.findByText('CRITICAL: Imminent Bearing Seizure')).toBeInTheDocument()
    expect(screen.queryByText('Indefinite')).not.toBeInTheDocument()
    expect(screen.getAllByText('Tripped')).toHaveLength(2)
  })

  it('shows a failed prognosis query as an error, not as a healthy motor', async () => {
    renderTab({ ...trippedFrame, supervisory: { ...supervisory, trip: false } } as Frame, { detail: 'boom' }, 500)
    expect(await screen.findByTestId('prognosis-error')).toHaveTextContent('Prognosis unavailable: boom')
  })

  it('formats thresholds distinctly: exceeded, not projected, tripped, no data', () => {
    expect(formatTimeToThreshold(null, 0.83, 0.8, false)).toBe('Exceeded')
    expect(formatTimeToThreshold(null, 0.2, 0.8, false)).toBe('Not projected')
    expect(formatTimeToThreshold(90, 0.2, 0.8, false)).toBe('1m 30s')
    expect(formatTimeToThreshold(null, 0.83, 0.8, true)).toBe('Tripped')
    expect(formatTimeToThreshold(undefined, undefined, 0.8, false)).toBe('—')
  })

  it('labels post-trip history rows with the latched fault', () => {
    const row = {
      id: 1, ts: '2026-01-01T00:00:00', fault_type: 'indeterminate', confidence: 0.3, severity_score: 0.83,
      per_sensor_scores_json: { sada_override: { sada_latched_fault: 'bearing_outer' } },
    }
    expect(historyFaultLabel(row)).toBe('indeterminate (tripped on bearing outer)')
  })
})

describe('Bug 2: Diagnosis panel names the latched fault while tripped', () => {
  it('shows the SADA-latched fault under an indeterminate fused verdict', async () => {
    const { DiagnosisPanel } = await import('./DiagnosisPanel')
    const { diagnosis } = await import('../test/fixtures')
    render(
      <DiagnosisPanel
        diagnosis={{
          ...diagnosis,
          fault_type: 'indeterminate',
          per_sensor_scores: {
            ...diagnosis.per_sensor_scores,
            sada_override: { sada_latched_fault: 'bearing_outer', sada_latched_severity: 0.91 },
          } as unknown as typeof diagnosis.per_sensor_scores,
        }}
        mlBackend="rules"
      />,
    )
    expect(screen.getByTestId('fused-latched-fault')).toHaveTextContent('Motor tripped on bearing outer (latched severity 0.91)')
  })
})
