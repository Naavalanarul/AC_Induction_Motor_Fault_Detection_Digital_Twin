import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { saveSession } from '../api/client'
import { diagnosis, supervisory } from '../test/fixtures'
import { DiagnosisPanel } from './DiagnosisPanel'
import { FaultConsole } from './FaultConsole'
import { SadaPanel } from './SadaPanel'
import { StatusBadge } from './StatusBadge'

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
    expect(JSON.parse(init.body as string)).toEqual({ fault_type: 'interturn_short', severity: 0.5, params: { phase: 'c' } })
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
