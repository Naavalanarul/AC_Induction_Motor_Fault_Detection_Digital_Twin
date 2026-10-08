import { label, type DiagnosisRow } from '../api/types'

/**
 * Time-to-threshold label. `null` from the API means "no crossing projected", which is different
 * from "already past the threshold" and from "no data" -- render each explicitly so a failed or
 * empty prognosis never looks like a healthy motor.
 */
export const formatTimeToThreshold = (
  sec: number | null | undefined,
  current: number | null | undefined,
  threshold: number,
  tripped: boolean,
): string => {
  if (tripped) return 'Tripped'
  if (current === null || current === undefined) return '—'
  if (current >= threshold) return 'Exceeded'
  if (sec === null || sec === undefined) return 'Not projected'
  return formatSeconds(sec)
}

const formatSeconds = (sec: number): string => {
  if (sec <= 0) return 'Exceeded'
  if (sec < 60) return `${sec.toFixed(0)} s`
  const mins = Math.floor(sec / 60)
  const remSec = Math.round(sec % 60)
  return `${mins}m ${remSec}s`
}

/** Post-trip rows are stored as `indeterminate` with the latched fault in `sada_override`. */
export function historyFaultLabel(row: DiagnosisRow): string {
  if (row.fault_type === 'indeterminate') {
    const o = row.per_sensor_scores_json?.['sada_override'] as Record<string, unknown> | undefined
    const latched = o?.['sada_latched_fault']
    if (typeof latched === 'string') return `indeterminate (tripped on ${label(latched)})`
  }
  return label(row.fault_type)
}
