import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { saveSession } from '../api/client'
import { diagnosis, supervisory } from '../test/fixtures'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AlertsModal } from './AlertsModal'
import { DiagnosisPanel } from './DiagnosisPanel'
import { FaultConsole } from './FaultConsole'
import { HealthGauge } from './HealthGauge'
import { HistoryView } from './HistoryView'
import { MotorCard } from './MotorCard'
import { MotorParamsStudio } from './MotorParamsStudio'
import { SadaPanel } from './SadaPanel'
import { StatusBadge } from './StatusBadge'
import { TripBanner } from './TripBanner'
import type { Frame } from '../api/types'

function mockFetch(body: unknown = {}, status = 200) {
  const fn = vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
  vi.stubGlobal('fetch', fn)
  return fn
}

beforeEach(() => saveSession({ access_token: 'tok', refresh_token: 'r', role: 'operator', username: 'op' }))
afterEach(() => {
  vi.unstubAllGlobals()
  saveSession(null)
})

describe('StatusBadge', () => {
  it('pairs status color with icon and text label', () => {
    render(<StatusBadge state="TRIP" />)
    expect(screen.getByTestId('sada-state')).toHaveTextContent('Trip')
    expect(screen.getByTestId('sada-state')).toHaveTextContent('■')
  })
})

describe('DiagnosisPanel', () => {
  it('shows fused verdict and per-channel scores', () => {
    render(<DiagnosisPanel diagnosis={diagnosis} mlBackend="conv_bilstm" />)
    expect(screen.getByTestId('fused-fault')).toHaveTextContent('bearing outer')
    expect(screen.getByRole('meter', { name: 'diagnosis confidence' })).toHaveAttribute('aria-valuenow', '93')
    const row = screen.getByText(/Vibration \/ acoustic/).closest('tr')!
    expect(within(row).getByText('Conv-BiLSTM', { exact: false })).toBeInTheDocument()
    expect(within(row).getByText('0.93')).toBeInTheDocument()
    expect(screen.getByText('unavailable')).toBeInTheDocument()
    expect(screen.getByText(/Also considered: unbalance/)).toBeInTheDocument()
  })

  it('renders safely when secondary contains sada_override format without crashing', () => {
    const tripDiagnosis = {
      ...diagnosis,
      fault_type: 'indeterminate',
      secondary: [
        {
          sada_latched_fault: 'bearing_outer',
          sada_latched_severity: 0.88,
          reason: 'channels_starved_during_trip',
        } as unknown as { fault_type: string; confidence: number; severity: number; sources: string[] },
      ],
    }
    render(<DiagnosisPanel diagnosis={tripDiagnosis} mlBackend="rules" />)
    expect(screen.getByTestId('fused-fault')).toHaveTextContent('indeterminate')
    expect(screen.getByText(/Also considered: bearing outer/)).toBeInTheDocument()
  })
})

describe('SadaPanel', () => {
  it('renders derate state and load command', () => {
    render(<SadaPanel motorId={1} sup={supervisory} canOperate={false} />)
    expect(screen.getByTestId('sada-state')).toHaveTextContent('Derate')
    expect(screen.getByTestId('load-cmd')).toHaveTextContent('72%')
    expect(screen.queryByRole('button', { name: 'Acknowledge' })).not.toBeInTheDocument()
  })

  it('sends an idempotent acknowledge override for operators', async () => {
    const fetch = mockFetch({ id: 1 })
    render(<SadaPanel motorId={3} sup={supervisory} canOperate />)
    expect(screen.getByRole('button', { name: 'Reset trip' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Acknowledge' }))
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/v1/motors/3/supervisory/override')
    expect(JSON.parse(init.body as string)).toEqual({ action: 'ack' })
    const headers = new Headers(init.headers)
    expect(headers.get('Authorization')).toBe('Bearer tok')
    expect(headers.get('Idempotency-Key')).toBeTruthy()
  })
})

describe('FaultConsole', () => {
  it('injects an inter-turn short with phase parameter', async () => {
    const fetch = mockFetch({ id: 9 }, 201)
    render(<FaultConsole motorId={1} faults={[]} canOperate />)
    await userEvent.selectOptions(screen.getByLabelText('fault type'), 'interturn_short')
    await userEvent.selectOptions(screen.getByLabelText('phase'), 'c')
    await userEvent.click(screen.getByRole('button', { name: 'Inject fault' }))
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/v1/motors/1/faults')
    expect(JSON.parse(init.body as string)).toEqual({ fault_type: 'interturn_short', severity: 0.3, params: { phase: 'c' } })
    expect(await screen.findByRole('status')).toHaveTextContent('Injected interturn short')
  })

  it('shows API validation errors', async () => {
    mockFetch({ detail: 'rate limit exceeded' }, 429)
    render(<FaultConsole motorId={1} faults={[]} canOperate />)
    await userEvent.click(screen.getByRole('button', { name: 'Inject fault' }))
    expect(await screen.findByRole('status')).toHaveTextContent('rate limit exceeded')
  })

  it('lists active faults and hides controls from viewers', () => {
    render(<FaultConsole motorId={1} faults={[{ id: 4, fault_type: 'unbalance', severity: 0.4, params: {} }]} canOperate={false} />)
    expect(screen.getByText(/unbalance/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Inject fault' })).not.toBeInTheDocument()
    expect(screen.getByText(/Operator role required/)).toBeInTheDocument()
  })

  it('clears a fault', async () => {
    const fetch = mockFetch({ id: 4 })
    render(<FaultConsole motorId={2} faults={[{ id: 4, fault_type: 'unbalance', severity: 0.4, params: {} }]} canOperate />)
    await userEvent.click(screen.getByRole('button', { name: 'clear fault 4' }))
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/v1/motors/2/faults/4')
    expect(init.method).toBe('DELETE')
  })
})

describe('HistoryView', () => {
  it('renders indeterminate diagnosis with distinct label and styling', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    const mockData = {
      total: 1,
      limit: 25,
      offset: 0,
      items: [
        {
          id: 101,
          ts: '2026-09-27T12:00:00',
          fault_type: 'indeterminate',
          confidence: 0.95,
          severity_score: 0.0,
          per_sensor_scores_json: {
            sada_override: {
              sada_latched_fault: 'bearing_outer',
              sada_latched_severity: 0.9,
              reason: 'channels_starved_during_trip',
            },
          },
        },
      ],
    }

    const fn = vi.fn(async (url: string | URL | Request) => {
      const urlStr = String(url)
      if (urlStr.includes('/diagnoses')) {
        return new Response(JSON.stringify(mockData), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      return new Response(JSON.stringify([]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    })
    vi.stubGlobal('fetch', fn)

    render(
      <QueryClientProvider client={queryClient}>
        <HistoryView motorId={1} />
      </QueryClientProvider>,
    )

    const cell = await screen.findByText(/monitoring paused — motor stopped \(last known: bearing outer\)/)
    expect(cell).toBeInTheDocument()
    expect(cell).toHaveClass('text-amber-600')
    const row = cell.closest('tr')
    expect(row).toHaveClass('bg-amber-50')
  })
})

describe('HealthGauge', () => {
  it('renders correct health value and zone label', () => {
    render(<HealthGauge value={92} />)
    expect(screen.getByText('92')).toBeInTheDocument()
    expect(screen.getByText('Zone A')).toBeInTheDocument()
  })

  it('correctly maps values to ISO condition zones', () => {
    const { rerender } = render(<HealthGauge value={78} />)
    expect(screen.getByText('Zone B')).toBeInTheDocument()

    rerender(<HealthGauge value={58} />)
    expect(screen.getByText('Zone C')).toBeInTheDocument()

    rerender(<HealthGauge value={35} />)
    expect(screen.getByText('Zone D')).toBeInTheDocument()
  })
})

describe('TripBanner', () => {
  it('renders nothing when no motors are tripped', () => {
    const { container } = render(<TripBanner trippedMotors={[]} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders persistent trip alert with acknowledge button', async () => {
    const fetch = mockFetch({ id: 1 })
    const onAck = vi.fn()
    const tripped = [
      { id: 2, name: 'Conveyor 11kW', reason_code: 'SEV_CRITICAL', acknowledged: false },
    ]
    render(<TripBanner trippedMotors={tripped} onAcknowledged={onAck} />)

    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByText(/EMERGENCY TRIP ACTIVE/i)).toBeInTheDocument()
    expect(screen.getByText(/Conveyor 11kW \[SEV_CRITICAL\]/i)).toBeInTheDocument()

    const ackBtn = screen.getByRole('button', { name: /Acknowledge Conveyor 11kW/i })
    expect(ackBtn).toBeInTheDocument()

    await userEvent.click(ackBtn)
    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/motors/2/supervisory/override',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ action: 'ack' }),
      }),
    )
    expect(onAck).toHaveBeenCalledWith(2)
  })
})

describe('MotorCard', () => {
  it('renders motor info, health gauge, and status', () => {
    const motor = {
      id: 1,
      name: 'Main Feed Pump 1.5kW',
      rated_power: 1500,
      rated_speed: 157.08,
      rated_torque: 9.55,
      base_load_nm: 7.5,
    }
    const frame = {
      health_index: 94.5,
      error_code: 'SYS-OK-A',
      zone: 'A',
      supervisory: { state: 'NORMAL' as const },
    } as unknown as Frame

    render(<MotorCard motor={motor} frame={frame} />)
    expect(screen.getByText('Main Feed Pump 1.5kW')).toBeInTheDocument()
    expect(screen.getByText(/1.5 kW/)).toBeInTheDocument()
    expect(screen.getByText('SYS-OK-A')).toBeInTheDocument()
    expect(screen.getByText('Zone A')).toBeInTheDocument()
  })
})

describe('MotorParamsStudio', () => {
  it('pre-fills from currentMotor params_json and applies to backend', async () => {
    const fetchMock = mockFetch({ id: 1, name: 'Conveyor 5.5kW' }, 200)
    const onApply = vi.fn()
    const motor = {
      id: 1,
      name: 'Conveyor 5.5kW',
      rated_power: 5500,
      rated_speed: 1460,
      rated_torque: 36.0,
      base_load_nm: 25.0,
      params_json: {
        Rs: 0.82,
        Rr: 0.65,
        Ls: 0.095,
        Lr: 0.095,
        Lm: 0.091,
        J: 0.045,
        pole_pairs: 2,
        rated_power: 5500,
        rated_voltage: 400,
        rated_current: 11.2,
        rated_speed: 1460,
        rated_torque: 36.0,
        t_ambient: 25.0,
        warn_c: 85.0,
        trip_c: 110.0,
      },
    }

    render(<MotorParamsStudio currentMotor={motor} onApplyParams={onApply} />)

    expect(screen.getByText(/Active Motor Target: Conveyor 5.5kW/)).toBeInTheDocument()
    const applyBtn = screen.getByRole('button', { name: 'Apply to Motor Twin' })
    expect(applyBtn).toBeInTheDocument()
    expect(applyBtn).not.toBeDisabled()

    await userEvent.click(applyBtn)

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/motors/1/params',
      expect.objectContaining({
        method: 'PATCH',
      }),
    )
    expect(onApply).toHaveBeenCalled()
    expect(await screen.findByText(/Parameters applied to Conveyor 5.5kW/)).toBeInTheDocument()
  })
})

describe('AlertsModal', () => {
  it('renders alerts and allows operator to acknowledge', async () => {
    const alertsData = [
      {
        id: 42,
        motor_id: 1,
        ts: new Date().toISOString(),
        severity: 'warning',
        message: 'Sensor vibration switched to hardware mode',
        acknowledged: false,
      },
    ]
    const fetchMock = mockFetch(alertsData, 200)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    render(
      <QueryClientProvider client={queryClient}>
        <AlertsModal
          isOpen={true}
          onClose={() => {}}
          motorId={1}
          motorName="Conveyor 5.5kW"
          canOperate={true}
        />
      </QueryClientProvider>,
    )

    expect(await screen.findByText(/Sensor vibration switched to hardware mode/)).toBeInTheDocument()
    const ackBtn = screen.getByRole('button', { name: 'Acknowledge' })
    expect(ackBtn).toBeInTheDocument()

    await userEvent.click(ackBtn)

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/motors/1/alerts/42/ack',
      expect.objectContaining({
        method: 'POST',
      }),
    )
  })
})

