import { useCallback, useEffect, useState } from 'react'
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  Clock,
  Compass,
  Cpu,
  Info,
  RefreshCw,
  RotateCcw,
  Sliders,
  Sparkles,
  Zap,
} from 'lucide-react'
import {
  diagnoseStatic,
  formatDetail,
  getStaticAnalysis,
  listStaticAnalyses,
  newIdempotencyKey,
} from '../api/client'
import type {
  Motor,
  NameplateBlock,
  Role,
  SpectralAmplitudes,
  StaticAnalysisItem,
  StaticDiagnosisOut,
  StaticMeasurement,
  ValueBasis,
  VibrationAmplitudes,
  VoltageBasis,
} from '../api/types'
import { label } from '../api/types'
import { HealthGauge } from './HealthGauge'
import { DEFAULT_STATIC_NAMEPLATE, STATIC_FIXTURES } from '../test/staticFixtures'

export interface StaticDiagnosisPanelProps {
  onBackToFleet?: () => void
  motors?: Motor[]
  role?: Role
}

export function StaticDiagnosisPanel({ onBackToFleet, motors = [], role }: StaticDiagnosisPanelProps) {

  // Input Mode
  const [motorMode, setMotorMode] = useState<'nameplate' | 'existing'>('nameplate')
  const [selectedMotorId, setSelectedMotorId] = useState<number | ''>(motors[0]?.id ?? '')

  // Nameplate specifications
  const [nameplate, setNameplate] = useState<NameplateBlock>({ ...DEFAULT_STATIC_NAMEPLATE })
  const [showAdvancedEq, setShowAdvancedEq] = useState(false)

  // Electrical inputs
  const [voltageBasis, setVoltageBasis] = useState<VoltageBasis>('line_line')
  const [valueBasis, setValueBasis] = useState<ValueBasis>('rms')
  const [va, setVa] = useState<string>('380.0')
  const [vb, setVb] = useState<string>('380.0')
  const [vc, setVc] = useState<string>('380.0')
  const [ia, setIa] = useState<string>('4.69')
  const [ib, setIb] = useState<string>('4.69')
  const [ic, setIc] = useState<string>('4.69')
  const [speedRpm, setSpeedRpm] = useState<string>('1474.0')
  const [supplyFreqHz, setSupplyFreqHz] = useState<string>('50.0')

  // Optional thermal
  const [windingTemp, setWindingTemp] = useState<string>('')
  const [ambientTemp, setAmbientTemp] = useState<string>('25.0')

  // Optional vibration
  const [vibOverallRms, setVibOverallRms] = useState<string>('')
  const [vib1x, setVib1x] = useState<string>('')
  const [vib2x, setVib2x] = useState<string>('')
  const [vibBearingDefect, setVibBearingDefect] = useState<string>('')

  // Optional spectral
  const [brbSidebandDb, setBrbSidebandDb] = useState<string>('')
  const [eccentricityDb, setEccentricityDb] = useState<string>('')
  const [vThdPct, setVThdPct] = useState<string>('')

  // UI state
  const [activePreset, setActivePreset] = useState<string>('healthy')
  const [diagnosing, setDiagnosing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<StaticDiagnosisOut | null>(null)

  // History state
  const [history, setHistory] = useState<StaticAnalysisItem[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)

  // Load past analyses on mount
  const fetchHistory = useCallback(async () => {
    try {
      setHistoryLoading(true)
      const res = await listStaticAnalyses(undefined, 20, 0)
      setHistory(res.items || [])
    } catch {
      // Ignore if viewer lacks token or endpoint not reachable
    } finally {
      setHistoryLoading(false)
    }
  }, [])

  useEffect(() => {
    let ignore = false
    listStaticAnalyses(undefined, 20, 0)
      .then((res) => {
        if (!ignore) {
          setHistory(res.items || [])
        }
      })
      .catch(() => {
        // Ignore initial fetch errors if unauthenticated
      })
    return () => {
      ignore = true
    }
  }, [])

  // Fill preset from staticFixtures
  const handleSelectPreset = (presetId: string) => {
    setActivePreset(presetId)
    const preset = STATIC_FIXTURES.find((f) => f.id === presetId)
    if (!preset) return

    setMotorMode('nameplate')
    if (preset.measurement.nameplate) {
      setNameplate({ ...preset.measurement.nameplate })
    }
    setVoltageBasis(preset.measurement.voltage_basis)
    setValueBasis(preset.measurement.value_basis)
    setVa(String(preset.measurement.v_a))
    setVb(String(preset.measurement.v_b))
    setVc(String(preset.measurement.v_c))
    setIa(String(preset.measurement.i_a))
    setIb(String(preset.measurement.i_b))
    setIc(String(preset.measurement.i_c))
    setSpeedRpm(String(preset.measurement.speed_rpm))
    setSupplyFreqHz(String(preset.measurement.supply_freq_hz))

    setWindingTemp(preset.measurement.winding_temp_c != null ? String(preset.measurement.winding_temp_c) : '')
    setAmbientTemp(preset.measurement.ambient_temp_c != null ? String(preset.measurement.ambient_temp_c) : '25.0')

    setVibOverallRms(preset.measurement.vibration?.overall_rms_mm_s != null ? String(preset.measurement.vibration.overall_rms_mm_s) : '')
    setVib1x(preset.measurement.vibration?.peak_1x_mm_s != null ? String(preset.measurement.vibration.peak_1x_mm_s) : '')
    setVib2x(preset.measurement.vibration?.peak_2x_mm_s != null ? String(preset.measurement.vibration.peak_2x_mm_s) : '')
    setVibBearingDefect(preset.measurement.vibration?.bearing_defect_mm_s != null ? String(preset.measurement.vibration.bearing_defect_mm_s) : '')

    setBrbSidebandDb(preset.measurement.spectral?.brb_sideband_db != null ? String(preset.measurement.spectral.brb_sideband_db) : '')
    setEccentricityDb(preset.measurement.spectral?.eccentricity_sideband_db != null ? String(preset.measurement.spectral.eccentricity_sideband_db) : '')
    setVThdPct(preset.measurement.v_thd_pct != null ? String(preset.measurement.v_thd_pct) : '')

    setError(null)
  }

  // Synchronous speed calculation for display
  const selectedMotor = motors.find((m) => m.id === selectedMotorId)
  const polePairs =
    motorMode === 'nameplate'
      ? nameplate.pole_pairs
      : ((selectedMotor?.params_json?.pole_pairs as number | undefined) ?? 2)
  const freqVal = parseFloat(supplyFreqHz) || 50.0
  const nSync = polePairs > 0 ? (60.0 * freqVal) / polePairs : 1500.0

  const handleRunDiagnosis = async () => {
    setError(null)
    const vA = parseFloat(va)
    const vB = parseFloat(vb)
    const vC = parseFloat(vc)
    const iA = parseFloat(ia)
    const iB = parseFloat(ib)
    const iC = parseFloat(ic)
    const speed = parseFloat(speedRpm)
    const freq = parseFloat(supplyFreqHz)

    if (isNaN(vA) || isNaN(vB) || isNaN(vC) || vA <= 0 || vB <= 0 || vC <= 0) {
      setError('Please provide valid positive 3-phase voltages.')
      return
    }
    if (isNaN(iA) || isNaN(iB) || isNaN(iC) || iA <= 0 || iB <= 0 || iC <= 0) {
      setError('Please provide valid positive 3-phase currents.')
      return
    }
    if (isNaN(speed) || speed <= 0) {
      setError('Please provide a valid shaft speed in RPM.')
      return
    }
    if (speed >= nSync) {
      setError(`Measured speed (${speed.toFixed(1)} RPM) must be strictly below synchronous speed (${nSync.toFixed(1)} RPM) for motoring.`)
      return
    }

    let vibObj: VibrationAmplitudes | null = null
    const vRms = vibOverallRms ? parseFloat(vibOverallRms) : null
    const v1x = vib1x ? parseFloat(vib1x) : null
    const v2x = vib2x ? parseFloat(vib2x) : null
    const vBrg = vibBearingDefect ? parseFloat(vibBearingDefect) : null
    if (vRms !== null || v1x !== null || v2x !== null || vBrg !== null) {
      vibObj = {
        overall_rms_mm_s: vRms,
        peak_1x_mm_s: v1x,
        peak_2x_mm_s: v2x,
        bearing_defect_mm_s: vBrg,
      }
    }

    let specObj: SpectralAmplitudes | null = null
    const brb = brbSidebandDb ? parseFloat(brbSidebandDb) : null
    const ecc = eccentricityDb ? parseFloat(eccentricityDb) : null
    if (brb !== null || ecc !== null) {
      specObj = {
        brb_sideband_db: brb,
        eccentricity_sideband_db: ecc,
      }
    }

    const payload: StaticMeasurement = {
      motor_id: motorMode === 'existing' && selectedMotorId !== '' ? Number(selectedMotorId) : null,
      nameplate: motorMode === 'nameplate' ? nameplate : null,
      v_a: vA,
      v_b: vB,
      v_c: vC,
      voltage_basis: voltageBasis,
      value_basis: valueBasis,
      i_a: iA,
      i_b: iB,
      i_c: iC,
      speed_rpm: speed,
      supply_freq_hz: freq,
      winding_temp_c: windingTemp ? parseFloat(windingTemp) : null,
      ambient_temp_c: ambientTemp ? parseFloat(ambientTemp) : 25.0,
      vibration: vibObj,
      spectral: specObj,
      v_thd_pct: vThdPct ? parseFloat(vThdPct) : null,
    }

    try {
      setDiagnosing(true)
      const res = await diagnoseStatic(payload, newIdempotencyKey())
      setResult(res)
      fetchHistory()
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message)
      } else {
        setError(formatDetail(err))
      }
    } finally {
      setDiagnosing(false)
    }
  }

  const handleLoadHistoryRecord = async (recordId: number) => {
    try {
      setHistoryLoading(true)
      const rec = await getStaticAnalysis(recordId)
      if (rec.result) {
        setResult(rec.result)
      }
      if (rec.inputs) {
        const inp = rec.inputs
        if (inp.motor_id) {
          setMotorMode('existing')
          setSelectedMotorId(inp.motor_id)
        } else if (inp.nameplate) {
          setMotorMode('nameplate')
          setNameplate(inp.nameplate)
        }
        setVoltageBasis(inp.voltage_basis)
        setValueBasis(inp.value_basis)
        setVa(String(inp.v_a))
        setVb(String(inp.v_b))
        setVc(String(inp.v_c))
        setIa(String(inp.i_a))
        setIb(String(inp.i_b))
        setIc(String(inp.i_c))
        setSpeedRpm(String(inp.speed_rpm))
        setSupplyFreqHz(String(inp.supply_freq_hz))
        setWindingTemp(inp.winding_temp_c != null ? String(inp.winding_temp_c) : '')
        setAmbientTemp(inp.ambient_temp_c != null ? String(inp.ambient_temp_c) : '25.0')
        setVibOverallRms(inp.vibration?.overall_rms_mm_s != null ? String(inp.vibration.overall_rms_mm_s) : '')
        setVib1x(inp.vibration?.peak_1x_mm_s != null ? String(inp.vibration.peak_1x_mm_s) : '')
        setVib2x(inp.vibration?.peak_2x_mm_s != null ? String(inp.vibration.peak_2x_mm_s) : '')
        setVibBearingDefect(inp.vibration?.bearing_defect_mm_s != null ? String(inp.vibration.bearing_defect_mm_s) : '')
        setBrbSidebandDb(inp.spectral?.brb_sideband_db != null ? String(inp.spectral.brb_sideband_db) : '')
        setEccentricityDb(inp.spectral?.eccentricity_sideband_db != null ? String(inp.spectral.eccentricity_sideband_db) : '')
        setVThdPct(inp.v_thd_pct != null ? String(inp.v_thd_pct) : '')
      }
    } catch (err: unknown) {
      if (err instanceof Error) setError(err.message)
    } finally {
      setHistoryLoading(false)
    }
  }

  return (
    <div className="static-panel-wrap" data-testid="static-diagnosis-panel">
      {/* Top Header */}
      <div className="glass-card" style={{ padding: '24px 32px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '16px' }}>
          <div>
            <span className="eyebrow">OFFLINE STEADY-STATE EVALUATION</span>
            <h1 className="fleet-title" style={{ fontSize: '1.4rem', margin: '4px 0' }}>
              Static-Value Motor Diagnosis
            </h1>
            <p className="page-subtitle" style={{ margin: 0 }}>
              Diagnose electrical, thermal, mechanical, and protection anomalies from nameplate parameters and measured scalar inputs without live simulation.
            </p>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            {/* Fill Preset Dropdown */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Sparkles size={16} className="text-amber-400" />
              <label htmlFor="static-preset-select" className="text-xs text-[var(--muted)] font-medium">Example:</label>
              <select
                id="static-preset-select"
                aria-label="Example Preset"
                className="input"
                style={{ width: '220px', padding: '6px 10px', fontSize: '0.8rem' }}
                value={activePreset}
                onChange={(e) => handleSelectPreset(e.target.value)}
              >
                {STATIC_FIXTURES.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.label}
                  </option>
                ))}
              </select>
            </div>

            {onBackToFleet && (
              <button className="btn" onClick={onBackToFleet} title="Return to fleet view">
                ← Fleet Dashboard
              </button>
            )}
          </div>
        </div>

        {/* Advisory Notice Banner */}
        <div className="static-advisory-banner" style={{ marginTop: '20px' }}>
          <Info size={18} style={{ color: 'var(--accent)', flexShrink: 0 }} />
          <div>
            <strong style={{ color: 'var(--accent)' }}>Advisory Mode Notice:</strong> Single-snapshot manual diagnosis is strictly advisory. Because manual readings lack dynamic time-series history, static verdicts cannot trigger physical SADA protection trips, relay derates, or motor control actions.
          </div>
        </div>
      </div>

      {/* Main Diagnosis Form Grid */}
      <div className="static-section-card">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Cpu size={18} className="text-[var(--accent)]" />
            <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--ink)]" style={{ margin: 0 }}>
              1. Motor Specification Reference
            </h2>
            {role === 'viewer' && (
              <span className="text-[10px] uppercase font-semibold px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20">
                Viewer (Read Only)
              </span>
            )}
          </div>

          {/* Mode Switcher */}
          <div style={{ display: 'inline-flex', background: 'var(--surface-raised)', padding: '3px', borderRadius: '8px', border: '1px solid var(--border)' }}>
            <button
              type="button"
              className={`login-mode-btn ${motorMode === 'nameplate' ? 'is-active' : ''}`}
              style={{ padding: '4px 12px', fontSize: '0.75rem' }}
              onClick={() => setMotorMode('nameplate')}
            >
              Custom Nameplate
            </button>
            <button
              type="button"
              className={`login-mode-btn ${motorMode === 'existing' ? 'is-active' : ''}`}
              style={{ padding: '4px 12px', fontSize: '0.75rem' }}
              onClick={() => setMotorMode('existing')}
              disabled={motors.length === 0}
            >
              Registered Fleet Motor ({motors.length})
            </button>
          </div>
        </div>

        {motorMode === 'existing' ? (
          <div style={{ padding: '8px 0 16px 0' }}>
            <label className="static-field-label">Select Target Motor</label>
            <select
              aria-label="Select Target Motor"
              className="input"
              value={selectedMotorId}
              onChange={(e) => setSelectedMotorId(e.target.value ? Number(e.target.value) : '')}
            >
              {motors.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name} (#{m.id}) — {m.rated_power}W, {m.rated_speed} RPM
                </option>
              ))}
            </select>
          </div>
        ) : (
          <div>
            <div className="static-grid-4">
              <div className="static-field-group">
                <label className="static-field-label">
                  <span>Rated Power</span>
                  <span className="static-field-unit">Watts [W]</span>
                </label>
                <input
                  type="number"
                  aria-label="Rated Power"
                  className="input"
                  value={nameplate.rated_power_w}
                  onChange={(e) => setNameplate({ ...nameplate, rated_power_w: parseFloat(e.target.value) || 0 })}
                />
              </div>

              <div className="static-field-group">
                <label className="static-field-label">
                  <span>Rated Voltage</span>
                  <span className="static-field-unit">V L-L [V]</span>
                </label>
                <input
                  type="number"
                  aria-label="Rated Voltage"
                  className="input"
                  value={nameplate.rated_voltage_v}
                  onChange={(e) => setNameplate({ ...nameplate, rated_voltage_v: parseFloat(e.target.value) || 0 })}
                />
              </div>

              <div className="static-field-group">
                <label className="static-field-label">
                  <span>Rated Current</span>
                  <span className="static-field-unit">Amperes [A]</span>
                </label>
                <input
                  type="number"
                  step="0.1"
                  aria-label="Rated Current"
                  className="input"
                  value={nameplate.rated_current_a}
                  onChange={(e) => setNameplate({ ...nameplate, rated_current_a: parseFloat(e.target.value) || 0 })}
                />
              </div>

              <div className="static-field-group">
                <label className="static-field-label">
                  <span>Rated Speed</span>
                  <span className="static-field-unit">RPM</span>
                </label>
                <input
                  type="number"
                  aria-label="Rated Speed"
                  className="input"
                  value={nameplate.rated_speed_rpm}
                  onChange={(e) => setNameplate({ ...nameplate, rated_speed_rpm: parseFloat(e.target.value) || 0 })}
                />
              </div>

              <div className="static-field-group">
                <label className="static-field-label">
                  <span>Rated Torque</span>
                  <span className="static-field-unit">Nm</span>
                </label>
                <input
                  type="number"
                  step="0.5"
                  aria-label="Rated Torque"
                  className="input"
                  value={nameplate.rated_torque_nm}
                  onChange={(e) => setNameplate({ ...nameplate, rated_torque_nm: parseFloat(e.target.value) || 0 })}
                />
              </div>

              <div className="static-field-group">
                <label className="static-field-label">
                  <span>Pole Pairs</span>
                  <span className="static-field-unit">p (2=4 pole)</span>
                </label>
                <input
                  type="number"
                  aria-label="Pole Pairs"
                  className="input"
                  value={nameplate.pole_pairs}
                  onChange={(e) => setNameplate({ ...nameplate, pole_pairs: parseInt(e.target.value, 10) || 1 })}
                />
              </div>

              <div className="static-field-group">
                <label className="static-field-label">
                  <span>Supply Freq</span>
                  <span className="static-field-unit">Hz</span>
                </label>
                <input
                  type="number"
                  aria-label="Supply Frequency"
                  className="input"
                  value={nameplate.supply_freq_hz}
                  onChange={(e) => setNameplate({ ...nameplate, supply_freq_hz: parseFloat(e.target.value) || 50 })}
                />
              </div>

              <div className="static-field-group">
                <label className="static-field-label">
                  <span>Insulation Class</span>
                  <span className="static-field-unit">NEMA/IEC</span>
                </label>
                <select
                  aria-label="Insulation Class"
                  className="input"
                  value={nameplate.insulation_class}
                  onChange={(e) => setNameplate({ ...nameplate, insulation_class: e.target.value as 'B' | 'F' | 'H' })}
                >
                  <option value="B">Class B (130°C)</option>
                  <option value="F">Class F (155°C)</option>
                  <option value="H">Class H (180°C)</option>
                </select>
              </div>
            </div>

            {/* Toggle Advanced Circuit parameters */}
            <div style={{ marginTop: '12px' }}>
              <button
                type="button"
                className="btn"
                style={{ padding: '4px 10px', fontSize: '0.75rem' }}
                onClick={() => setShowAdvancedEq(!showAdvancedEq)}
              >
                <Sliders size={12} />
                {showAdvancedEq ? 'Hide Equivalent Circuit Parameters' : 'Advanced Equivalent Circuit Parameters (Rs, Rr, Ls, Lr, Lm, J)'}
              </button>

              {showAdvancedEq && (
                <div className="static-grid-3" style={{ marginTop: '12px', padding: '12px', background: 'var(--surface-raised)', borderRadius: '8px' }}>
                  <div className="static-field-group">
                    <label className="static-field-label"><span>Rs (Stator Resistance)</span><span className="static-field-unit">Ω</span></label>
                    <input type="number" step="0.001" className="input" value={nameplate.Rs ?? ''} onChange={(e) => setNameplate({ ...nameplate, Rs: e.target.value ? parseFloat(e.target.value) : undefined })} />
                  </div>
                  <div className="static-field-group">
                    <label className="static-field-label"><span>Rr (Rotor Resistance)</span><span className="static-field-unit">Ω</span></label>
                    <input type="number" step="0.001" className="input" value={nameplate.Rr ?? ''} onChange={(e) => setNameplate({ ...nameplate, Rr: e.target.value ? parseFloat(e.target.value) : undefined })} />
                  </div>
                  <div className="static-field-group">
                    <label className="static-field-label"><span>Ls (Stator Inductance)</span><span className="static-field-unit">H</span></label>
                    <input type="number" step="0.0001" className="input" value={nameplate.Ls ?? ''} onChange={(e) => setNameplate({ ...nameplate, Ls: e.target.value ? parseFloat(e.target.value) : undefined })} />
                  </div>
                  <div className="static-field-group">
                    <label className="static-field-label"><span>Lr (Rotor Inductance)</span><span className="static-field-unit">H</span></label>
                    <input type="number" step="0.0001" className="input" value={nameplate.Lr ?? ''} onChange={(e) => setNameplate({ ...nameplate, Lr: e.target.value ? parseFloat(e.target.value) : undefined })} />
                  </div>
                  <div className="static-field-group">
                    <label className="static-field-label"><span>Lm (Mutual Inductance)</span><span className="static-field-unit">H</span></label>
                    <input type="number" step="0.0001" className="input" value={nameplate.Lm ?? ''} onChange={(e) => setNameplate({ ...nameplate, Lm: e.target.value ? parseFloat(e.target.value) : undefined })} />
                  </div>
                  <div className="static-field-group">
                    <label className="static-field-label"><span>J (Rotor Inertia)</span><span className="static-field-unit">kg·m²</span></label>
                    <input type="number" step="0.0001" className="input" value={nameplate.J ?? ''} onChange={(e) => setNameplate({ ...nameplate, J: e.target.value ? parseFloat(e.target.value) : undefined })} />
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Electrical Operating Inputs */}
      <div className="static-section-card">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Zap size={18} className="text-amber-400" />
            <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--ink)]" style={{ margin: 0 }}>
              2. Electrical &amp; Operational Measurements (Required)
            </h2>
          </div>

          {/* Basis Selectors */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span className="text-xs text-[var(--muted)]">Voltage Basis:</span>
              <select
                aria-label="Voltage Basis"
                className="input"
                style={{ width: '150px', padding: '4px 8px', fontSize: '0.75rem' }}
                value={voltageBasis}
                onChange={(e) => setVoltageBasis(e.target.value as VoltageBasis)}
              >
                <option value="line_line">Line-to-Line (V L-L)</option>
                <option value="line_neutral">Line-to-Neutral (V L-N)</option>
              </select>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span className="text-xs text-[var(--muted)]">Value Basis:</span>
              <select
                aria-label="Value Basis"
                className="input"
                style={{ width: '110px', padding: '4px 8px', fontSize: '0.75rem' }}
                value={valueBasis}
                onChange={(e) => setValueBasis(e.target.value as ValueBasis)}
              >
                <option value="rms">RMS</option>
                <option value="peak">Peak</option>
              </select>
            </div>
          </div>
        </div>

        {/* 3-phase Voltages & Currents */}
        <div className="static-grid-3">
          <div className="static-field-group">
            <label className="static-field-label"><span>Phase A Voltage (Va)</span><span className="static-field-unit">V</span></label>
            <input type="number" step="0.1" aria-label="Phase A Voltage" className="input" value={va} onChange={(e) => setVa(e.target.value)} />
          </div>
          <div className="static-field-group">
            <label className="static-field-label"><span>Phase B Voltage (Vb)</span><span className="static-field-unit">V</span></label>
            <input type="number" step="0.1" aria-label="Phase B Voltage" className="input" value={vb} onChange={(e) => setVb(e.target.value)} />
          </div>
          <div className="static-field-group">
            <label className="static-field-label"><span>Phase C Voltage (Vc)</span><span className="static-field-unit">V</span></label>
            <input type="number" step="0.1" aria-label="Phase C Voltage" className="input" value={vc} onChange={(e) => setVc(e.target.value)} />
          </div>

          <div className="static-field-group">
            <label className="static-field-label"><span>Phase A Current (Ia)</span><span className="static-field-unit">A RMS</span></label>
            <input type="number" step="0.01" aria-label="Phase A Current" className="input" value={ia} onChange={(e) => setIa(e.target.value)} />
          </div>
          <div className="static-field-group">
            <label className="static-field-label"><span>Phase B Current (Ib)</span><span className="static-field-unit">A RMS</span></label>
            <input type="number" step="0.01" aria-label="Phase B Current" className="input" value={ib} onChange={(e) => setIb(e.target.value)} />
          </div>
          <div className="static-field-group">
            <label className="static-field-label"><span>Phase C Current (Ic)</span><span className="static-field-unit">A RMS</span></label>
            <input type="number" step="0.01" aria-label="Phase C Current" className="input" value={ic} onChange={(e) => setIc(e.target.value)} />
          </div>

          <div className="static-field-group">
            <label className="static-field-label">
              <span>Shaft Speed (n)</span>
              <span className="static-field-unit">RPM (sync: {nSync.toFixed(0)})</span>
            </label>
            <input type="number" step="0.5" aria-label="Shaft Speed" className="input" value={speedRpm} onChange={(e) => setSpeedRpm(e.target.value)} />
          </div>

          <div className="static-field-group">
            <label className="static-field-label"><span>Grid Frequency</span><span className="static-field-unit">Hz</span></label>
            <input type="number" step="0.1" aria-label="Grid Frequency" className="input" value={supplyFreqHz} onChange={(e) => setSupplyFreqHz(e.target.value)} />
          </div>

          <div className="static-field-group">
            <label className="static-field-label"><span>Ambient Temperature</span><span className="static-field-unit">°C</span></label>
            <input type="number" step="0.5" aria-label="Ambient Temperature" className="input" value={ambientTemp} onChange={(e) => setAmbientTemp(e.target.value)} />
          </div>
        </div>
      </div>

      {/* Optional Channels: Thermal, Vibration, Spectral */}
      <div className="static-section-card">
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
          <Compass size={18} className="text-emerald-400" />
          <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--ink)]" style={{ margin: 0 }}>
            3. Optional Diagnostic Channels (Thermal, Vibration, Spectral)
          </h2>
        </div>

        <div className="static-grid-3">
          {/* Thermal */}
          <div style={{ background: 'var(--surface-raised)', padding: '14px', borderRadius: '8px', border: '1px solid var(--border)' }}>
            <span className="eyebrow" style={{ fontSize: '0.65rem' }}>THERMAL CHANNEL</span>
            <div className="static-field-group" style={{ marginTop: '8px' }}>
              <label className="static-field-label"><span>Winding Temp</span><span className="static-field-unit">°C</span></label>
              <input
                type="number"
                step="0.5"
                placeholder="e.g. 75.0"
                aria-label="Winding Temperature"
                className="input"
                value={windingTemp}
                onChange={(e) => setWindingTemp(e.target.value)}
              />
            </div>
            <p className="text-[11px] text-[var(--muted)]" style={{ marginTop: '6px' }}>
              Evaluates insulation margin against thermal class ({nameplate.insulation_class}).
            </p>
          </div>

          {/* Vibration */}
          <div style={{ background: 'var(--surface-raised)', padding: '14px', borderRadius: '8px', border: '1px solid var(--border)' }}>
            <span className="eyebrow" style={{ fontSize: '0.65rem' }}>MECHANICAL VIBRATION</span>
            <div className="static-field-group" style={{ marginTop: '8px' }}>
              <label className="static-field-label"><span>Overall RMS</span><span className="static-field-unit">mm/s</span></label>
              <input
                type="number"
                step="0.1"
                placeholder="e.g. 2.8"
                aria-label="Vibration Overall RMS"
                className="input"
                value={vibOverallRms}
                onChange={(e) => setVibOverallRms(e.target.value)}
              />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginTop: '8px' }}>
              <div className="static-field-group">
                <label className="static-field-label"><span>1X Peak</span><span className="static-field-unit">mm/s</span></label>
                <input type="number" step="0.1" aria-label="Vibration 1X Peak" className="input" value={vib1x} onChange={(e) => setVib1x(e.target.value)} />
              </div>
              <div className="static-field-group">
                <label className="static-field-label"><span>2X Peak</span><span className="static-field-unit">mm/s</span></label>
                <input type="number" step="0.1" aria-label="Vibration 2X Peak" className="input" value={vib2x} onChange={(e) => setVib2x(e.target.value)} />
              </div>
            </div>
            <div className="static-field-group" style={{ marginTop: '8px' }}>
              <label className="static-field-label"><span>Bearing Defect</span><span className="static-field-unit">mm/s</span></label>
              <input
                type="number"
                step="0.1"
                placeholder="BPFO/BPFI envelope"
                aria-label="Vibration Bearing Defect Peak"
                className="input"
                value={vibBearingDefect}
                onChange={(e) => setVibBearingDefect(e.target.value)}
              />
            </div>
          </div>

          {/* Spectral */}
          <div style={{ background: 'var(--surface-raised)', padding: '14px', borderRadius: '8px', border: '1px solid var(--border)' }}>
            <span className="eyebrow" style={{ fontSize: '0.65rem' }}>SPECTRAL / MCSA</span>
            <div className="static-field-group" style={{ marginTop: '8px' }}>
              <label className="static-field-label"><span>BRB Sideband</span><span className="static-field-unit">dB (carrier)</span></label>
              <input
                type="number"
                step="0.5"
                placeholder="e.g. -32.0"
                aria-label="Broken Rotor Bar Sideband dB"
                className="input"
                value={brbSidebandDb}
                onChange={(e) => setBrbSidebandDb(e.target.value)}
              />
            </div>
            <div className="static-field-group" style={{ marginTop: '8px' }}>
              <label className="static-field-label"><span>Eccentricity Sideband</span><span className="static-field-unit">dB</span></label>
              <input
                type="number"
                step="0.5"
                placeholder="e.g. -30.0"
                aria-label="Eccentricity Sideband dB"
                className="input"
                value={eccentricityDb}
                onChange={(e) => setEccentricityDb(e.target.value)}
              />
            </div>
            <div className="static-field-group" style={{ marginTop: '8px' }}>
              <label className="static-field-label"><span>Voltage THD</span><span className="static-field-unit">%</span></label>
              <input
                type="number"
                step="0.1"
                placeholder="e.g. 2.5"
                aria-label="Voltage THD Percent"
                className="input"
                value={vThdPct}
                onChange={(e) => setVThdPct(e.target.value)}
              />
            </div>
          </div>
        </div>

        {/* Validation Error Banner */}
        {error && (
          <div
            role="alert"
            style={{
              marginTop: '16px',
              padding: '12px 16px',
              borderRadius: '8px',
              background: 'rgba(239, 68, 68, 0.1)',
              border: '1px solid rgba(239, 68, 68, 0.3)',
              color: '#f87171',
              display: 'flex',
              alignItems: 'center',
              gap: '10px',
              fontSize: '0.85rem',
            }}
          >
            <AlertCircle size={18} style={{ flexShrink: 0 }} />
            <span>{error}</span>
          </div>
        )}

        {/* Action Button */}
        <div style={{ marginTop: '20px', display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
          <button
            type="button"
            className="btn"
            onClick={() => handleSelectPreset('healthy')}
            title="Reset form to healthy baseline"
          >
            <RotateCcw size={14} />
            Reset Defaults
          </button>

          <button
            type="button"
            className="btn btn-primary"
            style={{ minWidth: '180px' }}
            disabled={diagnosing}
            onClick={handleRunDiagnosis}
          >
            {diagnosing ? (
              <>
                <RefreshCw size={14} className="animate-spin" />
                Diagnosing…
              </>
            ) : (
              <>
                <Activity size={16} />
                Run Static Diagnosis
              </>
            )}
          </button>
        </div>
      </div>

      {/* Diagnosis Results Section */}
      {result && (
        <div className="glass-card" style={{ padding: '28px 32px' }} data-testid="static-results-container">
          <header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid var(--border)', paddingBottom: '14px', marginBottom: '20px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <span className="w-8 h-8 rounded-md bg-[var(--surface-raised)] border border-[var(--border)] flex items-center justify-center text-[var(--accent)]">
                <Activity size={18} />
              </span>
              <div>
                <span className="eyebrow" style={{ fontSize: '0.7rem' }}>FUSED MULTI-CHANNEL EVALUATION</span>
                <h2 className="text-base font-bold uppercase tracking-wider text-[var(--ink)]" style={{ margin: 0 }}>
                  Diagnostic Assessment Output
                </h2>
              </div>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span className="badge-error-code" style={{ background: 'var(--surface-raised)', border: '1px solid var(--border)', color: 'var(--ink)' }}>
                {result.error_code}
              </span>
              <span className="text-xs num text-[var(--muted)] px-2 py-1 rounded bg-[var(--surface-raised)] border border-[var(--border)]">
                v{result.schema_version}
              </span>
            </div>
          </header>

          {/* Primary Cards Grid: Health Gauge, Fused Classification, Derived Metrics */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '20px', marginBottom: '24px' }}>
            {/* Health Gauge Card */}
            <div className="static-section-card flex flex-col items-center justify-center" style={{ textAlign: 'center', padding: '24px' }}>
              <HealthGauge value={result.health_index} zone={result.zone} size="lg" />
              <div style={{ marginTop: '12px' }}>
                <span className="eyebrow" style={{ fontSize: '0.65rem' }}>HEALTH STATUS</span>
                <div className="text-xs text-[var(--muted)] mt-1">
                  MHI: <strong className="text-white num">{result.health_index.toFixed(1)}/100</strong> (Zone {result.zone})
                </div>
              </div>
            </div>

            {/* Fused Condition Card */}
            <div className="static-section-card flex flex-col justify-between" style={{ padding: '20px' }}>
              <div>
                <span className="eyebrow" style={{ fontSize: '0.65rem' }}>FUSED VERDICT</span>
                <div
                  className="text-2xl font-bold capitalize mt-1"
                  style={{
                    color:
                      result.fault_type === 'healthy'
                        ? 'var(--good)'
                        : result.zone === 'D'
                        ? 'var(--critical)'
                        : result.zone === 'C'
                        ? 'var(--serious)'
                        : 'var(--warning)',
                  }}
                  data-testid="static-fused-fault"
                >
                  {label(result.fault_type)}
                </div>
                <div className="text-xs text-[var(--muted)] mt-1">
                  Confidence: <strong className="num text-white">{(result.confidence * 100).toFixed(0)}%</strong> | Severity:{' '}
                  <strong className="num text-white">{(result.severity * 100).toFixed(0)}%</strong>
                </div>
              </div>

              {/* Confidence & Severity meters */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '16px' }}>
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: 'var(--muted)', marginBottom: '3px' }}>
                    <span>Confidence Score</span>
                    <span className="num">{(result.confidence * 100).toFixed(0)}%</span>
                  </div>
                  <div style={{ height: '6px', borderRadius: '9999px', background: 'var(--surface-raised)', overflow: 'hidden' }}>
                    <div style={{ height: '100%', width: `${Math.round(result.confidence * 100)}%`, background: 'var(--accent)' }} />
                  </div>
                </div>

                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: 'var(--muted)', marginBottom: '3px' }}>
                    <span>Severity Score</span>
                    <span className="num">{(result.severity * 100).toFixed(0)}%</span>
                  </div>
                  <div style={{ height: '6px', borderRadius: '9999px', background: 'var(--surface-raised)', overflow: 'hidden' }}>
                    <div
                      style={{
                        height: '100%',
                        width: `${Math.round(result.severity * 100)}%`,
                        background: result.severity > 0.7 ? 'var(--critical)' : result.severity > 0.4 ? 'var(--warning)' : 'var(--good)',
                      }}
                    />
                  </div>
                </div>
              </div>
            </div>

            {/* Derived Physics Metrics Card */}
            <div className="static-section-card" style={{ padding: '20px' }}>
              <span className="eyebrow" style={{ fontSize: '0.65rem' }}>DERIVED PHYSICS PARAMETERS</span>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginTop: '12px' }}>
                <div style={{ background: 'var(--surface-raised)', padding: '8px 10px', borderRadius: '6px' }}>
                  <div className="text-[10px] text-[var(--muted)] uppercase">Operating Slip</div>
                  <div className="text-sm font-semibold num text-white">{(result.derived.slip * 100).toFixed(2)}%</div>
                </div>
                <div style={{ background: 'var(--surface-raised)', padding: '8px 10px', borderRadius: '6px' }}>
                  <div className="text-[10px] text-[var(--muted)] uppercase">Loading (pu)</div>
                  <div className="text-sm font-semibold num text-white">{result.derived.loading_pu.toFixed(2)} pu</div>
                </div>
                <div style={{ background: 'var(--surface-raised)', padding: '8px 10px', borderRadius: '6px' }}>
                  <div className="text-[10px] text-[var(--muted)] uppercase">Expected Current</div>
                  <div className="text-sm font-semibold num text-white">{result.derived.expected_current_a.toFixed(2)} A</div>
                </div>
                <div style={{ background: 'var(--surface-raised)', padding: '8px 10px', borderRadius: '6px' }}>
                  <div className="text-[10px] text-[var(--muted)] uppercase">Current Residual</div>
                  <div className="text-sm font-semibold num text-white">{result.derived.stator_current_residual_a.toFixed(2)} A</div>
                </div>
                <div style={{ background: 'var(--surface-raised)', padding: '8px 10px', borderRadius: '6px' }}>
                  <div className="text-[10px] text-[var(--muted)] uppercase">Current Imbalance</div>
                  <div className="text-sm font-semibold num text-white">{result.derived.current_imbalance_pct.toFixed(1)}%</div>
                </div>
                <div style={{ background: 'var(--surface-raised)', padding: '8px 10px', borderRadius: '6px' }}>
                  <div className="text-[10px] text-[var(--muted)] uppercase">Voltage Unbalance (VUF)</div>
                  <div className="text-sm font-semibold num text-white">{result.derived.voltage_unbalance_pct.toFixed(2)}%</div>
                </div>
              </div>
            </div>
          </div>

          {/* Prescriptive Recommendation Card */}
          {result.recommendation && (
            <div className="static-section-card" style={{ marginBottom: '24px', borderLeft: '4px solid var(--accent)' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                <span className="eyebrow" style={{ fontSize: '0.65rem' }}>PRESCRIPTIVE MAINTENANCE DIRECTIVE</span>
                <span className={`urgency-pill urgency-pill--${result.recommendation.urgency || 'routine'}`}>
                  {result.recommendation.urgency || 'routine'} urgency
                </span>
              </div>
              <h3 className="text-base font-semibold text-white" style={{ margin: '4px 0 8px 0' }}>
                {result.recommendation.action}
              </h3>
              {result.recommendation.reason && (
                <p className="text-xs text-[var(--muted)]" style={{ margin: '0 0 12px 0' }}>
                  {result.recommendation.reason}
                </p>
              )}
              {Array.isArray(result.recommendation.checklists) && result.recommendation.checklists.length > 0 && (
                <div style={{ background: 'var(--surface-raised)', padding: '12px', borderRadius: '8px' }}>
                  <div className="text-xs font-semibold text-[var(--ink-2)] mb-2">Recommended Inspection Checklist:</div>
                  <ul style={{ margin: 0, paddingLeft: '20px', fontSize: '0.8rem', color: 'var(--ink)' }}>
                    {result.recommendation.checklists.map((c: string, idx: number) => (
                      <li key={idx} style={{ marginBottom: '4px' }}>
                        {c}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {/* Input Quality Strip */}
          <div className="static-quality-strip" style={{ marginBottom: '24px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <CheckCircle2 size={16} className="text-emerald-400" />
                <span className="text-xs font-semibold uppercase tracking-wider text-white">
                  Assessment Coverage: {result.channels_run.length} assessed, {Object.keys(result.channels_skipped).length} skipped
                </span>
              </div>
            </div>

            {Object.keys(result.channels_skipped).length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginTop: '4px' }}>
                {Object.entries(result.channels_skipped).map(([ch, reason]) => (
                  <div key={ch} style={{ fontSize: '0.75rem', color: 'var(--muted)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#f59e0b', display: 'inline-block' }} />
                    <strong className="capitalize text-amber-300">{ch.replace('_', ' ')}:</strong>
                    <span>{reason}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Per-Channel Breakdown Table */}
          <div className="static-section-card" style={{ padding: 0, overflow: 'hidden' }}>
            <div style={{ padding: '12px 16px', background: 'var(--surface-raised)', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Sliders size={16} className="text-[var(--accent)]" />
              <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--ink)]" style={{ margin: 0 }}>
                Diagnostic Channel Verdicts
              </h3>
            </div>

            <div style={{ overflowX: 'auto' }}>
              <div className="static-channel-row" style={{ background: 'var(--surface-raised)', fontWeight: 600, color: 'var(--muted)', textTransform: 'uppercase', fontSize: '0.7rem' }}>
                <div>Channel Source</div>
                <div>Status</div>
                <div>Verdict</div>
                <div>Confidence</div>
                <div>Severity</div>
                <div>Diagnostic Details</div>
              </div>

              {Object.entries(result.per_sensor_scores).map(([key, score]) => {
                const isAssessed = score.available
                return (
                  <div key={key} className="static-channel-row">
                    <div className="font-semibold text-white capitalize">{key.replace('_', ' ')}</div>
                    <div>
                      {isAssessed ? (
                        <span className="badge-status badge-status--assessed">Assessed</span>
                      ) : (
                        <span className="badge-status badge-status--skipped">Not Assessable</span>
                      )}
                    </div>
                    <div className="capitalize font-medium" style={{ color: isAssessed ? (score.fault_type === 'healthy' ? 'var(--good)' : 'var(--warning)') : 'var(--muted)' }}>
                      {isAssessed ? label(score.fault_type) : '—'}
                    </div>
                    <div className="num">{isAssessed ? `${Math.round(score.confidence * 100)}%` : '—'}</div>
                    <div className="num">{isAssessed ? `${Math.round(score.severity * 100)}%` : '—'}</div>
                    <div className="text-xs text-[var(--muted)] truncate" title={JSON.stringify(score.details)}>
                      {isAssessed
                        ? Object.entries(score.details || {})
                            .map(([k, v]) => `${k}: ${typeof v === 'number' ? v.toFixed(2) : v}`)
                            .join(', ') || 'OK'
                        : result.channels_skipped[key] || 'Omitted from manual inputs'}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      )}

      {/* History of Saved Analyses */}
      <div className="glass-card" style={{ padding: '24px 32px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Clock size={18} className="text-[var(--accent)]" />
            <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--ink)]" style={{ margin: 0 }}>
              Saved Static Analyses History
            </h2>
          </div>

          <button
            type="button"
            className="btn"
            style={{ padding: '4px 10px', fontSize: '0.75rem' }}
            onClick={fetchHistory}
            disabled={historyLoading}
          >
            <RefreshCw size={12} className={historyLoading ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>

        {history.length === 0 ? (
          <p className="text-xs text-[var(--muted)]" style={{ textAlign: 'center', padding: '16px 0' }}>
            No static analyses saved yet. Run a diagnosis above to automatically save and track history.
          </p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border)', textAlign: 'left', color: 'var(--muted)' }}>
                  <th style={{ padding: '8px 12px' }}>ID</th>
                  <th style={{ padding: '8px 12px' }}>Timestamp</th>
                  <th style={{ padding: '8px 12px' }}>Operator</th>
                  <th style={{ padding: '8px 12px' }}>Motor</th>
                  <th style={{ padding: '8px 12px' }}>Diagnosed Fault</th>
                  <th style={{ padding: '8px 12px' }}>Severity</th>
                  <th style={{ padding: '8px 12px' }}>MHI</th>
                  <th style={{ padding: '8px 12px' }}>Code</th>
                  <th style={{ padding: '8px 12px', textAlign: 'right' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {history.map((row) => (
                  <tr key={row.id} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                    <td className="num font-semibold text-white" style={{ padding: '8px 12px' }}>#{row.id}</td>
                    <td className="num text-[var(--muted)]" style={{ padding: '8px 12px' }}>{new Date(row.ts).toLocaleTimeString()}</td>
                    <td style={{ padding: '8px 12px' }}>{row.user}</td>
                    <td style={{ padding: '8px 12px' }}>{row.motor_id ? `Motor #${row.motor_id}` : 'Nameplate'}</td>
                    <td style={{ padding: '8px 12px' }} className="capitalize font-semibold text-white">
                      {label(row.fault_type)}
                    </td>
                    <td className="num" style={{ padding: '8px 12px' }}>{(row.severity * 100).toFixed(0)}%</td>
                    <td className="num font-semibold text-white" style={{ padding: '8px 12px' }}>{row.mhi.toFixed(0)} ({row.zone ?? '—'})</td>
                    <td style={{ padding: '8px 12px' }}>
                      <span className="badge-error-code" style={{ padding: '2px 6px', fontSize: '0.7rem', background: 'var(--surface-raised)' }}>
                        {row.error_code ?? '—'}
                      </span>
                    </td>
                    <td style={{ padding: '8px 12px', textAlign: 'right' }}>
                      <button
                        type="button"
                        className="btn"
                        style={{ padding: '2px 8px', fontSize: '0.7rem' }}
                        onClick={() => handleLoadHistoryRecord(row.id)}
                      >
                        Load Record
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
