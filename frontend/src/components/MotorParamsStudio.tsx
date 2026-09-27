import { useState, useMemo } from 'react'
import type { Motor } from '../api/types'

interface MotorParamsStudioProps {
  currentMotor?: Motor
  onApplyParams?: (params: Record<string, number>) => void
}

interface MotorFullParams {
  // Equivalent Circuit
  Rs: number
  Rr: number
  Ls: number
  Lr: number
  Lm: number
  // Mechanical
  J: number
  pole_pairs: number
  B: number
  base_load_nm: number
  // Nameplate Ratings
  rated_power: number
  rated_voltage: number
  rated_current: number
  rated_speed: number
  rated_torque: number
  // Thermal
  R_th: number
  C_th: number
  T_ambient: number
  T_warning: number
  T_trip: number
  // Supply Grid
  supply_freq: number
  supply_voltage: number
}

// Industry Benchmark Presets
const PRESETS: Record<string, { label: string; description: string; params: MotorFullParams }> = {
  default_1_5kw: {
    label: '1.5 kW 4-Pole Lab Benchmark (DTC / Chen 2025)',
    description: 'Widely used 1.5 kW, 400V, 50 Hz machine from field-oriented control literature.',
    params: {
      Rs: 1.405,
      Rr: 1.395,
      Ls: 0.178039,
      Lr: 0.178039,
      Lm: 0.1722,
      J: 0.0131,
      pole_pairs: 2,
      B: 0.0015,
      base_load_nm: 8.0,
      rated_power: 1500,
      rated_voltage: 380,
      rated_current: 4.7,
      rated_speed: 1474,
      rated_torque: 10.0,
      R_th: 0.85,
      C_th: 320,
      T_ambient: 25.0,
      T_warning: 80.0,
      T_trip: 105.0,
      supply_freq: 50.0,
      supply_voltage: 380.0,
    },
  },
  industrial_5_5kw: {
    label: '5.5 kW 4-Pole Industrial Conveyor Motor',
    description: 'Robust medium-frame industrial pump and material handling motor.',
    params: {
      Rs: 0.82,
      Rr: 0.65,
      Ls: 0.095,
      Lr: 0.095,
      Lm: 0.091,
      J: 0.045,
      pole_pairs: 2,
      B: 0.0035,
      base_load_nm: 25.0,
      rated_power: 5500,
      rated_voltage: 400,
      rated_current: 11.2,
      rated_speed: 1460,
      rated_torque: 36.0,
      R_th: 0.42,
      C_th: 650,
      T_ambient: 25.0,
      T_warning: 85.0,
      T_trip: 110.0,
      supply_freq: 50.0,
      supply_voltage: 400.0,
    },
  },
  water_pump_15kw: {
    label: '15 kW 4-Pole Wastewater Booster Pump',
    description: 'Continuous heavy-duty municipal water circulating pump drive.',
    params: {
      Rs: 0.28,
      Rr: 0.22,
      Ls: 0.042,
      Lr: 0.042,
      Lm: 0.0405,
      J: 0.16,
      pole_pairs: 2,
      B: 0.008,
      base_load_nm: 75.0,
      rated_power: 15000,
      rated_voltage: 400,
      rated_current: 29.5,
      rated_speed: 1470,
      rated_torque: 97.4,
      R_th: 0.18,
      C_th: 1450,
      T_ambient: 25.0,
      T_warning: 90.0,
      T_trip: 115.0,
      supply_freq: 50.0,
      supply_voltage: 400.0,
    },
  },
  heavy_compressor_75kw: {
    label: '75 kW 6-Pole Heavy Slurry Compressor',
    description: 'High-torque low-speed 6-pole induction machine for heavy industrial gas compression.',
    params: {
      Rs: 0.075,
      Rr: 0.062,
      Ls: 0.016,
      Lr: 0.016,
      Lm: 0.0155,
      J: 1.85,
      pole_pairs: 3,
      B: 0.045,
      base_load_nm: 480.0,
      rated_power: 75000,
      rated_voltage: 415,
      rated_current: 135.0,
      rated_speed: 980,
      rated_torque: 730.0,
      R_th: 0.055,
      C_th: 4800,
      T_ambient: 30.0,
      T_warning: 95.0,
      T_trip: 120.0,
      supply_freq: 50.0,
      supply_voltage: 415.0,
    },
  },
}

export function MotorParamsStudio({ currentMotor }: MotorParamsStudioProps) {
  const [selectedPreset, setSelectedPreset] = useState<string>('default_1_5kw')
  const [params, setParams] = useState<MotorFullParams>(PRESETS.default_1_5kw.params)
  const [activeTab, setActiveTab] = useState<'circuit' | 'mechanical' | 'nameplate' | 'thermal' | 'grid'>('circuit')
  const [savedStatus, setSavedStatus] = useState<string | null>(null)

  const handlePresetSelect = (presetKey: string) => {
    setSelectedPreset(presetKey)
    setParams(PRESETS[presetKey].params)
    setSavedStatus(`Loaded preset: ${PRESETS[presetKey].label}`)
  }

  const updateParam = (field: keyof MotorFullParams, val: number) => {
    setParams((prev) => ({ ...prev, [field]: val }))
    setSavedStatus(null)
  }

  // Precompute Derived Dynamic Constants (Chen et al. 2025)
  const derived = useMemo(() => {
    const { Rs, Rr, Ls, Lr, Lm, pole_pairs, supply_freq, rated_power, rated_voltage, rated_current } = params

    // Leakage factor sigma = 1 - Lm^2 / (Ls * Lr)
    const sigma = 1 - (Lm * Lm) / (Ls * Lr)
    const isPhysical = Lm < Math.min(Ls, Lr) && sigma > 0

    // Rotor time constant Tr = Lr / Rr
    const Tr = Rr > 0 ? Lr / Rr : 0

    // Damping factor gamma
    const gamma = isPhysical && sigma > 0 && Ls > 0 ? (Rs + (Lm * Lm) / (Lr * Tr)) / (sigma * Ls) : 0

    // Coupling factor K
    const K = isPhysical && sigma > 0 ? Lm / (sigma * Ls * Lr) : 0

    // Synchronous speed
    const nSyncRpm = pole_pairs > 0 ? (60 * supply_freq) / pole_pairs : 1500
    const omegaSyncRad = (nSyncRpm * 2 * Math.PI) / 60

    // Leakage inductances
    const Lls = Ls - Lm
    const Llr = Lr - Lm

    // Power factor estimate
    const apparentPower = Math.sqrt(3) * rated_voltage * rated_current
    const estimatedCosPhi = apparentPower > 0 ? Math.min(0.95, rated_power / (apparentPower * 0.88)) : 0.85

    return {
      sigma,
      Tr,
      gamma,
      K,
      nSyncRpm,
      omegaSyncRad,
      Lls,
      Llr,
      isPhysical,
      estimatedCosPhi,
    }
  }, [params])

  return (
    <div className="grid gap-6">
      {/* Header and Preset Selector */}
      <section className="card p-5 border-[var(--border)] bg-[var(--surface)]">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-[var(--ink-2)]" />
              <h2 className="text-sm font-semibold text-[var(--ink)] uppercase tracking-wider">
                AC Induction Motor Parameters Studio
              </h2>
            </div>
            <p className="text-xs text-[var(--muted)] mt-1">
              Configure full electromagnetic, mechanical, thermal, and nameplate rating parameters for RK4 simulation.
            </p>
          </div>

          {/* Preset Dropdown */}
          <div className="flex items-center gap-2">
            <span className="text-xs num text-[var(--muted)]">Load Preset:</span>
            <select
              className="input py-1 px-3 text-xs num bg-[var(--surface-raised)] border-[var(--border)] text-[var(--ink)]"
              value={selectedPreset}
              onChange={(e) => handlePresetSelect(e.target.value)}
            >
              {Object.entries(PRESETS).map(([key, val]) => (
                <option key={key} value={key}>
                  {val.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        {savedStatus && (
          <div className="mt-3 p-2 rounded-md bg-[var(--surface-raised)] border border-[var(--border)] text-[var(--ink)] text-xs num flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
            <span>{savedStatus}</span>
          </div>
        )}
      </section>

      {/* Main Grid: Parameters Editor & Derived Constants Deck */}
      <div className="grid gap-6 lg:grid-cols-[1.5fr_1fr]">
        {/* Left: Tabbed Parameter Inputs */}
        <section className="card p-5 border-[var(--border)] bg-[var(--surface)] flex flex-col justify-between">
          <div>
            {/* Category Navigation Tabs */}
            <div className="flex flex-wrap gap-1 border-b border-[var(--border)] pb-3 mb-5">
              {[
                { id: 'circuit', label: '1. Equivalent Circuit' },
                { id: 'mechanical', label: '2. Mechanical & Rotor' },
                { id: 'nameplate', label: '3. Nameplate Ratings' },
                { id: 'thermal', label: '4. Thermal Dynamics' },
                { id: 'grid', label: '5. Grid & Supply' },
              ].map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id as typeof activeTab)}
                  className={`text-xs py-1.5 px-3 rounded-md font-medium transition-colors ${
                    activeTab === tab.id
                      ? 'btn-primary font-medium'
                      : 'bg-transparent border-transparent text-[var(--muted)] hover:text-[var(--ink)]'
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            {/* Tab 1: Equivalent Circuit */}
            {activeTab === 'circuit' && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="grid gap-1.5">
                  <label className="text-xs font-medium text-[var(--foreground)] flex justify-between">
                    <span>Stator Resistance (Rs)</span>
                    <span className="font-mono text-cyan-400">Ω</span>
                  </label>
                  <input
                    type="number"
                    step="0.001"
                    className="input font-mono text-sm"
                    value={params.Rs}
                    onChange={(e) => updateParam('Rs', parseFloat(e.target.value) || 0)}
                  />
                  <span className="text-[10px] text-[var(--muted)]">Stator winding phase resistance per phase</span>
                </div>

                <div className="grid gap-1.5">
                  <label className="text-xs font-medium text-[var(--foreground)] flex justify-between">
                    <span>Rotor Resistance (Rr')</span>
                    <span className="font-mono text-cyan-400">Ω</span>
                  </label>
                  <input
                    type="number"
                    step="0.001"
                    className="input font-mono text-sm"
                    value={params.Rr}
                    onChange={(e) => updateParam('Rr', parseFloat(e.target.value) || 0)}
                  />
                  <span className="text-[10px] text-[var(--muted)]">Rotor resistance referred to the stator</span>
                </div>

                <div className="grid gap-1.5">
                  <label className="text-xs font-medium text-[var(--foreground)] flex justify-between">
                    <span>Stator Total Inductance (Ls)</span>
                    <span className="font-mono text-cyan-400">H</span>
                  </label>
                  <input
                    type="number"
                    step="0.0001"
                    className="input font-mono text-sm"
                    value={params.Ls}
                    onChange={(e) => updateParam('Ls', parseFloat(e.target.value) || 0)}
                  />
                  <span className="text-[10px] text-[var(--muted)]">Ls = Lls + Lm (leakage + magnetizing)</span>
                </div>

                <div className="grid gap-1.5">
                  <label className="text-xs font-medium text-[var(--foreground)] flex justify-between">
                    <span>Rotor Total Inductance (Lr')</span>
                    <span className="font-mono text-cyan-400">H</span>
                  </label>
                  <input
                    type="number"
                    step="0.0001"
                    className="input font-mono text-sm"
                    value={params.Lr}
                    onChange={(e) => updateParam('Lr', parseFloat(e.target.value) || 0)}
                  />
                  <span className="text-[10px] text-[var(--muted)]">Lr' = Llr' + Lm referred to stator</span>
                </div>

                <div className="grid gap-1.5 sm:col-span-2">
                  <label className="text-xs font-medium text-[var(--foreground)] flex justify-between">
                    <span>Magnetizing / Mutual Inductance (Lm)</span>
                    <span className="font-mono text-cyan-400">H</span>
                  </label>
                  <input
                    type="number"
                    step="0.0001"
                    className="input font-mono text-sm"
                    value={params.Lm}
                    onChange={(e) => updateParam('Lm', parseFloat(e.target.value) || 0)}
                  />
                  <span className="text-[10px] text-[var(--muted)]">Must satisfy: Lm &lt; min(Ls, Lr) for positive leakage</span>
                </div>
              </div>
            )}

            {/* Tab 2: Mechanical */}
            {activeTab === 'mechanical' && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="grid gap-1.5">
                  <label className="text-xs font-medium text-[var(--foreground)] flex justify-between">
                    <span>Moment of Inertia (J)</span>
                    <span className="font-mono text-cyan-400">kg·m²</span>
                  </label>
                  <input
                    type="number"
                    step="0.001"
                    className="input font-mono text-sm"
                    value={params.J}
                    onChange={(e) => updateParam('J', parseFloat(e.target.value) || 0)}
                  />
                  <span className="text-[10px] text-[var(--muted)]">Rotor + coupled shaft inertia</span>
                </div>

                <div className="grid gap-1.5">
                  <label className="text-xs font-medium text-[var(--foreground)] flex justify-between">
                    <span>Pole Pairs (p)</span>
                    <span className="font-mono text-cyan-400">pairs</span>
                  </label>
                  <select
                    className="input font-mono text-sm"
                    value={params.pole_pairs}
                    onChange={(e) => updateParam('pole_pairs', parseInt(e.target.value, 10))}
                  >
                    <option value={1}>1 (2 poles, 3000 RPM @ 50Hz)</option>
                    <option value={2}>2 (4 poles, 1500 RPM @ 50Hz)</option>
                    <option value={3}>3 (6 poles, 1000 RPM @ 50Hz)</option>
                    <option value={4}>4 (8 poles, 750 RPM @ 50Hz)</option>
                  </select>
                  <span className="text-[10px] text-[var(--muted)]">Determines synchronous speed Nsync = 60f / p</span>
                </div>

                <div className="grid gap-1.5">
                  <label className="text-xs font-medium text-[var(--foreground)] flex justify-between">
                    <span>Friction & Windage Damping (B)</span>
                    <span className="font-mono text-cyan-400">N·m·s/rad</span>
                  </label>
                  <input
                    type="number"
                    step="0.0005"
                    className="input font-mono text-sm"
                    value={params.B}
                    onChange={(e) => updateParam('B', parseFloat(e.target.value) || 0)}
                  />
                  <span className="text-[10px] text-[var(--muted)]">Viscous friction loss constant</span>
                </div>

                <div className="grid gap-1.5">
                  <label className="text-xs font-medium text-[var(--foreground)] flex justify-between">
                    <span>Base Mechanical Load (TL)</span>
                    <span className="font-mono text-cyan-400">N·m</span>
                  </label>
                  <input
                    type="number"
                    step="0.5"
                    className="input font-mono text-sm"
                    value={params.base_load_nm}
                    onChange={(e) => updateParam('base_load_nm', parseFloat(e.target.value) || 0)}
                  />
                  <span className="text-[10px] text-[var(--muted)]">Nominal mechanical load applied to shaft</span>
                </div>
              </div>
            )}

            {/* Tab 3: Nameplate */}
            {activeTab === 'nameplate' && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="grid gap-1.5">
                  <label className="text-xs font-medium text-[var(--foreground)] flex justify-between">
                    <span>Rated Power (Prated)</span>
                    <span className="font-mono text-cyan-400">W</span>
                  </label>
                  <input
                    type="number"
                    step="100"
                    className="input font-mono text-sm"
                    value={params.rated_power}
                    onChange={(e) => updateParam('rated_power', parseFloat(e.target.value) || 0)}
                  />
                  <span className="text-[10px] text-[var(--muted)]">{(params.rated_power / 1000).toFixed(1)} kW nameplate rating</span>
                </div>

                <div className="grid gap-1.5">
                  <label className="text-xs font-medium text-[var(--foreground)] flex justify-between">
                    <span>Rated Voltage (Vrated)</span>
                    <span className="font-mono text-cyan-400">V RMS</span>
                  </label>
                  <input
                    type="number"
                    step="10"
                    className="input font-mono text-sm"
                    value={params.rated_voltage}
                    onChange={(e) => updateParam('rated_voltage', parseFloat(e.target.value) || 0)}
                  />
                  <span className="text-[10px] text-[var(--muted)]">3-phase Line-to-Line RMS voltage</span>
                </div>

                <div className="grid gap-1.5">
                  <label className="text-xs font-medium text-[var(--foreground)] flex justify-between">
                    <span>Rated Current (Irated)</span>
                    <span className="font-mono text-cyan-400">A RMS</span>
                  </label>
                  <input
                    type="number"
                    step="0.1"
                    className="input font-mono text-sm"
                    value={params.rated_current}
                    onChange={(e) => updateParam('rated_current', parseFloat(e.target.value) || 0)}
                  />
                  <span className="text-[10px] text-[var(--muted)]">Nominal full-load phase current draw</span>
                </div>

                <div className="grid gap-1.5">
                  <label className="text-xs font-medium text-[var(--foreground)] flex justify-between">
                    <span>Rated Speed (Nrated)</span>
                    <span className="font-mono text-cyan-400">RPM</span>
                  </label>
                  <input
                    type="number"
                    step="5"
                    className="input font-mono text-sm"
                    value={params.rated_speed}
                    onChange={(e) => updateParam('rated_speed', parseFloat(e.target.value) || 0)}
                  />
                  <span className="text-[10px] text-[var(--muted)]">Full-load operating speed</span>
                </div>
              </div>
            )}

            {/* Tab 4: Thermal */}
            {activeTab === 'thermal' && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="grid gap-1.5">
                  <label className="text-xs font-medium text-[var(--foreground)] flex justify-between">
                    <span>Thermal Resistance (Rth)</span>
                    <span className="font-mono text-cyan-400">K/W</span>
                  </label>
                  <input
                    type="number"
                    step="0.01"
                    className="input font-mono text-sm"
                    value={params.R_th}
                    onChange={(e) => updateParam('R_th', parseFloat(e.target.value) || 0)}
                  />
                  <span className="text-[10px] text-[var(--muted)]">Housing-to-ambient thermal resistance</span>
                </div>

                <div className="grid gap-1.5">
                  <label className="text-xs font-medium text-[var(--foreground)] flex justify-between">
                    <span>Thermal Capacitance (Cth)</span>
                    <span className="font-mono text-cyan-400">J/K</span>
                  </label>
                  <input
                    type="number"
                    step="10"
                    className="input font-mono text-sm"
                    value={params.C_th}
                    onChange={(e) => updateParam('C_th', parseFloat(e.target.value) || 0)}
                  />
                  <span className="text-[10px] text-[var(--muted)]">Thermal inertia of copper + iron mass</span>
                </div>

                <div className="grid gap-1.5">
                  <label className="text-xs font-medium text-[var(--foreground)] flex justify-between">
                    <span>Ambient Temperature</span>
                    <span className="font-mono text-cyan-400">°C</span>
                  </label>
                  <input
                    type="number"
                    step="1"
                    className="input font-mono text-sm"
                    value={params.T_ambient}
                    onChange={(e) => updateParam('T_ambient', parseFloat(e.target.value) || 0)}
                  />
                  <span className="text-[10px] text-[var(--muted)]">Environmental baseline temperature</span>
                </div>

                <div className="grid gap-1.5">
                  <label className="text-xs font-medium text-[var(--foreground)] flex justify-between">
                    <span>Trip Interlock Threshold</span>
                    <span className="font-mono text-rose-400">°C</span>
                  </label>
                  <input
                    type="number"
                    step="1"
                    className="input font-mono text-sm"
                    value={params.T_trip}
                    onChange={(e) => updateParam('T_trip', parseFloat(e.target.value) || 0)}
                  />
                  <span className="text-[10px] text-[var(--muted)]">SADA emergency trip threshold</span>
                </div>
              </div>
            )}

            {/* Tab 5: Grid & Supply */}
            {activeTab === 'grid' && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="grid gap-1.5">
                  <label className="text-xs font-medium text-[var(--foreground)] flex justify-between">
                    <span>Supply Frequency (f)</span>
                    <span className="font-mono text-cyan-400">Hz</span>
                  </label>
                  <input
                    type="number"
                    step="1"
                    className="input font-mono text-sm"
                    value={params.supply_freq}
                    onChange={(e) => updateParam('supply_freq', parseFloat(e.target.value) || 0)}
                  />
                  <span className="text-[10px] text-[var(--muted)]">Grid fundamental frequency (50 Hz / 60 Hz)</span>
                </div>

                <div className="grid gap-1.5">
                  <label className="text-xs font-medium text-[var(--foreground)] flex justify-between">
                    <span>Supply Line Voltage</span>
                    <span className="font-mono text-cyan-400">V LL</span>
                  </label>
                  <input
                    type="number"
                    step="5"
                    className="input font-mono text-sm"
                    value={params.supply_voltage}
                    onChange={(e) => updateParam('supply_voltage', parseFloat(e.target.value) || 0)}
                  />
                  <span className="text-[10px] text-[var(--muted)]">Balanced 3-phase grid line-to-line RMS</span>
                </div>
              </div>
            )}
          </div>
        </section>

        {/* Right: Derived State Space Constants & Physical Validation */}
        <section className="card p-5 border-[var(--border)] bg-[var(--surface)] flex flex-col justify-between">
          <div>
            <header className="pb-3 border-b border-[var(--border)] flex items-center justify-between">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">
                Derived State-Space Constants
              </h3>
              <span
                className={`text-[10px] num px-2 py-0.5 rounded font-bold ${
                  derived.isPhysical
                    ? 'bg-emerald-950/60 border border-emerald-500/30 text-emerald-300'
                    : 'bg-rose-950/60 border border-rose-500/30 text-rose-300'
                }`}
              >
                {derived.isPhysical ? 'PHYSICALLY VALID' : 'INVALID LEAKAGE'}
              </span>
            </header>

            <div className="mt-4 grid gap-2.5 text-xs num">
              {/* Total Leakage Factor Sigma */}
              <div className="p-3 rounded-md bg-[var(--surface-raised)] border border-[var(--border)] flex items-center justify-between hover:border-[var(--border-hover)] transition-colors cursor-default">
                <div>
                  <span className="text-[var(--ink)] block text-[11px] font-medium">Total Leakage Factor (σ)</span>
                  <span className="text-[10px] text-[var(--muted)] font-sans">σ = 1 - Lm² / (Ls · Lr)</span>
                </div>
                <span className="text-base font-bold text-[var(--ink)]">{derived.sigma.toFixed(4)}</span>
              </div>

              {/* Rotor Time Constant Tr */}
              <div className="p-3 rounded-md bg-[var(--surface-raised)] border border-[var(--border)] flex items-center justify-between hover:border-[var(--border-hover)] transition-colors cursor-default">
                <div>
                  <span className="text-[var(--ink)] block text-[11px] font-medium">Rotor Time Constant (Tr)</span>
                  <span className="text-[10px] text-[var(--muted)] font-sans">Tr = Lr / Rr</span>
                </div>
                <span className="text-base font-bold text-[var(--ink)]">{(derived.Tr * 1000).toFixed(1)} ms</span>
              </div>

              {/* Damping Factor Gamma */}
              <div className="p-3 rounded-md bg-[var(--surface-raised)] border border-[var(--border)] flex items-center justify-between hover:border-[var(--border-hover)] transition-colors cursor-default">
                <div>
                  <span className="text-[var(--ink)] block text-[11px] font-medium">Damping Factor (γ)</span>
                  <span className="text-[10px] text-[var(--muted)] font-sans">λ in Chen et al. Eq. (3)</span>
                </div>
                <span className="text-base font-bold text-[var(--ink)]">{derived.gamma.toFixed(2)}</span>
              </div>

              {/* Coupling Factor K */}
              <div className="p-3 rounded-md bg-[var(--surface-raised)] border border-[var(--border)] flex items-center justify-between hover:border-[var(--border-hover)] transition-colors cursor-default">
                <div>
                  <span className="text-[var(--ink)] block text-[11px] font-medium">Flux-Current Coupling (K)</span>
                  <span className="text-[10px] text-[var(--muted)] font-sans">K = Lm / (σ · Ls · Lr)</span>
                </div>
                <span className="text-base font-bold text-[var(--ink)]">{derived.K.toFixed(1)}</span>
              </div>

              {/* Synchronous Speed */}
              <div className="p-3 rounded-md bg-[var(--surface-raised)] border border-[var(--border)] flex items-center justify-between hover:border-[var(--border-hover)] transition-colors cursor-default">
                <div>
                  <span className="text-[var(--ink)] block text-[11px] font-medium">Synchronous Speed (Nsync)</span>
                  <span className="text-[10px] text-[var(--muted)] font-sans">Nsync = 60 · f / p</span>
                </div>
                <span className="text-base font-bold text-[var(--ink)]">{derived.nSyncRpm.toFixed(0)} RPM</span>
              </div>

              {/* Leakage Inductances */}
              <div className="p-3 rounded-md bg-[var(--surface-raised)] border border-[var(--border)] flex items-center justify-between hover:border-[var(--border-hover)] transition-colors cursor-default">
                <div>
                  <span className="text-[var(--ink)] block text-[11px] font-medium">Stator / Rotor Leakage</span>
                  <span className="text-[10px] text-[var(--muted)] font-sans">Lls = Ls - Lm</span>
                </div>
                <span className="text-xs font-bold text-[var(--ink)]">
                  {(derived.Lls * 1000).toFixed(2)} mH / {(derived.Llr * 1000).toFixed(2)} mH
                </span>
              </div>
            </div>
          </div>

          {/* Active Motor Association Info */}
          <div className="mt-5 pt-3 border-t border-[var(--border)] text-xs text-[var(--muted)]">
            <span className="font-semibold text-[var(--ink)] block mb-1">
              Active Motor Target: {currentMotor ? currentMotor.name : 'Default Twin Instance'}
            </span>
            <p className="text-[11px] text-[var(--muted)]">
              Parameters are ready for RK4 state integration and healthy twin observer current-residual computation.
            </p>
          </div>
        </section>
      </div>
    </div>
  )
}
