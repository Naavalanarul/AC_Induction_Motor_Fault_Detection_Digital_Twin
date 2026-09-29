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
  health_index?: number
  error_code?: string
  zone?: string
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

export type ThermalLPTNState = {
  t_winding: number
  t_teeth: number
  t_rotor: number
  t_bearing: number
  ambient: number
  aging_acceleration: number
  rul_hours: number
  bearing_rul_hours?: number
  overall_rul_hours?: number
  limiting_factor?: 'insulation' | 'bearing_de' | 'bearing_nde' | string
  bearing_health_percent?: number
  iso_zone?: string
}

export interface SubsystemRUL {
  winding_temp_c?: number
  hotspot_temp_c?: number
  bearing_temp_c?: number
  aging_acceleration_factor?: number
  l10h_hours?: number
  adjusted_l10h_hours?: number
  nominal_life_hours?: number
  rul_hours: number
  rul_years: number
  health_percent: number
  temp_margin_c?: number
  vibration_rms_mms?: number
  iso_zone?: string
}

export interface RULResultOut {
  motor_id: number
  overall_rul_hours: number
  overall_rul_years: number
  overall_health_percent: number
  limiting_factor: 'insulation' | 'bearing_de' | 'bearing_nde' | string
  insulation: SubsystemRUL
  bearing_de: SubsystemRUL
  bearing_nde: SubsystemRUL
}

export type Frame = {
  type: 'frame'
  motor_id: number
  name: string
  t: number
  health_index?: number
  error_code?: string
  zone?: string
  sensors: Record<string, SensorEntry>
  spectra: Partial<Record<'current_a' | 'vibration_y' | 'acoustic' | 'mcsa', Spectrum | any>>
  scalogram: { freqs: number[]; values: number[][]; dt: number } | null
  residual: { a: number[] } | null
  mechanics: { torque_nm: number; load_nm: number; rpm: number }
  thermal_lptn?: ThermalLPTNState | null
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
  per_sensor_scores_json?: Record<string, unknown>
  health_index?: number
  error_code?: string
}

export type ConditionZone = 'A' | 'B' | 'C' | 'D'

export type Prognosis = {
  current_severity: number
  slope_per_s: number
  time_to_derate_s: number | null
  time_to_trip_s: number | null
  trend: 'increasing' | 'decreasing' | 'stable'
  sample_count: number
}

export type Recommendation = {
  motor_id: number
  fault_type: string
  zone: ConditionZone
  mhi: number
  urgency: 'routine' | 'planned' | 'prompt' | 'immediate'
  title: string
  action: string
  checklist: string[]
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

export const label = (s?: string | null): string => {
  if (!s) return ''
  return String(s).replaceAll('_', ' ')
}

export const getZoneFromMHI = (val: number): ConditionZone => {
  if (val >= 85) return 'A'
  if (val >= 70) return 'B'
  if (val >= 50) return 'C'
  return 'D'
}

export interface DatabaseStatus {
  connected: boolean
  engine: string
  dialect: string
  database: string
  user: string
  host: string
  port: number | null
  latency_ms: number | null
  tables: string[]
  pool?: {
    size: number
    checked_out: number
  } | null
  error: string | null
}

export interface DbTestResult {
  success: boolean
  message: string
  latency_ms: number | null
  applied: boolean
}

export type MCSAPeak = {
  freq_hz: number
  magnitude_db: number
  label: string
  harmonic_k?: number | null
  expected_freq_hz?: number | null
  deviation_hz?: number | null
}

export type MCSAResult = {
  status: string
  fundamental_freq: number
  fundamental_mag_db: number
  slip: number
  rotor_freq_hz: number
  brb_fault_detected: boolean
  eccentricity_detected: boolean
  worst_brb_sideband_db?: number | null
  peaks: MCSAPeak[]
  brb_peaks: MCSAPeak[]
  ecc_peaks: MCSAPeak[]
  freqs: number[]
  psd_db: number[]
}

export type TransientSimulationResult = {
  motor_id: number
  duration_s: number
  steady_state_rpm: number
  steady_state_torque: number
  slip: number
  t: number[]
  rpm: number[]
  te: number[]
  load_torque: number[]
  ia: number[]
  ib: number[]
  ic: number[]
  id: number[]
  iq: number[]
  psi_rd: number[]
  psi_rq: number[]
  copper_loss_w: number[]
  fault_heat_w: number[]
}


