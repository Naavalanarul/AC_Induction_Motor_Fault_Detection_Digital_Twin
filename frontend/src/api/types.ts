// Mirrors the backend payloads (diagnosis schema_version 1.0).

export type Role = 'viewer' | 'operator' | 'admin'

export type ChannelVerdict = {
  source: string
  fault_type: string
  confidence: number
  severity: number
  available: boolean
  details: Record<string, unknown>
}

export type Diagnosis = {
  t: number
  fault_type: string
  confidence: number
  severity: number
  per_sensor_scores: Record<string, ChannelVerdict>
  secondary: { fault_type: string; confidence: number; severity: number; sources: string[] }[]
  source: string
  schema_version: string
}

export type SadaStateName = 'NORMAL' | 'WATCH' | 'DERATE' | 'TRIP'

export type Supervisory = {
  state: SadaStateName
  load_cmd: number
  reason_code: string
  trip: boolean
  smoothed_severity: number
  fault_type: string
  manual_override: boolean
  base_load_nm: number
  acknowledged: boolean
}

export type SensorEntry = {
  status: 'ok' | 'stale' | 'fault'
  mode: 'simulated' | 'hardware'
  unit: string
  wave?: Record<string, number[]>
  rms?: Record<string, number>
  value?: number
}

export type Spectrum = { f: number[]; db: number[] }

export type ActiveFault = { id: number; fault_type: string; severity: number; params: Record<string, unknown> }

export type Frame = {
  type: 'frame'
  motor_id: number
  name: string
  t: number
  sensors: Record<string, SensorEntry>
  spectra: Partial<Record<'current_a' | 'vibration_y' | 'acoustic', Spectrum>>
  scalogram: { freqs: number[]; values: number[][]; dt: number } | null
  residual: { a: number[] } | null
  mechanics: { torque_nm: number; load_nm: number; rpm: number }
  diagnosis: Diagnosis
  supervisory: Supervisory
  faults: ActiveFault[]
  ml_backend: string
}

export type Motor = {
  id: number
  name: string
  rated_power: number
  rated_speed: number
  rated_torque: number
  base_load_nm: number
}

export type SensorRow = { id: number; motor_id: number; type: string; mode: 'simulated' | 'hardware' }

export type HistoryEvent = {
  ts: string
  kind: 'fault_injected' | 'fault_cleared' | 'supervisory'
  data: Record<string, unknown>
}

export type DiagnosisRow = {
  id: number
  ts: string
  fault_type: string
  confidence: number
  severity_score: number
}

export type Page<T> = { total: number; limit: number; offset: number; items: T[] }

export const FAULT_TYPES = [
  'broken_rotor_bar',
  'interturn_short',
  'eccentricity',
  'bearing_inner',
  'bearing_outer',
  'bearing_ball',
  'unbalance',
  'misalignment',
  'voltage_anomaly',
] as const
export type FaultType = (typeof FAULT_TYPES)[number]

export const label = (s: string) => s.replaceAll('_', ' ')
