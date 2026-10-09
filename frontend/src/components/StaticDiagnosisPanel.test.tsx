import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { StaticDiagnosisPanel } from './StaticDiagnosisPanel'
import * as client from '../api/client'
import type { StaticAnalysisRecord, StaticDiagnosisOut } from '../api/types'

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client')
  return {
    ...actual,
    diagnoseStatic: vi.fn(),
    listStaticAnalyses: vi.fn(),
    getStaticAnalysis: vi.fn(),
    newIdempotencyKey: () => 'test-uuid-1234',
  }
})

const mockDiagnosisOut: StaticDiagnosisOut = {
  t: 1728460000.0,
  fault_type: 'interturn_short',
  confidence: 0.85,
  severity: 0.42,
  schema_version: '1.0',
  source: 'fused',
  health_index: 74.8,
  zone: 'B',
  error_code: 'ELEC-ITS-B',
  per_sensor_scores: {
    supply: {
      source: 'supply',
      fault_type: 'healthy',
      confidence: 0.95,
      severity: 0.0,
      available: true,
      details: { vuf_pct: 0.0 },
    },
    protection: {
      source: 'protection',
      fault_type: 'healthy',
      confidence: 0.9,
      severity: 0.0,
      available: true,
      details: { i_max_pu: 0.99 },
    },
    electrical_residual: {
      source: 'electrical_residual',
      fault_type: 'interturn_short',
      confidence: 0.85,
      severity: 0.42,
      available: true,
      details: { current_imbalance_pct: 7.2 },
    },
    thermal: {
      source: 'thermal',
      fault_type: 'healthy',
      confidence: 0.0,
      severity: 0.0,
      available: false,
      details: {},
    },
    mechanical_vibration: {
      source: 'mechanical_vibration',
      fault_type: 'healthy',
      confidence: 0.0,
      severity: 0.0,
      available: false,
      details: {},
    },
    spectral_mcsa: {
      source: 'spectral_mcsa',
      fault_type: 'healthy',
      confidence: 0.0,
      severity: 0.0,
      available: false,
      details: {},
    },
  },
  secondary: [],
  channels_run: ['supply', 'protection', 'electrical_residual'],
  channels_skipped: {
    thermal: 'Requires measured winding temperature',
    mechanical_vibration: 'Requires vibration RMS or defect peak',
    spectral_mcsa: 'Requires MCSA spectral sidebands or voltage THD',
  },
  derived: {
    slip: 0.0138,
    expected_current_a: 4.69,
    current_imbalance_pct: 7.2,
    voltage_unbalance_pct: 0.0,
    loading_pu: 0.85,
    stator_current_residual_a: 0.35,
    real_power_w: 2450.0,
    power_factor: 0.82,
  },
  recommendation: {
    urgency: 'prompt',
    action: 'Schedule motor inspection for stator inter-turn insulation degradation.',
    reason: 'Negative sequence current asymmetry detected with balanced voltage supply.',
    checklists: [
      'Perform surge comparison test on stator windings',
      'Measure phase-to-phase insulation resistance with megohmmeter',
    ],
  },
  warnings: [],
  advisory_notice: 'Advisory only, no control action taken.',
}

const mockHistoryItem = {
  id: 42,
  user: 'operator1',
  ts: '2026-10-09T08:00:00Z',
  motor_id: null,
  fault_type: 'interturn_short',
  severity: 0.42,
  mhi: 74.8,
  error_code: 'ELEC-ITS-B',
  zone: 'B',
}

const mockFullRecord: StaticAnalysisRecord = {
  ...mockHistoryItem,
  inputs: {
    v_a: 380,
    v_b: 380,
    v_c: 380,
    voltage_basis: 'line_line',
    value_basis: 'rms',
    i_a: 4.64,
    i_b: 4.63,
    i_c: 4.32,
    speed_rpm: 1479.2,
    supply_freq_hz: 50.0,
  },
  result: mockDiagnosisOut,
}

describe('StaticDiagnosisPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(client.listStaticAnalyses).mockResolvedValue({
      total: 1,
      limit: 20,
      offset: 0,
      items: [mockHistoryItem],
    })
    vi.mocked(client.diagnoseStatic).mockResolvedValue(mockDiagnosisOut)
    vi.mocked(client.getStaticAnalysis).mockResolvedValue(mockFullRecord)
  })

  it('renders title, advisory banner, and initial default inputs', async () => {
    render(<StaticDiagnosisPanel />)

    expect(screen.getByText('Static-Value Motor Diagnosis')).toBeInTheDocument()
    expect(screen.getByText(/Advisory Mode Notice:/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Run Static Diagnosis/i })).toBeInTheDocument()

    // Default inputs
    const speedInput = screen.getByLabelText('Shaft Speed')
    expect(speedInput).toHaveValue(1474)

    // History item rendered
    await waitFor(() => {
      expect(screen.getByText('#42')).toBeInTheDocument()
    })
  })

  it('validates speed strictly below synchronous speed before executing', async () => {
    const user = userEvent.setup()
    render(<StaticDiagnosisPanel />)

    const speedInput = screen.getByLabelText('Shaft Speed')
    await user.clear(speedInput)
    // 50 Hz, 2 pole pairs -> nSync = 1500 RPM. Entering 1500 or higher must fail.
    await user.type(speedInput, '1500')

    const runBtn = screen.getByRole('button', { name: /Run Static Diagnosis/i })
    await user.click(runBtn)

    expect(
      screen.getByText(/Measured speed \(1500.0 RPM\) must be strictly below synchronous speed/i)
    ).toBeInTheDocument()
    expect(client.diagnoseStatic).not.toHaveBeenCalled()
  })

  it('validates negative or invalid voltages', async () => {
    const user = userEvent.setup()
    render(<StaticDiagnosisPanel />)

    const vaInput = screen.getByLabelText('Phase A Voltage')
    await user.clear(vaInput)
    await user.type(vaInput, '-10')

    const runBtn = screen.getByRole('button', { name: /Run Static Diagnosis/i })
    await user.click(runBtn)

    expect(screen.getByText(/Please provide valid positive 3-phase voltages/i)).toBeInTheDocument()
    expect(client.diagnoseStatic).not.toHaveBeenCalled()
  })

  it('populates form fields when example preset is selected', async () => {
    const user = userEvent.setup()
    render(<StaticDiagnosisPanel />)

    const presetSelect = screen.getByLabelText('Example Preset')
    await user.selectOptions(presetSelect, 'interturn_short')

    expect(screen.getByLabelText('Phase A Current')).toHaveValue(4.64)
    expect(screen.getByLabelText('Phase B Current')).toHaveValue(4.63)
    expect(screen.getByLabelText('Phase C Current')).toHaveValue(4.32)
    expect(screen.getByLabelText('Shaft Speed')).toHaveValue(1479.2)
  })

  it('executes static diagnosis and renders results, gauge, error code, and channels', async () => {
    const user = userEvent.setup()
    render(<StaticDiagnosisPanel />)

    const runBtn = screen.getByRole('button', { name: /Run Static Diagnosis/i })
    await user.click(runBtn)

    await waitFor(() => {
      expect(client.diagnoseStatic).toHaveBeenCalledTimes(1)
    })

    // Gauge and Fused Verdict
    const resultsContainer = screen.getByTestId('static-results-container')
    expect(resultsContainer).toBeInTheDocument()
    expect(within(resultsContainer).getByText('ELEC-ITS-B')).toBeInTheDocument()
    expect(screen.getByTestId('static-fused-fault')).toHaveTextContent('interturn short')

    // Prescriptive recommendation
    expect(screen.getByText(/Schedule motor inspection for stator inter-turn insulation degradation/i)).toBeInTheDocument()
    expect(screen.getByText(/prompt urgency/i)).toBeInTheDocument()
    expect(screen.getByText(/Perform surge comparison test on stator windings/i)).toBeInTheDocument()

    // Derived engineering metrics
    expect(screen.getByText('7.2%')).toBeInTheDocument() // current imbalance
    expect(screen.getByText('0.85 pu')).toBeInTheDocument() // loading pu

    // Channel table
    expect(screen.getAllByText('Assessed').length).toBe(3)
    expect(screen.getAllByText('Not Assessable').length).toBe(3)
    expect(screen.getAllByText(/Requires measured winding temperature/i).length).toBeGreaterThanOrEqual(1)
  })

  it('loads historical record into form and results upon clicking Load Record', async () => {
    const user = userEvent.setup()
    render(<StaticDiagnosisPanel />)

    await waitFor(() => {
      expect(screen.getByText('#42')).toBeInTheDocument()
    })

    const loadBtn = screen.getByRole('button', { name: /Load Record/i })
    await user.click(loadBtn)

    await waitFor(() => {
      expect(client.getStaticAnalysis).toHaveBeenCalledWith(42)
    })

    expect(screen.getByTestId('static-fused-fault')).toHaveTextContent('interturn short')
    expect(screen.getByLabelText('Phase A Current')).toHaveValue(4.64)
  })

  it('supports navigation back to fleet dashboard', async () => {
    const onBack = vi.fn()
    const user = userEvent.setup()
    render(<StaticDiagnosisPanel onBackToFleet={onBack} />)

    const backBtn = screen.getByRole('button', { name: /Fleet Dashboard/i })
    await user.click(backBtn)
    expect(onBack).toHaveBeenCalledTimes(1)
  })
})
