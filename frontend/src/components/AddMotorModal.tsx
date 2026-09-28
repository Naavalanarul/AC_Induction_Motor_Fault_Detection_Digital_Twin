import React, { useState } from 'react'
import { X, Cpu, Sliders, CheckCircle2, AlertTriangle, Loader2 } from 'lucide-react'
import { api } from '../api/client'
import type { Motor } from '../api/types'

export interface MotorCreationParams {
  Rs: number
  Rr: number
  Ls: number
  Lr: number
  Lm: number
  J: number
  pole_pairs: number
  rated_power: number
  rated_voltage: number
  rated_current: number
  rated_speed: number
  rated_torque: number
}

export interface PresetTemplate {
  key: string
  label: string
  category: string
  description: string
  base_load_nm: number
  params: MotorCreationParams
}

const MOTOR_PRESETS: PresetTemplate[] = [
  {
    key: 'default_1_5kw',
    label: '1.5 kW 4-Pole Lab Machine (Chen 2025 DTC)',
    category: 'Lab Standard',
    description: '400V 50Hz standard benchmark from digital twin induction literature.',
    base_load_nm: 8.0,
    params: {
      Rs: 1.405,
      Rr: 1.395,
      Ls: 0.178039,
      Lr: 0.178039,
      Lm: 0.1722,
      J: 0.0131,
      pole_pairs: 2,
      rated_power: 1500,
      rated_voltage: 380,
      rated_current: 4.7,
      rated_speed: 1474,
      rated_torque: 10.0,
    },
  },
  {
    key: 'pump_3kw',
    label: '3.0 kW 2-Pole High-Speed Pump Motor',
    category: 'Pumping',
    description: 'High-speed centrifugal chemical transfer pump drive.',
    base_load_nm: 8.0,
    params: {
      Rs: 1.15,
      Rr: 0.98,
      Ls: 0.132,
      Lr: 0.132,
      Lm: 0.127,
      J: 0.028,
      pole_pairs: 1,
      rated_power: 3000,
      rated_voltage: 380,
      rated_current: 6.8,
      rated_speed: 2920,
      rated_torque: 9.8,
    },
  },
  {
    key: 'conveyor_5_5kw',
    label: '5.5 kW 4-Pole Industrial Conveyor Motor',
    category: 'Material Handling',
    description: 'Robust medium-frame continuous belt drive.',
    base_load_nm: 28.0,
    params: {
      Rs: 0.38,
      Rr: 0.35,
      Ls: 0.0485,
      Lr: 0.0485,
      Lm: 0.0468,
      J: 0.065,
      pole_pairs: 2,
      rated_power: 5500,
      rated_voltage: 380,
      rated_current: 11.5,
      rated_speed: 1460,
      rated_torque: 36.0,
    },
  },
  {
    key: 'heavy_conveyor_11kw',
    label: '11.0 kW 4-Pole Heavy Assembly Conveyor',
    category: 'Heavy Material',
    description: 'High-capacity plant distribution line conveyor drive.',
    base_load_nm: 55.0,
    params: {
      Rs: 0.19,
      Rr: 0.17,
      Ls: 0.0242,
      Lr: 0.0242,
      Lm: 0.0233,
      J: 0.18,
      pole_pairs: 2,
      rated_power: 11000,
      rated_voltage: 380,
      rated_current: 22.0,
      rated_speed: 1465,
      rated_torque: 72.0,
    },
  },
  {
    key: 'booster_pump_15kw',
    label: '15.0 kW 4-Pole Water Booster Pump',
    category: 'Municipal Water',
    description: 'Continuous duty high-flow wastewater booster drive.',
    base_load_nm: 75.0,
    params: {
      Rs: 0.28,
      Rr: 0.22,
      Ls: 0.042,
      Lr: 0.042,
      Lm: 0.0405,
      J: 0.16,
      pole_pairs: 2,
      rated_power: 15000,
      rated_voltage: 400,
      rated_current: 29.5,
      rated_speed: 1470,
      rated_torque: 97.4,
    },
  },
  {
    key: 'compressor_37kw',
    label: '37.0 kW 4-Pole Utility Gas Compressor',
    category: 'Utility Gas',
    description: 'Medium-voltage industrial plant air utility compressor.',
    base_load_nm: 180.0,
    params: {
      Rs: 0.055,
      Rr: 0.048,
      Ls: 0.0072,
      Lr: 0.0072,
      Lm: 0.00695,
      J: 0.85,
      pole_pairs: 2,
      rated_power: 37000,
      rated_voltage: 380,
      rated_current: 71.0,
      rated_speed: 1475,
      rated_torque: 240.0,
    },
  },
  {
    key: 'slurry_compressor_75kw',
    label: '75.0 kW 6-Pole Heavy Slurry Compressor',
    category: 'Mining & Slurry',
    description: 'High-torque low-speed heavy industrial gas compressor.',
    base_load_nm: 380.0,
    params: {
      Rs: 0.025,
      Rr: 0.022,
      Ls: 0.0035,
      Lr: 0.0035,
      Lm: 0.00338,
      J: 2.4,
      pole_pairs: 3,
      rated_power: 75000,
      rated_voltage: 380,
      rated_current: 142.0,
      rated_speed: 980,
      rated_torque: 484.0,
    },
  },
]

export interface AddMotorModalProps {
  isOpen: boolean
  onClose: () => void
  onMotorAdded: (newMotorId: number) => void
}

export function AddMotorModal({ isOpen, onClose, onMotorAdded }: AddMotorModalProps) {
  const [mode, setMode] = useState<'preset' | 'custom'>('preset')
  const [selectedPresetKey, setSelectedPresetKey] = useState<string>(MOTOR_PRESETS[0].key)
  const [motorName, setMotorName] = useState<string>('Custom Motor Asset')
  const [baseLoadNm, setBaseLoadNm] = useState<number>(MOTOR_PRESETS[0].base_load_nm)
  const [params, setParams] = useState<MotorCreationParams>(MOTOR_PRESETS[0].params)
  const [busy, setBusy] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)

  if (!isOpen) return null

  const handleSelectPreset = (presetKey: string) => {
    setSelectedPresetKey(presetKey)
    const found = MOTOR_PRESETS.find((p) => p.key === presetKey)
    if (found) {
      setBaseLoadNm(found.base_load_nm)
      setParams({ ...found.params })
      setMotorName(`${found.label.split('—')[0].trim()} Twin`)
    }
  }

  const handleParamChange = (field: keyof MotorCreationParams, value: number) => {
    setParams((prev) => ({ ...prev, [field]: value }))
  }

  // Physical feasibility checks
  const isPositiveLeakage = params.Lm < Math.min(params.Ls, params.Lr)
  const leakageFactor = params.Ls * params.Lr > 0
    ? (1 - (params.Lm * params.Lm) / (params.Ls * params.Lr)).toFixed(4)
    : '—'
  const rotorTimeConstantMs = params.Rr > 0
    ? ((params.Lr / params.Rr) * 1000).toFixed(1)
    : '—'

  const isValid =
    motorName.trim().length > 0 &&
    isPositiveLeakage &&
    params.Rs > 0 &&
    params.Rr > 0 &&
    params.Ls > 0 &&
    params.Lr > 0 &&
    params.Lm > 0 &&
    params.J > 0 &&
    params.pole_pairs >= 1 &&
    params.rated_power > 0 &&
    params.rated_voltage > 0 &&
    params.rated_current > 0 &&
    params.rated_speed > 0 &&
    params.rated_torque > 0

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!isValid || busy) return

    setBusy(true)
    setError(null)

    try {
      const payload = {
        name: motorName.trim(),
        base_load_nm: Number(baseLoadNm),
        params: {
          Rs: Number(params.Rs),
          Rr: Number(params.Rr),
          Ls: Number(params.Ls),
          Lr: Number(params.Lr),
          Lm: Number(params.Lm),
          J: Number(params.J),
          pole_pairs: Math.round(Number(params.pole_pairs)),
          rated_power: Number(params.rated_power),
          rated_voltage: Number(params.rated_voltage),
          rated_current: Number(params.rated_current),
          rated_speed: Number(params.rated_speed),
          rated_torque: Number(params.rated_torque),
        },
      }

      const res = await api<Motor>('/motors', {
        method: 'POST',
        body: JSON.stringify(payload),
      })

      onMotorAdded(res.id)
      onClose()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to provision motor')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="modal-dialog glass-card"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-motor-title"
      >
        {/* Modal Header */}
        <header className="modal-header">
          <div>
            <span className="eyebrow">ASSET PROVISIONING</span>
            <h2 id="add-motor-title" className="fleet-title" style={{ fontSize: '1.25rem', marginTop: 2 }}>
              Add Induction Motor Twin
            </h2>
            <p className="page-subtitle" style={{ marginTop: 2 }}>
              Deploy a new motor digital twin using standard industrial presets or custom physical parameters.
            </p>
          </div>
          <button
            className="nav-icon-btn"
            onClick={onClose}
            aria-label="Close dialog"
            title="Close dialog"
          >
            <X size={18} />
          </button>
        </header>

        {/* Modal Body */}
        <form onSubmit={handleSubmit} className="modal-body" noValidate>
          {error && (
            <div
              className="glass-card"
              style={{
                padding: '10px 14px',
                borderColor: 'rgba(239, 68, 68, 0.4)',
                background: 'rgba(239, 68, 68, 0.08)',
                color: '#f87171',
                fontSize: 12,
                display: 'flex',
                alignItems: 'center',
                gap: 8,
              }}
            >
              <AlertTriangle size={16} />
              <span>{error}</span>
            </div>
          )}

          {/* Mode Selector */}
          <div style={{ display: 'flex', gap: 10, background: 'var(--surface-raised)', padding: 4, borderRadius: 'var(--corner-full)', border: '1px solid var(--border)' }}>
            <button
              type="button"
              className={`btn ${mode === 'preset' ? 'btn-primary' : ''}`}
              style={{ flex: 1, padding: '6px 12px', fontSize: 12, borderRadius: 'var(--corner-full)', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}
              onClick={() => setMode('preset')}
            >
              <Cpu size={14} />
              <span>Industrial Preset Template</span>
            </button>
            <button
              type="button"
              className={`btn ${mode === 'custom' ? 'btn-primary' : ''}`}
              style={{ flex: 1, padding: '6px 12px', fontSize: 12, borderRadius: 'var(--corner-full)', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}
              onClick={() => setMode('custom')}
            >
              <Sliders size={14} />
              <span>Custom Physical Parameters</span>
            </button>
          </div>

          {/* Preset Selector Card */}
          {mode === 'preset' && (
            <div className="card" style={{ background: 'var(--surface-raised)', border: '1px solid var(--border)', padding: 14 }}>
              <label style={{ display: 'block', marginBottom: 6, fontSize: 11, fontWeight: 600, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Select Machine Preset
              </label>
              <select
                className="input"
                value={selectedPresetKey}
                onChange={(e) => handleSelectPreset(e.target.value)}
                style={{ fontSize: 13, background: 'var(--surface)', borderColor: 'var(--border)' }}
                aria-label="Preset machine template"
              >
                {MOTOR_PRESETS.map((p) => (
                  <option key={p.key} value={p.key}>
                    {p.label} ({(p.params.rated_power / 1000).toFixed(1)} kW · {p.params.rated_speed} RPM)
                  </option>
                ))}
              </select>
              <p style={{ marginTop: 8, fontSize: 11, color: 'var(--ink-2)' }}>
                {MOTOR_PRESETS.find((p) => p.key === selectedPresetKey)?.description}
              </p>
            </div>
          )}

          {/* Primary Asset Attributes */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 14 }}>
            <div>
              <label style={{ display: 'block', fontSize: 11, fontWeight: 600, color: 'var(--ink-2)', marginBottom: 4 }}>
                Motor Asset Name *
              </label>
              <input
                className="input"
                type="text"
                placeholder="e.g. Pump Motor — Bay 4"
                value={motorName}
                onChange={(e) => setMotorName(e.target.value)}
                required
              />
            </div>
            <div>
              <label style={{ display: 'block', fontSize: 11, fontWeight: 600, color: 'var(--ink-2)', marginBottom: 4 }}>
                Base Process Load (N·m) *
              </label>
              <input
                className="input"
                type="number"
                step="any"
                min="0"
                max="2000"
                value={baseLoadNm}
                onChange={(e) => setBaseLoadNm(parseFloat(e.target.value) || 0)}
                required
              />
            </div>
          </div>

          {/* Nameplate Ratings */}
          <div className="card" style={{ padding: 14 }}>
            <span className="eyebrow" style={{ color: 'var(--accent)', marginBottom: 8, display: 'block' }}>
              1. Nameplate Ratings
            </span>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 12 }}>
              <div>
                <label style={{ display: 'block', fontSize: 10, color: 'var(--muted)', marginBottom: 2 }}>Rated Power (W)</label>
                <input
                  className="input"
                  type="number"
                  step="any"
                  min="1"
                  value={params.rated_power}
                  onChange={(e) => handleParamChange('rated_power', parseFloat(e.target.value) || 0)}
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: 10, color: 'var(--muted)', marginBottom: 2 }}>Rated Voltage (V)</label>
                <input
                  className="input"
                  type="number"
                  step="any"
                  min="1"
                  value={params.rated_voltage}
                  onChange={(e) => handleParamChange('rated_voltage', parseFloat(e.target.value) || 0)}
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: 10, color: 'var(--muted)', marginBottom: 2 }}>Rated Current (A)</label>
                <input
                  className="input"
                  type="number"
                  step="any"
                  min="0.1"
                  value={params.rated_current}
                  onChange={(e) => handleParamChange('rated_current', parseFloat(e.target.value) || 0)}
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: 10, color: 'var(--muted)', marginBottom: 2 }}>Rated Speed (RPM)</label>
                <input
                  className="input"
                  type="number"
                  step="any"
                  min="1"
                  value={params.rated_speed}
                  onChange={(e) => handleParamChange('rated_speed', parseFloat(e.target.value) || 0)}
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: 10, color: 'var(--muted)', marginBottom: 2 }}>Rated Torque (N·m)</label>
                <input
                  className="input"
                  type="number"
                  step="any"
                  min="0.1"
                  value={params.rated_torque}
                  onChange={(e) => handleParamChange('rated_torque', parseFloat(e.target.value) || 0)}
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: 10, color: 'var(--muted)', marginBottom: 2 }}>Pole Pairs (p)</label>
                <input
                  className="input"
                  type="number"
                  step="1"
                  min="1"
                  max="12"
                  value={params.pole_pairs}
                  onChange={(e) => handleParamChange('pole_pairs', parseInt(e.target.value, 10) || 1)}
                />
              </div>
            </div>
          </div>

          {/* Equivalent Circuit & Mechanics */}
          <div className="card" style={{ padding: 14 }}>
            <span className="eyebrow" style={{ color: 'var(--accent)', marginBottom: 8, display: 'block' }}>
              2. Equivalent Circuit &amp; Mechanics (State-Space RK4)
            </span>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 12 }}>
              <div>
                <label style={{ display: 'block', fontSize: 10, color: 'var(--muted)', marginBottom: 2 }}>Stator Res Rs (Ω)</label>
                <input
                  className="input"
                  type="number"
                  step="any"
                  min="0.0001"
                  value={params.Rs}
                  onChange={(e) => handleParamChange('Rs', parseFloat(e.target.value) || 0)}
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: 10, color: 'var(--muted)', marginBottom: 2 }}>Rotor Res Rr (Ω)</label>
                <input
                  className="input"
                  type="number"
                  step="any"
                  min="0.0001"
                  value={params.Rr}
                  onChange={(e) => handleParamChange('Rr', parseFloat(e.target.value) || 0)}
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: 10, color: 'var(--muted)', marginBottom: 2 }}>Stator Ind Ls (H)</label>
                <input
                  className="input"
                  type="number"
                  step="any"
                  min="0.0001"
                  value={params.Ls}
                  onChange={(e) => handleParamChange('Ls', parseFloat(e.target.value) || 0)}
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: 10, color: 'var(--muted)', marginBottom: 2 }}>Rotor Ind Lr (H)</label>
                <input
                  className="input"
                  type="number"
                  step="any"
                  min="0.0001"
                  value={params.Lr}
                  onChange={(e) => handleParamChange('Lr', parseFloat(e.target.value) || 0)}
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: 10, color: 'var(--muted)', marginBottom: 2 }}>Mutual Ind Lm (H)</label>
                <input
                  className="input"
                  type="number"
                  step="any"
                  min="0.0001"
                  value={params.Lm}
                  onChange={(e) => handleParamChange('Lm', parseFloat(e.target.value) || 0)}
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: 10, color: 'var(--muted)', marginBottom: 2 }}>Inertia J (kg·m²)</label>
                <input
                  className="input"
                  type="number"
                  step="any"
                  min="0.0001"
                  value={params.J}
                  onChange={(e) => handleParamChange('J', parseFloat(e.target.value) || 0)}
                />
              </div>
            </div>
          </div>

          {/* Derived Physical Validation Callout */}
          <div
            style={{
              padding: '10px 14px',
              borderRadius: 'var(--corner-md)',
              background: isPositiveLeakage ? 'rgba(16, 185, 129, 0.08)' : 'rgba(239, 68, 68, 0.08)',
              border: `1px solid ${isPositiveLeakage ? 'rgba(16, 185, 129, 0.25)' : 'rgba(239, 68, 68, 0.3)'}`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              flexWrap: 'wrap',
              gap: 8,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              {isPositiveLeakage ? (
                <CheckCircle2 size={16} style={{ color: 'var(--good)' }} />
              ) : (
                <AlertTriangle size={16} style={{ color: 'var(--critical)' }} />
              )}
              <span style={{ fontSize: 12, fontWeight: 500, color: isPositiveLeakage ? 'var(--good)' : 'var(--critical)' }}>
                {isPositiveLeakage
                  ? 'Physical State-Space Feasibility Verified'
                  : 'Physical Constraint Violated: Lm must be strictly smaller than Ls and Lr'}
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14, fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--muted)' }}>
              <span>Leakage σ: <strong style={{ color: 'var(--ink)' }}>{leakageFactor}</strong></span>
              <span>Rotor Tr: <strong style={{ color: 'var(--ink)' }}>{rotorTimeConstantMs} ms</strong></span>
            </div>
          </div>

          {/* Modal Footer */}
          <footer className="modal-footer" style={{ margin: '10px -24px -20px', padding: '16px 24px', borderTop: '1px solid var(--border)' }}>
            <button type="button" className="btn" onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={!isValid || busy}
              style={{ display: 'flex', alignItems: 'center', gap: 8 }}
            >
              {busy ? (
                <>
                  <Loader2 size={15} style={{ animation: 'login-spin 900ms linear infinite' }} />
                  <span>Provisioning Twin…</span>
                </>
              ) : (
                <>
                  <Cpu size={15} />
                  <span>Create &amp; Provision Motor</span>
                </>
              )}
            </button>
          </footer>
        </form>
      </div>
    </div>
  )
}
