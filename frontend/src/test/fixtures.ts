import type { Diagnosis, Supervisory } from '../api/types'

export const diagnosis: Diagnosis = {
  t: 12.3,
  fault_type: 'bearing_outer',
  confidence: 0.93,
  severity: 0.61,
  per_sensor_scores: {
    electrical_residual: { source: 'electrical_residual', fault_type: 'healthy', confidence: 0.8, severity: 0, available: true, details: {} },
    ml_classifier: { source: 'ml_classifier', fault_type: 'bearing_outer', confidence: 0.93, severity: 0.61, available: true, details: {} },
    thermal: { source: 'thermal', fault_type: 'unknown', confidence: 0, severity: 0, available: false, details: {} },
  },
  secondary: [{ fault_type: 'unbalance', confidence: 0.3, severity: 0.2, sources: ['ml_classifier'] }],
  source: 'fused',
  schema_version: '1.0',
}

export const supervisory: Supervisory = {
  state: 'DERATE',
  load_cmd: 0.72,
  reason_code: 'DERATE_BEARING_OUTER',
  trip: false,
  smoothed_severity: 0.64,
  fault_type: 'bearing_outer',
  manual_override: false,
  base_load_nm: 8,
  acknowledged: false,
}
