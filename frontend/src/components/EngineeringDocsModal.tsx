import { useState, useEffect } from 'react'
import { createPortal } from 'react-dom'
import {
  X,
  BookOpen,
  Atom,
  Activity,
  Layers,
  ExternalLink,
  Cpu,
  ShieldAlert,
  Thermometer,
  Zap,
  Waves,
  ChevronLeft,
  ChevronRight,
  Github,
  Radio,
} from 'lucide-react'

export interface EngineeringDocsModalProps {
  isOpen: boolean
  onClose: () => void
}

export type ChapterKey =
  | 'physics'
  | 'faults'
  | 'sensors'
  | 'detection'
  | 'mcsa-thermal'
  | 'architecture'
  | 'papers'

interface Chapter {
  key: ChapterKey
  title: string
  shortTitle: string
  subtitle: string
  icon: typeof Atom
}

const CHAPTERS: Chapter[] = [
  {
    key: 'physics',
    title: '1. Software Stack & State-Space Physics Simulation',
    shortTitle: '1. State-Space Physics',
    subtitle: 'Scientific libraries used & continuous electromechanical state-space model in Clarke (α-β) and Park (d-q) frames',
    icon: Atom,
  },
  {
    key: 'faults',
    title: '2. Mathematical Fault Injection Mechanisms',
    shortTitle: '2. Mathematical Faults',
    subtitle: 'ITSC circulating matrices, BRB resistance asymmetry, eccentricity, and bearing kinematics',
    icon: ShieldAlert,
  },
  {
    key: 'sensors',
    title: '3. Sensor Simulation & First-Principles Physics',
    shortTitle: '3. Sensor Simulation',
    subtitle: 'How 3-phase currents, voltages, speed, tri-axial vibration, and acoustics are synthesized',
    icon: Radio,
  },
  {
    key: 'detection',
    title: '4. Multi-Modal Fault Detection & In-Depth Physics',
    shortTitle: '4. Fault Detection',
    subtitle: 'Digital twin current residual, CWT, Conv-BiLSTM classifier, weighted fusion, and SADA FSM',
    icon: Activity,
  },
  {
    key: 'mcsa-thermal',
    title: '5. MCSA & 4-Node LPTN Thermal Network',
    shortTitle: '5. MCSA & Thermal',
    subtitle: 'High-frequency spectral analysis (Welch PSD), 4-Node LPTN, and Arrhenius/ISO 281 RUL',
    icon: Thermometer,
  },
  {
    key: 'architecture',
    title: '6. System Architecture & Real-Time Data Flow',
    shortTitle: '6. System Architecture',
    subtitle: 'End-to-end telemetry pipeline, dual ingestion modes, asynchronous workers, and persistence',
    icon: Layers,
  },
  {
    key: 'papers',
    title: '7. Canonical Research Papers & Standards',
    shortTitle: '7. Research Papers & Standards',
    subtitle: 'Peer-reviewed academic citations, IEEE/ISO standards, and project credits',
    icon: ExternalLink,
  },
]

export function EngineeringDocsModal({ isOpen, onClose }: EngineeringDocsModalProps) {
  const [activeChapterIndex, setActiveChapterIndex] = useState<number>(0)

  // Escape key listener, left/right arrow page turn listener, & body scroll lock
  useEffect(() => {
    if (!isOpen) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
      } else if (e.key === 'ArrowRight' || e.key === 'PageDown') {
        setActiveChapterIndex((prev) => Math.min(CHAPTERS.length - 1, prev + 1))
      } else if (e.key === 'ArrowLeft' || e.key === 'PageUp') {
        setActiveChapterIndex((prev) => Math.max(0, prev - 1))
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = prevOverflow
    }
  }, [isOpen, onClose])

  if (!isOpen) return null

  const currentChapter = CHAPTERS[activeChapterIndex]
  const isFirstPage = activeChapterIndex === 0
  const isLastPage = activeChapterIndex === CHAPTERS.length - 1

  const goToPrev = () => setActiveChapterIndex((prev) => Math.max(0, prev - 1))
  const goToNext = () => setActiveChapterIndex((prev) => Math.min(CHAPTERS.length - 1, prev + 1))

  return createPortal(
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="modal-dialog glass-card docs-modal-dialog"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="docs-modal-title"
      >
        {/* Book Spine Accent Line */}
        <div className="book-spine-accent" />

        {/* Book Header */}
        <header className="modal-header" style={{ padding: '16px 24px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div
              style={{
                width: 38,
                height: 38,
                borderRadius: '50%',
                background: 'rgba(0, 229, 255, 0.12)',
                border: '1.5px solid var(--accent)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--accent)',
                boxShadow: '0 0 12px rgba(0, 229, 255, 0.25)',
                flexShrink: 0,
              }}
            >
              <BookOpen size={18} strokeWidth={2.2} />
            </div>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span className="eyebrow" style={{ color: 'var(--accent)' }}>ENGINEERING HANDBOOK</span>
                <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-neutral-800 text-neutral-300 border border-neutral-700">
                  Chapter {activeChapterIndex + 1} of {CHAPTERS.length}
                </span>
              </div>
              <h2 id="docs-modal-title" className="fleet-title" style={{ fontSize: '1.25rem', marginTop: 1 }}>
                AC Induction Motor Digital Twin Documentation
              </h2>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {/* Quick Page Turn Controls */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <button
                type="button"
                className="book-turn-btn"
                style={{ padding: '6px 10px', fontSize: 11 }}
                onClick={goToPrev}
                disabled={isFirstPage}
                title="Turn to previous chapter (Left Arrow)"
              >
                <ChevronLeft size={14} />
                <span>Prev</span>
              </button>
              <button
                type="button"
                className="book-turn-btn"
                style={{ padding: '6px 10px', fontSize: 11 }}
                onClick={goToNext}
                disabled={isLastPage}
                title="Turn to next chapter (Right Arrow)"
              >
                <span>Next</span>
                <ChevronRight size={14} />
              </button>
            </div>

            <button
              type="button"
              className="nav-icon-btn"
              onClick={onClose}
              aria-label="Close documentation dialog"
              title="Close dialog (Escape)"
            >
              <X size={18} />
            </button>
          </div>
        </header>

        {/* Book Ribbon Navigation Bar */}
        <nav className="book-nav-ribbon" aria-label="Book Chapters">
          {CHAPTERS.map((ch, idx) => {
            const Icon = ch.icon
            const isActive = idx === activeChapterIndex
            return (
              <button
                key={ch.key}
                type="button"
                className={`book-tab-pill ${isActive ? 'is-active' : ''}`}
                onClick={() => setActiveChapterIndex(idx)}
              >
                <Icon size={14} />
                <span>{ch.shortTitle}</span>
              </button>
            )
          })}
        </nav>

        {/* Scrollable Book Page Content */}
        <div className="modal-body book-page-body" style={{ padding: '24px 30px', gap: 20 }}>

          {/* ========================================================================= */}
          {/* CHAPTER 1: SOFTWARE STACK & STATE-SPACE SIMULATION */}
          {/* ========================================================================= */}
          {currentChapter.key === 'physics' && (
            <div className="space-y-6">
              {/* Executive Overview */}
              <section className="card" style={{ padding: '22px 26px', borderLeft: '3px solid var(--accent)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                  <BookOpen size={22} style={{ color: 'var(--accent)' }} />
                  <h3 style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--ink)' }}>
                    Executive Handbook: The AC Induction Motor Digital Twin
                  </h3>
                </div>
                <p style={{ fontSize: 13.5, lineHeight: 1.65, color: 'var(--ink-2)' }}>
                  This engineering handbook provides a rigorous, physics-grounded explanation of the mathematical models,
                  sensor synthesis pipelines, real-time diagnostic algorithms, and supervisory interlocks governing this
                  industrial digital twin. It explains how high-frequency multi-modal sensors isolate machine degradation
                  from grid fluctuations, how continuous differential equations simulate motor dynamics, and how safety
                  interlocks prevent catastrophic motor burnout.
                </p>
              </section>

              {/* What is Used in the Program (Software Stack) */}
              <section className="card" style={{ padding: '20px 24px' }}>
                <h4 style={{ fontSize: 15, fontWeight: 700, color: 'var(--ink)', marginBottom: 14 }}>
                  Technology Stack &amp; Scientific Libraries
                </h4>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 14 }}>
                  <div style={{ padding: 14, borderRadius: 8, background: 'var(--surface-raised)', border: '1px solid var(--border)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--accent)', fontWeight: 600, fontSize: 13 }}>
                      <Cpu size={16} />
                      <span>scipy.integrate.solve_ivp (RK45)</span>
                    </div>
                    <p style={{ fontSize: 12, color: 'var(--ink-2)', marginTop: 6, lineHeight: 1.5 }}>
                      Adaptive Dormand-Prince Runge-Kutta 5(4) solver numerically integrating the non-linear 5-state electromechanical
                      differential equations at sub-millisecond precision.
                    </p>
                  </div>

                  <div style={{ padding: 14, borderRadius: 8, background: 'var(--surface-raised)', border: '1px solid var(--border)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#10b981', fontWeight: 600, fontSize: 13 }}>
                      <Waves size={16} />
                      <span>scipy.signal &amp; PyWavelets</span>
                    </div>
                    <p style={{ fontSize: 12, color: 'var(--ink-2)', marginTop: 6, lineHeight: 1.5 }}>
                      Computes windowed Welch Power Spectral Density (PSD) for Motor Current Signature Analysis (MCSA) and Continuous
                      Wavelet Transform (CWT) Morlet scalograms for vibration feature extraction.
                    </p>
                  </div>

                  <div style={{ padding: 14, borderRadius: 8, background: 'var(--surface-raised)', border: '1px solid var(--border)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#f59e0b', fontWeight: 600, fontSize: 13 }}>
                      <Layers size={16} />
                      <span>PyTorch (Optional Conv-BiLSTM)</span>
                    </div>
                    <p style={{ fontSize: 12, color: 'var(--ink-2)', marginTop: 6, lineHeight: 1.5 }}>
                      Deep learning classifier with 1D convolutions and Bidirectional LSTM layers classifying 28 time-frequency features,
                      with automatic fallback to rule-based envelope order analysis.
                    </p>
                  </div>

                  <div style={{ padding: 14, borderRadius: 8, background: 'var(--surface-raised)', border: '1px solid var(--border)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#a855f7', fontWeight: 600, fontSize: 13 }}>
                      <Zap size={16} />
                      <span>FastAPI, Redis &amp; MySQL 8.4</span>
                    </div>
                    <p style={{ fontSize: 12, color: 'var(--ink-2)', marginTop: 6, lineHeight: 1.5 }}>
                      Asynchronous multi-process worker runtime streaming 10 Hz WebSocket telemetry frames, backed by Redis in-memory
                      Pub/Sub and batched MySQL relational persistence.
                    </p>
                  </div>
                </div>
              </section>

              {/* Continuous Electromechanical State-Space Model */}
              <section className="card" style={{ padding: '20px 24px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                  <Atom size={20} style={{ color: 'var(--accent)' }} />
                  <h3 style={{ fontSize: '1.15rem', fontWeight: 700, color: 'var(--ink)' }}>
                    Continuous Electromechanical State-Space Model
                  </h3>
                </div>
                <p style={{ fontSize: 13, lineHeight: 1.6, color: 'var(--ink-2)' }}>
                  The induction machine simulation engine executes numerical integration over the continuous-time
                  nonlinear differential equations of the squirrel-cage induction machine in orthogonal stationary
                  Clarke coordinates (α-β) and synchronous Park coordinates (d-q) using the adaptive Runge-Kutta 4th/5th order method (<strong>RK45 Dormand-Prince</strong> via <code>scipy.integrate.solve_ivp</code>).
                </p>

                <div
                  style={{
                    margin: '16px 0',
                    padding: '14px 18px',
                    borderRadius: 8,
                    background: 'var(--surface-raised)',
                    border: '1px solid var(--border)',
                    fontFamily: 'monospace',
                    fontSize: 13,
                    color: 'var(--accent)',
                    lineHeight: 1.7,
                  }}
                >
                  <div style={{ color: 'var(--muted)', fontSize: 11, marginBottom: 4, textTransform: 'uppercase' }}>State Vector Definition:</div>
                  x = [ i_sα, i_sβ, ψ_rα, ψ_rβ, ω_m, θ_m ]ᵀ
                  <div style={{ fontSize: 12, color: 'var(--ink-2)', marginTop: 4 }}>
                    • i_sα, i_sβ: Stator current components in stationary frame [A]<br />
                    • ψ_rα, ψ_rβ: Rotor flux linkages [Wb]<br />
                    • ω_m: Mechanical rotor shaft angular velocity [rad/s]<br />
                    • θ_m: Mechanical shaft angular position [rad]
                  </div>
                </div>

                <h4 style={{ fontSize: 14, fontWeight: 700, color: 'var(--ink)', marginTop: 18, marginBottom: 8 }}>
                  1. Governing Electromagnetic Differential Equations
                </h4>
                <div
                  style={{
                    padding: '16px',
                    borderRadius: 8,
                    background: 'var(--surface-raised)',
                    border: '1px solid var(--border)',
                    fontFamily: 'monospace',
                    fontSize: 12.5,
                    lineHeight: 1.8,
                    color: 'var(--ink)',
                  }}
                >
                  <div><strong>Stator Current Dynamics:</strong></div>
                  <div>d(i_sα)/dt = [ v_sα - R_s·i_sα - (L_m / L_r)·d(ψ_rα)/dt ] / (σ·L_s)</div>
                  <div>d(i_sβ)/dt = [ v_sβ - R_s·i_sβ - (L_m / L_r)·d(ψ_rβ)/dt ] / (σ·L_s)</div>
                  <div style={{ color: 'var(--muted)', fontSize: 11, marginTop: 4 }}>
                    where total leakage factor σ = 1 - L_m² / (L_s·L_r)
                  </div>
                  <div style={{ marginTop: 10 }}><strong>Rotor Flux Dynamics:</strong></div>
                  <div>d(ψ_rα)/dt = -R_r·i_rα - ω_r·ψ_rβ</div>
                  <div>d(ψ_rβ)/dt = -R_r·i_rβ + ω_r·ψ_rα</div>
                  <div style={{ color: 'var(--muted)', fontSize: 11, marginTop: 4 }}>
                    where electrical rotor frequency ω_r = p·ω_m, and rotor currents i_r = (ψ_r - L_m·i_s) / L_r
                  </div>
                </div>

                <h4 style={{ fontSize: 14, fontWeight: 700, color: 'var(--ink)', marginTop: 18, marginBottom: 8 }}>
                  2. Electromechanical Torque &amp; Shaft Mechanics
                </h4>
                <div
                  style={{
                    padding: '16px',
                    borderRadius: 8,
                    background: 'var(--surface-raised)',
                    border: '1px solid var(--border)',
                    fontFamily: 'monospace',
                    fontSize: 12.5,
                    lineHeight: 1.8,
                    color: 'var(--ink)',
                  }}
                >
                  <div><strong>Air-Gap Electromagnetic Torque (T_e):</strong></div>
                  <div>T_e = (3/2) · p · (L_m / L_r) · ( ψ_rα·i_sβ - ψ_rβ·i_sα )</div>
                  <div style={{ marginTop: 10 }}><strong>Rotor Shaft Acceleration (Newton's 2nd Law for Rotation):</strong></div>
                  <div>d(ω_m)/dt = ( T_e - T_L - B·ω_m ) / J</div>
                  <div>d(θ_m)/dt = ω_m</div>
                  <div style={{ color: 'var(--muted)', fontSize: 11, marginTop: 4 }}>
                    • p: Stator pole pairs (p = 2 for 4-pole machine)<br />
                    • T_L: Applied mechanical load torque [N·m]<br />
                    • J: Rotor shaft and load moment of inertia [kg·m²]<br />
                    • B: Viscous friction damping coefficient [N·m·s/rad]
                  </div>
                </div>

                <h4 style={{ fontSize: 14, fontWeight: 700, color: 'var(--ink)', marginTop: 18, marginBottom: 8 }}>
                  3. Pre-Computed Physical Machine Parameters
                </h4>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: 10, marginTop: 8 }}>
                  <div style={{ padding: '10px 14px', borderRadius: 6, background: 'var(--surface-raised)', border: '1px solid var(--border)' }}>
                    <div style={{ fontSize: 11, color: 'var(--muted)' }}>Total Leakage Factor (σ)</div>
                    <div style={{ fontSize: 13, fontFamily: 'monospace', color: 'var(--accent)', marginTop: 2 }}>σ = 1 - L_m² / (L_s · L_r)</div>
                  </div>
                  <div style={{ padding: '10px 14px', borderRadius: 6, background: 'var(--surface-raised)', border: '1px solid var(--border)' }}>
                    <div style={{ fontSize: 11, color: 'var(--muted)' }}>Rotor Time Constant (T_r)</div>
                    <div style={{ fontSize: 13, fontFamily: 'monospace', color: 'var(--accent)', marginTop: 2 }}>T_r = L_r / R_r [s]</div>
                  </div>
                  <div style={{ padding: '10px 14px', borderRadius: 6, background: 'var(--surface-raised)', border: '1px solid var(--border)' }}>
                    <div style={{ fontSize: 11, color: 'var(--muted)' }}>Stator Damping (γ)</div>
                    <div style={{ fontSize: 13, fontFamily: 'monospace', color: 'var(--accent)', marginTop: 2 }}>γ = (R_s + L_m²/(L_r·T_r)) / (σ·L_s)</div>
                  </div>
                  <div style={{ padding: '10px 14px', borderRadius: 6, background: 'var(--surface-raised)', border: '1px solid var(--border)' }}>
                    <div style={{ fontSize: 11, color: 'var(--muted)' }}>Flux Coupling Factor (K)</div>
                    <div style={{ fontSize: 13, fontFamily: 'monospace', color: 'var(--accent)', marginTop: 2 }}>K = L_m / (σ · L_s · L_r)</div>
                  </div>
                </div>
              </section>
            </div>
          )}

          {/* ========================================================================= */}
          {/* CHAPTER 2: MATHEMATICAL FAULT INJECTIONS */}
          {/* ========================================================================= */}
          {currentChapter.key === 'faults' && (
            <div className="space-y-6">
              <section className="card" style={{ padding: '20px 24px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                  <ShieldAlert size={20} style={{ color: 'var(--warning)' }} />
                  <h3 style={{ fontSize: '1.15rem', fontWeight: 700, color: 'var(--ink)' }}>
                    Mathematical Fault Injection Models
                  </h3>
                </div>
                <p style={{ fontSize: 13, lineHeight: 1.6, color: 'var(--ink-2)' }}>
                  Unlike basic mock applications that apply synthetic offsets, this digital twin implements true physical parameter
                  degradations in the continuous state equations.
                </p>

                {/* ITSC */}
                <div style={{ marginTop: 18, borderTop: '1px solid var(--border-subtle)', paddingTop: 16 }}>
                  <h4 style={{ fontSize: 14, fontWeight: 700, color: 'var(--ink)', marginBottom: 6 }}>
                    1. Stator Inter-turn Short Circuit (ITSC)
                  </h4>
                  <p style={{ fontSize: 12.5, lineHeight: 1.6, color: 'var(--ink-2)' }}>
                    A shorted turn ratio μ = N<sub>sc</sub> / N<sub>s</sub> is injected into Phase A. This establishes an isolated,
                    low-resistance circulating current loop governed by:
                  </p>
                  <div style={{ padding: '12px 16px', background: 'var(--surface-raised)', borderRadius: 6, border: '1px solid var(--border)', fontFamily: 'monospace', fontSize: 12.5, margin: '8px 0', color: 'var(--accent)' }}>
                    v_s = R_s · i_s + d(ψ_s)/dt<br />
                    i_f = (μ · v_sa) / [ R_f + μ · R_s ]<br />
                    P_fault = R_f · i_f² [W]
                  </div>
                  <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>
                    • Generates intense localized heat dissipated directly into Stator Winding node (T_w).<br />
                    • Induces negative-sequence current imbalance observable in symmetrical component analysis.
                  </p>
                </div>

                {/* BRB */}
                <div style={{ marginTop: 18, borderTop: '1px solid var(--border-subtle)', paddingTop: 16 }}>
                  <h4 style={{ fontSize: 14, fontWeight: 700, color: 'var(--ink)', marginBottom: 6 }}>
                    2. Broken Rotor Bars (BRB)
                  </h4>
                  <p style={{ fontSize: 12.5, lineHeight: 1.6, color: 'var(--ink-2)' }}>
                    Rotor bar fractures break rotor cage circumferential symmetry. In the rotating reference frame, rotor resistance
                    becomes an anisotropic tensor modulated by rotor electrical angle θ_r:
                  </p>
                  <div style={{ padding: '12px 16px', background: 'var(--surface-raised)', borderRadius: 6, border: '1px solid var(--border)', fontFamily: 'monospace', fontSize: 12.5, margin: '8px 0', color: 'var(--accent)' }}>
                    R_r(θ_r) = R_r0 · [ 1 + δ_brb · cos(2θ_r) ]<br />
                    f_brb = f_s · ( 1 ± 2k·s ),   k ∈ &#123;1, 2, 3&#125;
                  </div>
                  <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>
                    • Backward magnetic field produces sidebands at (1 ± 2s)f_s around the fundamental frequency.<br />
                    • Generates shaft speed and torque oscillations at 2s·f_s (double slip frequency).
                  </p>
                </div>

                {/* Eccentricity */}
                <div style={{ marginTop: 18, borderTop: '1px solid var(--border-subtle)', paddingTop: 16 }}>
                  <h4 style={{ fontSize: 14, fontWeight: 700, color: 'var(--ink)', marginBottom: 6 }}>
                    3. Dynamic Air-Gap Eccentricity
                  </h4>
                  <p style={{ fontSize: 12.5, lineHeight: 1.6, color: 'var(--ink-2)' }}>
                    When the rotor shaft center of rotation does not coincide with the stator bore axis, non-uniform air-gap permeance
                    modulates the mutual magnetizing inductance as a function of mechanical angle:
                  </p>
                  <div style={{ padding: '12px 16px', background: 'var(--surface-raised)', borderRadius: 6, border: '1px solid var(--border)', fontFamily: 'monospace', fontSize: 12.5, margin: '8px 0', color: 'var(--accent)' }}>
                    L_m(θ_m) = L_m0 · [ 1 + δ_ecc · cos(θ_m) ]<br />
                    f_ecc = f_s ± k · f_r,   f_r = n_rpm / 60
                  </div>
                  <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>
                    • Produces rotational sidebands at f_s ± f_r in stator current spectrum and radial 1x vibration forces.
                  </p>
                </div>

                {/* Bearing Kinematics */}
                <div style={{ marginTop: 18, borderTop: '1px solid var(--border-subtle)', paddingTop: 16 }}>
                  <h4 style={{ fontSize: 14, fontWeight: 700, color: 'var(--ink)', marginBottom: 6 }}>
                    4. Rolling Element Bearing Defect Kinematics
                  </h4>
                  <p style={{ fontSize: 12.5, lineHeight: 1.6, color: 'var(--ink-2)' }}>
                    Defects on bearing components create periodic structural impacts calculated from bearing pitch diameter D,
                    ball diameter d, number of rolling elements N_b, and contact angle β:
                  </p>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: 10, marginTop: 10 }}>
                    <div style={{ padding: '10px 14px', borderRadius: 6, background: 'var(--surface-raised)', border: '1px solid var(--border)' }}>
                      <div style={{ fontSize: 11, color: 'var(--muted)' }}>BPFO (Outer Race)</div>
                      <div style={{ fontSize: 12, fontFamily: 'monospace', color: 'var(--accent)', marginTop: 2 }}>
                        (N_b / 2) · f_r · [ 1 - (d/D)·cos β ]
                      </div>
                    </div>
                    <div style={{ padding: '10px 14px', borderRadius: 6, background: 'var(--surface-raised)', border: '1px solid var(--border)' }}>
                      <div style={{ fontSize: 11, color: 'var(--muted)' }}>BPFI (Inner Race)</div>
                      <div style={{ fontSize: 12, fontFamily: 'monospace', color: 'var(--accent)', marginTop: 2 }}>
                        (N_b / 2) · f_r · [ 1 + (d/D)·cos β ]
                      </div>
                    </div>
                    <div style={{ padding: '10px 14px', borderRadius: 6, background: 'var(--surface-raised)', border: '1px solid var(--border)' }}>
                      <div style={{ fontSize: 11, color: 'var(--muted)' }}>BSF (Ball Spin)</div>
                      <div style={{ fontSize: 12, fontFamily: 'monospace', color: 'var(--accent)', marginTop: 2 }}>
                        (D / 2d) · f_r · [ 1 - (d/D)²·cos² β ]
                      </div>
                    </div>
                    <div style={{ padding: '10px 14px', borderRadius: 6, background: 'var(--surface-raised)', border: '1px solid var(--border)' }}>
                      <div style={{ fontSize: 11, color: 'var(--muted)' }}>FTF (Cage / Train)</div>
                      <div style={{ fontSize: 12, fontFamily: 'monospace', color: 'var(--accent)', marginTop: 2 }}>
                        (1 / 2) · f_r · [ 1 - (d/D)·cos β ]
                      </div>
                    </div>
                  </div>
                </div>
              </section>
            </div>
          )}

          {/* ========================================================================= */}
          {/* CHAPTER 3: HOW SENSORS ARE SIMULATED (PHYSICS & SYNTHESIS) */}
          {/* ========================================================================= */}
          {currentChapter.key === 'sensors' && (
            <div className="space-y-6">
              <section className="card" style={{ padding: '20px 24px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                  <Radio size={20} style={{ color: 'var(--accent)' }} />
                  <h3 style={{ fontSize: '1.15rem', fontWeight: 700, color: 'var(--ink)' }}>
                    How Sensor Values are Simulated: First-Principles Signal Synthesis
                  </h3>
                </div>
                <p style={{ fontSize: 13, lineHeight: 1.6, color: 'var(--ink-2)' }}>
                  Rather than outputting naive arbitrary numbers, every simulated telemetry channel in this digital twin
                  is mathematically synthesized from the internal electromechanical state variables of the motor,
                  transduced according to real physical sensor dynamics, noise floors, and quantization properties.
                </p>

                {/* 1. Current Sensors */}
                <div style={{ marginTop: 18, borderTop: '1px solid var(--border-subtle)', paddingTop: 16 }}>
                  <h4 style={{ fontSize: 14, fontWeight: 700, color: 'var(--ink)', marginBottom: 6 }}>
                    1. Three-Phase Stator Current Channels (IA, IB, IC)
                  </h4>
                  <p style={{ fontSize: 12.5, lineHeight: 1.6, color: 'var(--ink-2)' }}>
                    State variables i_sα and i_sβ from the RK45 solver are mapped to three-phase instantaneous currents via
                    the Inverse Clarke Transformation, combined with converter switching ripple and transducer noise:
                  </p>
                  <div style={{ padding: '12px 16px', background: 'var(--surface-raised)', borderRadius: 6, border: '1px solid var(--border)', fontFamily: 'monospace', fontSize: 12.5, margin: '8px 0', color: 'var(--accent)' }}>
                    i_a(t) = i_sα(t) + n_a(t)<br />
                    i_b(t) = -0.5 · i_sα(t) + (√3 / 2) · i_sβ(t) + n_b(t)<br />
                    i_c(t) = -0.5 · i_sα(t) - (√3 / 2) · i_sβ(t) + n_c(t)<br />
                    where n(t) ~ 𝒩(0, σ_noise²) represents 16-bit Hall-effect ADC white noise and thermal drift.
                  </div>
                </div>

                {/* 2. Voltage Sensors */}
                <div style={{ marginTop: 18, borderTop: '1px solid var(--border-subtle)', paddingTop: 16 }}>
                  <h4 style={{ fontSize: 14, fontWeight: 700, color: 'var(--ink)', marginBottom: 6 }}>
                    2. Three-Phase Voltage Channels (VA, VB, VC)
                  </h4>
                  <p style={{ fontSize: 12.5, lineHeight: 1.6, color: 'var(--ink-2)' }}>
                    Synthesizes either balanced sinusoidal utility grid voltages or PWM inverter carrier switching patterns,
                    incorporating line impedance drops, voltage unbalance factors, and grid harmonic distortion:
                  </p>
                  <div style={{ padding: '12px 16px', background: 'var(--surface-raised)', borderRadius: 6, border: '1px solid var(--border)', fontFamily: 'monospace', fontSize: 12.5, margin: '8px 0', color: 'var(--accent)' }}>
                    v_a(t) = V_peak · cos(ω_s·t)<br />
                    v_b(t) = V_peak · cos(ω_s·t - 2π/3)<br />
                    v_c(t) = V_peak · cos(ω_s·t + 2π/3)<br />
                    v_measured(t) = v_grid(t) + v_harmonic_5th + v_harmonic_7th + Δv_sag(t)
                  </div>
                </div>

                {/* 3. Tri-axial Vibration */}
                <div style={{ marginTop: 18, borderTop: '1px solid var(--border-subtle)', paddingTop: 16 }}>
                  <h4 style={{ fontSize: 14, fontWeight: 700, color: 'var(--ink)', marginBottom: 6 }}>
                    3. Tri-Axial Accelerometer (Vibration x, y, z)
                  </h4>
                  <p style={{ fontSize: 12.5, lineHeight: 1.6, color: 'var(--ink-2)' }}>
                    Accelerations are synthesized along three orthogonal mechanical axes:
                  </p>
                  <div style={{ padding: '12px 16px', background: 'var(--surface-raised)', borderRadius: 6, border: '1px solid var(--border)', fontFamily: 'monospace', fontSize: 12, margin: '8px 0', color: 'var(--accent)', lineHeight: 1.7 }}>
                    • Radial X (Horizontal): Unbalance centrifugal force F = m·r·ω_m²·cos(ω_m·t) at 1x shaft speed.<br />
                    • Radial Y (Vertical Load Zone): Combined shaft dynamics, 2x misalignment, and bearing defect impact trains convolved with structural resonance ring-down: a_y(t) = Σ [ A_i · e^(-ζ·ω_n·t) · sin(ω_n·t) ] · cos(θ_load).<br />
                    • Axial Z (Thrust): Angular misalignment and thrust bearing reaction at 1x and 2x running speed.
                  </div>
                </div>

                {/* 4. Acoustic Sensor */}
                <div style={{ marginTop: 18, borderTop: '1px solid var(--border-subtle)', paddingTop: 16 }}>
                  <h4 style={{ fontSize: 14, fontWeight: 700, color: 'var(--ink)', marginBottom: 6 }}>
                    4. Acoustic Microphone Channel
                  </h4>
                  <p style={{ fontSize: 12.5, lineHeight: 1.6, color: 'var(--ink-2)' }}>
                    Airborne sound pressure waves (in Pascals) are simulated by coupling mechanical housing vibration velocity
                    with stator core magnetostriction hum at double electrical supply frequency (2·f_s = 100 Hz) and broadband
                    cooling fan aerodynamic turbulence:
                  </p>
                  <div style={{ padding: '12px 16px', background: 'var(--surface-raised)', borderRadius: 6, border: '1px solid var(--border)', fontFamily: 'monospace', fontSize: 12.5, margin: '8px 0', color: 'var(--accent)' }}>
                    P_sound(t) = k_vib · v_y(t) + A_magneto · sin(4π·f_s·t) + Noise_fan(ω_m)
                  </div>
                </div>

                {/* 5. Temperature Sensors */}
                <div style={{ marginTop: 18, borderTop: '1px solid var(--border-subtle)', paddingTop: 16 }}>
                  <h4 style={{ fontSize: 14, fontWeight: 700, color: 'var(--ink)', marginBottom: 6 }}>
                    5. Temperature Sensing (RTD / Thermocouple)
                  </h4>
                  <p style={{ fontSize: 12.5, lineHeight: 1.6, color: 'var(--ink-2)' }}>
                    Temperature readings reflect real thermal inertia and heat dissipation computed by the 4-Node Lumped Parameter
                    Thermal Network (LPTN), tracking stator copper winding losses, iron core losses, and bearing friction:
                  </p>
                  <div style={{ padding: '12px 16px', background: 'var(--surface-raised)', borderRadius: 6, border: '1px solid var(--border)', fontFamily: 'monospace', fontSize: 12.5, margin: '8px 0', color: 'var(--accent)' }}>
                    T_sensor(t) = T_winding(t) - ΔT_sensor_lag(τ_rtd) + n_thermal(t)
                  </div>
                </div>
              </section>
            </div>
          )}

          {/* ========================================================================= */}
          {/* CHAPTER 4: HOW FAULTS ARE DETECTED (DIAGNOSTIC PIPELINE) */}
          {/* ========================================================================= */}
          {currentChapter.key === 'detection' && (
            <div className="space-y-6">
              <section className="card" style={{ padding: '20px 24px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                  <Activity size={20} style={{ color: 'var(--accent)' }} />
                  <h3 style={{ fontSize: '1.15rem', fontWeight: 700, color: 'var(--ink)' }}>
                    How Faults are Detected: The Multi-Modal Diagnostic Engine
                  </h3>
                </div>
                <p style={{ fontSize: 13, lineHeight: 1.6, color: 'var(--ink-2)' }}>
                  Fault detection is achieved not through single isolated thresholds, but through a multi-tiered,
                  cross-sensor diagnostic architecture that separates true motor health degradation from supply power anomalies.
                </p>

                {/* 1. Digital Twin Residual Method */}
                <div style={{ marginTop: 18, borderTop: '1px solid var(--border-subtle)', paddingTop: 16 }}>
                  <h4 style={{ fontSize: 14, fontWeight: 700, color: 'var(--ink)', marginBottom: 6 }}>
                    1. The Digital Twin Current Residual Method
                  </h4>
                  <p style={{ fontSize: 12.5, lineHeight: 1.6, color: 'var(--ink-2)' }}>
                    A pristine, healthy reference model of the motor runs continuously in the background, locked to the measured
                    supply voltage and shaft rotational speed:
                  </p>
                  <div style={{ padding: '12px 16px', background: 'var(--surface-raised)', borderRadius: 6, border: '1px solid var(--border)', fontFamily: 'monospace', fontSize: 12.5, margin: '8px 0', color: 'var(--accent)' }}>
                    r_i(t) = i_measured(t) - i_twin(t)<br />
                    J_residual = (1 / T) · ∫ |r_i(t)|² dt &gt; Threshold_fault
                  </div>
                  <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>
                    • Under normal healthy conditions, the residual is near zero: r_i(t) ≈ 0.<br />
                    • When stator shorts or rotor bar defects emerge, r_i(t) spikes immediately, isolating internal machine faults even during supply voltage swings.
                  </p>
                </div>

                {/* 2. MCSA & Welch PSD */}
                <div style={{ marginTop: 18, borderTop: '1px solid var(--border-subtle)', paddingTop: 16 }}>
                  <h4 style={{ fontSize: 14, fontWeight: 700, color: 'var(--ink)', marginBottom: 6 }}>
                    2. MCSA Spectral Welch PSD Peak Detection
                  </h4>
                  <p style={{ fontSize: 12.5, lineHeight: 1.6, color: 'var(--ink-2)' }}>
                    Stator current is sampled at <em>F_s &ge; 5000 Hz</em>, windowed with Flat-top and Hann filters, and transformed via
                    Welch Power Spectral Density. Automated peak detectors locate characteristic sidebands:
                  </p>
                  <div style={{ padding: '12px 16px', background: 'var(--surface-raised)', borderRadius: 6, border: '1px solid var(--border)', fontFamily: 'monospace', fontSize: 12.5, margin: '8px 0', color: 'var(--accent)' }}>
                    f_sideband = f_s · ( 1 ± 2k·s ),   k ∈ &#123;1, 2, 3&#125;<br />
                    Sideband Power Delta &gt; 15 dBc ⇒ Confirmed Broken Rotor Bar (BRB)
                  </div>
                </div>

                {/* 3. Deep Learning Classifier */}
                <div style={{ marginTop: 18, borderTop: '1px solid var(--border-subtle)', paddingTop: 16 }}>
                  <h4 style={{ fontSize: 14, fontWeight: 700, color: 'var(--ink)', marginBottom: 6 }}>
                    3. Deep Learning Mechanical Classifier (Conv-BiLSTM)
                  </h4>
                  <p style={{ fontSize: 12.5, lineHeight: 1.6, color: 'var(--ink-2)' }}>
                    Extracts 28 statistical and spectral features (RMS, Kurtosis, Skewness, Crest Factor, Envelope spectrum)
                    coupled with Continuous Wavelet Transform (CWT) Morlet scalograms. The neural net architecture consists of:
                  </p>
                  <div style={{ padding: '12px 16px', background: 'var(--surface-raised)', borderRadius: 6, border: '1px solid var(--border)', fontFamily: 'monospace', fontSize: 12.5, margin: '8px 0', color: 'var(--accent)' }}>
                    Input Features (28) → Conv1D(32, k=3) → Conv1D(64, k=3) → BiLSTM(64) → Dense(8, Softmax)<br />
                    Outputs: healthy, bearing_outer, bearing_inner, bearing_ball, unbalance, misalignment
                  </div>
                </div>

                {/* 4. Weighted Fusion & SADA FSM */}
                <div style={{ marginTop: 18, borderTop: '1px solid var(--border-subtle)', paddingTop: 16 }}>
                  <h4 style={{ fontSize: 14, fontWeight: 700, color: 'var(--ink)', marginBottom: 6 }}>
                    4. Weighted Decision Fusion &amp; SADA Supervisory Controller
                  </h4>
                  <p style={{ fontSize: 12.5, lineHeight: 1.6, color: 'var(--ink-2)' }}>
                    Individual channel scores are fused using frozen Schema v1.0 weights, calculating the Motor Health Index (MHI):
                  </p>
                  <div style={{ padding: '12px 16px', background: 'var(--surface-raised)', borderRadius: 6, border: '1px solid var(--border)', fontFamily: 'monospace', fontSize: 12.5, margin: '8px 0', color: 'var(--accent)' }}>
                    MHI = 100 - [ 0.35·S_elec + 0.35·S_mech + 0.15·S_therm + 0.15·S_supply ] · 100<br />
                    MHI &ge; 85: Zone A (Good) | 70-84: Zone B (Satisfactory) | 50-69: Zone C (Warning) | &lt;50: Zone D (Critical)
                  </div>
                  <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>
                    • SADA FSM: Filters noise with EMA smoothing (α=0.25). On sustained severity, transitions NORMAL → WATCH → DERATE (50% load command) → TRIP (latched safety interlock).
                  </p>
                </div>
              </section>
            </div>
          )}

          {/* ========================================================================= */}
          {/* CHAPTER 5: MCSA & 4-NODE LPTN THERMAL NETWORK */}
          {/* ========================================================================= */}
          {currentChapter.key === 'mcsa-thermal' && (
            <div className="space-y-6">
              <section className="card" style={{ padding: '20px 24px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                  <Thermometer size={20} style={{ color: 'var(--accent)' }} />
                  <h3 style={{ fontSize: '1.15rem', fontWeight: 700, color: 'var(--ink)' }}>
                    Motor Current Signature Analysis (MCSA) Pipeline
                  </h3>
                </div>
                <p style={{ fontSize: 13, lineHeight: 1.6, color: 'var(--ink-2)' }}>
                  The MCSA pipeline captures high-frequency steady-state phase current waveforms (<em>F_s &ge; 5000 Hz</em>)
                  and applies flat-top and Hann windowing to suppress spectral leakage before computing the Welch Power Spectral Density:
                </p>

                <div
                  style={{
                    padding: '16px',
                    borderRadius: 8,
                    background: 'var(--surface-raised)',
                    border: '1px solid var(--border)',
                    fontFamily: 'monospace',
                    fontSize: 12.5,
                    lineHeight: 1.8,
                    color: 'var(--ink)',
                    marginTop: 10,
                  }}
                >
                  <div><strong>Welch PSD Averaging:</strong></div>
                  <div>S_xx(f) = (1 / K) · Σ |X_k(f)|²</div>
                  <div style={{ marginTop: 8 }}><strong>Characteristic Fault Sideband Tracking:</strong></div>
                  <div>• Broken Rotor Bar (BRB): f_brb = f_s · (1 ± 2k·s) for k ∈ &#123;1, 2, 3&#125;</div>
                  <div>• Dynamic Eccentricity: f_ecc = f_s ± k · f_r, where f_r = (1 - s) · f_s / p</div>
                  <div>• Harmonic Distortion (THD): Evaluated across 3rd, 5th, and 7th supply harmonics</div>
                </div>

                {/* 4-Node LPTN */}
                <h4 style={{ fontSize: 15, fontWeight: 700, color: 'var(--ink)', marginTop: 22, marginBottom: 8 }}>
                  4-Node Lumped Parameter Thermal Network (LPTN)
                </h4>
                <p style={{ fontSize: 13, lineHeight: 1.6, color: 'var(--ink-2)' }}>
                  Tracks internal thermodynamic heat generation across four coupled thermal nodes:
                  Stator Winding (T_w), Teeth Core (T_t), Rotor Cage (T_r), and Bearings (T_b):
                </p>
                <div
                  style={{
                    padding: '16px',
                    borderRadius: 8,
                    background: 'var(--surface-raised)',
                    border: '1px solid var(--border)',
                    fontFamily: 'monospace',
                    fontSize: 12.5,
                    lineHeight: 1.8,
                    color: 'var(--accent)',
                    marginTop: 10,
                  }}
                >
                  <div>C_w · d(T_w)/dt = P_cu_s + P_itsc - (T_w - T_t) / R_wt</div>
                  <div>C_t · d(T_t)/dt = P_fe_t + (T_w - T_t) / R_wt - (T_t - T_frame) / R_tf</div>
                  <div>C_r · d(T_r)/dt = P_cu_r - (T_r - T_air) / R_ra</div>
                  <div>C_b · d(T_b)/dt = P_fric_bearing - (T_b - T_amb) / R_ba</div>
                </div>

                {/* Arrhenius & ISO 281 Life Models */}
                <h4 style={{ fontSize: 15, fontWeight: 700, color: 'var(--ink)', marginTop: 22, marginBottom: 8 }}>
                  Classical Arrhenius Thermal Insulation Life Model &amp; Bearing ISO 281 L10h
                </h4>
                <div
                  style={{
                    padding: '16px',
                    borderRadius: 8,
                    background: 'var(--surface-raised)',
                    border: '1px solid var(--border)',
                    fontFamily: 'monospace',
                    fontSize: 12.5,
                    lineHeight: 1.8,
                    color: 'var(--ink)',
                  }}
                >
                  <div><strong>Arrhenius Chemical Reaction Kinetics (Winding Insulation):</strong></div>
                  <div>Life = A · exp( E_a / (k_B · T_w) )</div>
                  <div>A_F (Thermal Acceleration Factor) = 2^( (T_w - T_rated) / 10 )</div>
                  <div>RUL_insulation = Nominal_Life / max(A_F, 0.05) [hours]</div>
                  <div style={{ marginTop: 10 }}><strong>ISO 281 L10h Bearing Fatigue Life Model:</strong></div>
                  <div>L_10h = (10⁶ / (60·n)) · (C / P)^p</div>
                  <div style={{ color: 'var(--muted)', fontSize: 11, marginTop: 4 }}>
                    Dynamic load P is adjusted by vibration velocity RMS (ISO 10816) and bearing temperature factors.
                  </div>
                </div>
              </section>
            </div>
          )}

          {/* ========================================================================= */}
          {/* CHAPTER 6: SYSTEM ARCHITECTURE & DUAL INGESTION */}
          {/* ========================================================================= */}
          {currentChapter.key === 'architecture' && (
            <div className="space-y-6">
              <section className="card" style={{ padding: '20px 24px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                  <Layers size={20} style={{ color: 'var(--accent)' }} />
                  <h3 style={{ fontSize: '1.15rem', fontWeight: 700, color: 'var(--ink)' }}>
                    High-Level Software Pipeline Architecture
                  </h3>
                </div>
                <p style={{ fontSize: 13, lineHeight: 1.6, color: 'var(--ink-2)' }}>
                  The digital twin operates an asynchronous, decoupled pipeline designed for hard real-time streaming,
                  asynchronous database buffering, and sub-100ms dashboard latency:
                </p>

                <div
                  style={{
                    margin: '16px 0',
                    padding: '18px',
                    borderRadius: 8,
                    background: 'var(--surface-raised)',
                    border: '1px solid var(--border)',
                    fontFamily: 'monospace',
                    fontSize: 12,
                    lineHeight: 1.8,
                    color: 'var(--accent)',
                    overflowX: 'auto',
                  }}
                >
                  <div>┌────────────────────────────────────────────────────────────────────────┐</div>
                  <div>│  PHYSICS ENGINE (1000 Hz RK45 State-Space Solver or Hardware Drivers)  │</div>
                  <div>└───────────────────────────────────┬────────────────────────────────────┘</div>
                  <div>                                    ▼</div>
                  <div>┌────────────────────────────────────────────────────────────────────────┐</div>
                  <div>│  SENSOR ABSTRACTION LAYER (3-Phase Current, Voltage, Tri-Axial Vib)   │</div>
                  <div>└───────────────────────────────────┬────────────────────────────────────┘</div>
                  <div>                                    ▼</div>
                  <div>┌────────────────────────────────────────────────────────────────────────┐</div>
                  <div>│  MULTI-MODAL DIAGNOSTIC ENGINES (MCSA, CWT, Conv-BiLSTM, Thermal, VUF) │</div>
                  <div>└───────────────────────────────────┬────────────────────────────────────┘</div>
                  <div>                                    ▼</div>
                  <div>┌────────────────────────────────────────────────────────────────────────┐</div>
                  <div>│  WEIGHTED DECISION FUSION &amp; SUPERVISORY SADA CONTROLLER (MHI / TRIP)   │</div>
                  <div>└──────────────────┬─────────────────────────────────┬───────────────────┘</div>
                  <div>                   ▼                                 ▼</div>
                  <div>┌──────────────────────────────────────┐  ┌──────────────────────────────┐</div>
                  <div>│  REDIS / IN-MEMORY PUBSUB (10 Hz)   │  │  BATCHED ASYNC MYSQL WRITER  │</div>
                  <div>└──────────────────┬───────────────────┘  └──────────────────────────────┘</div>
                  <div>                   ▼</div>
                  <div>┌────────────────────────────────────────────────────────────────────────┐</div>
                  <div>│  FASTAPI WEBSOCKET / REST SERVER &amp; REACT ENTERPRISE DIGITAL TWIN UI   │</div>
                  <div>└────────────────────────────────────────────────────────────────────────┘</div>
                </div>

                <h4 style={{ fontSize: 14, fontWeight: 700, color: 'var(--ink)', marginTop: 20, marginBottom: 8 }}>
                  Dual Telemetry Ingestion Modes
                </h4>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 14 }}>
                  <div style={{ padding: 14, borderRadius: 8, background: 'var(--surface-raised)', border: '1px solid var(--border)' }}>
                    <div style={{ color: 'var(--accent)', fontWeight: 700, fontSize: 13, marginBottom: 6 }}>
                      Mode: Dynamic State-Space Emulation
                    </div>
                    <p style={{ fontSize: 12, lineHeight: 1.6, color: 'var(--ink-2)' }}>
                      Coupled 5-state nonlinear RK45 Dormand-Prince numerical integration under simulated electrical
                      and mechanical parameters, enabling arbitrary mathematical fault injection and transient testing.
                    </p>
                  </div>
                  <div style={{ padding: 14, borderRadius: 8, background: 'var(--surface-raised)', border: '1px solid var(--border)' }}>
                    <div style={{ color: '#10b981', fontWeight: 700, fontSize: 13, marginBottom: 6 }}>
                      Mode: Real Hardware Stream
                    </div>
                    <p style={{ fontSize: 12, lineHeight: 1.6, color: 'var(--ink-2)' }}>
                      Telemetry acquired directly from physical sensors (I2C ADS1115 ADCs, MQTT accelerometers, Hall-effect
                      transducers) with circuit-breaker fallbacks and zero-burst lag compensation.
                    </p>
                  </div>
                </div>
              </section>
            </div>
          )}

          {/* ========================================================================= */}
          {/* CHAPTER 7: CANONICAL PAPERS, STANDARDS & PROJECT CREDITS */}
          {/* ========================================================================= */}
          {currentChapter.key === 'papers' && (
            <div className="space-y-6">
              <section className="card" style={{ padding: '20px 24px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                  <ExternalLink size={20} style={{ color: 'var(--accent)' }} />
                  <h3 style={{ fontSize: '1.15rem', fontWeight: 700, color: 'var(--ink)' }}>
                    Canonical Research Papers &amp; IEEE Standards
                  </h3>
                </div>
                <p style={{ fontSize: 13, lineHeight: 1.6, color: 'var(--ink-2)', marginBottom: 16 }}>
                  The physics models, diagnostic algorithms, and supervisory trip rules in this digital twin are directly
                  grounded in peer-reviewed electrical engineering literature:
                </p>

                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  {/* Paper 1 */}
                  <div style={{ padding: '14px 18px', borderRadius: 8, background: 'var(--surface-raised)', border: '1px solid var(--border)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--accent)' }}>MCSA FOUNDATIONAL DETECTION</span>
                      <a href="https://doi.org/10.1109/2943.930989" target="_blank" rel="noopener noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, color: 'var(--accent)' }}>
                        <span>IEEE DOI: 10.1109/2943.930989</span>
                        <ExternalLink size={12} />
                      </a>
                    </div>
                    <h5 style={{ fontSize: 13.5, fontWeight: 700, color: 'var(--ink)', margin: '6px 0 4px' }}>
                      Current signature analysis to detect induction motor faults
                    </h5>
                    <p style={{ fontSize: 12, color: 'var(--muted)', lineHeight: 1.5 }}>
                      W. T. Thomson and M. Fenger, <em>IEEE Industry Applications Magazine</em>, vol. 7, no. 4, pp. 26–34, 2001.
                    </p>
                  </div>

                  {/* Paper 2 */}
                  <div style={{ padding: '14px 18px', borderRadius: 8, background: 'var(--surface-raised)', border: '1px solid var(--border)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <span style={{ fontSize: 11, fontWeight: 700, color: '#10b981' }}>CONDITION MONITORING SURVEY</span>
                      <a href="https://doi.org/10.1109/TEC.2005.847954" target="_blank" rel="noopener noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, color: '#10b981' }}>
                        <span>IEEE DOI: 10.1109/TEC.2005.847954</span>
                        <ExternalLink size={12} />
                      </a>
                    </div>
                    <h5 style={{ fontSize: 13.5, fontWeight: 700, color: 'var(--ink)', margin: '6px 0 4px' }}>
                      Condition monitoring and fault diagnosis of electrical motors—a review
                    </h5>
                    <p style={{ fontSize: 12, color: 'var(--muted)', lineHeight: 1.5 }}>
                      S. Nandi, H. A. Toliyat, and X. Li, <em>IEEE Transactions on Energy Conversion</em>, vol. 20, no. 4, pp. 719–729, 2005.
                    </p>
                  </div>

                  {/* Paper 3 */}
                  <div style={{ padding: '14px 18px', borderRadius: 8, background: 'var(--surface-raised)', border: '1px solid var(--border)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--accent)' }}>STATE-SPACE INDUCTION MODEL</span>
                      <a href="https://ieeexplore.ieee.org/document/6894237" target="_blank" rel="noopener noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, color: 'var(--accent)' }}>
                        <span>IEEE Xplore</span>
                        <ExternalLink size={12} />
                      </a>
                    </div>
                    <h5 style={{ fontSize: 13.5, fontWeight: 700, color: 'var(--ink)', margin: '6px 0 4px' }}>
                      Induction machine state-space dynamic modelling and fault diagnosis
                    </h5>
                    <p style={{ fontSize: 12, color: 'var(--muted)', lineHeight: 1.5 }}>
                      J. Chen et al., <em>IEEE International Conference on Electrical Machines (ICEM)</em>, 2014.
                    </p>
                  </div>

                  {/* Standards */}
                  <div style={{ padding: '14px 18px', borderRadius: 8, background: 'var(--surface-raised)', border: '1px solid var(--border)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <span style={{ fontSize: 11, fontWeight: 700, color: '#f59e0b' }}>VIBRATION &amp; RELIABILITY STANDARDS</span>
                      <a href="https://standards.ieee.org/ieee/841/7361/" target="_blank" rel="noopener noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, color: '#f59e0b' }}>
                        <span>IEEE Std 841</span>
                        <ExternalLink size={12} />
                      </a>
                    </div>
                    <h5 style={{ fontSize: 13.5, fontWeight: 700, color: 'var(--ink)', margin: '6px 0 4px' }}>
                      IEEE Std 841 &amp; ISO 10816-3 Machine Condition Standards
                    </h5>
                    <p style={{ fontSize: 12, color: 'var(--muted)', lineHeight: 1.5 }}>
                      Defines vibration severity zones (A: Good &lt;2.3 mm/s, B: Acceptable 2.3–4.5 mm/s, C: Warning 4.5–7.1 mm/s, D: Critical &gt;7.1 mm/s).
                    </p>
                  </div>
                </div>
              </section>
            </div>
          )}

        </div>

        {/* Book Footer with Page Controls, Repository Link & Creation Year */}
        <footer className="book-footer-info">
          {/* Page Turn / Navigation Controls */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <button
              type="button"
              className="book-turn-btn"
              onClick={goToPrev}
              disabled={isFirstPage}
            >
              <ChevronLeft size={16} />
              <span>Previous Chapter</span>
            </button>
            <span style={{ fontSize: 12, fontFamily: 'monospace', color: 'var(--ink)' }}>
              Page {activeChapterIndex + 1} of {CHAPTERS.length}
            </span>
            <button
              type="button"
              className="book-turn-btn"
              onClick={goToNext}
              disabled={isLastPage}
            >
              <span>Next Chapter</span>
              <ChevronRight size={16} />
            </button>
          </div>

          {/* GitHub Repository & Year of Creation */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <a
              href="https://github.com/Naavalanarul/AC_Induction_Motor_Fault_Detection_Digital_Twin"
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                padding: '6px 12px',
                borderRadius: 6,
                background: 'rgba(255, 255, 255, 0.06)',
                border: '1px solid var(--border)',
                color: 'var(--ink)',
                textDecoration: 'none',
                fontWeight: 600,
                fontSize: 12,
                transition: 'all 0.15s ease',
              }}
              className="hover:border-[var(--accent)] hover:text-[var(--accent)]"
            >
              <Github size={14} />
              <span>GitHub Repository</span>
              <ExternalLink size={12} />
            </a>

            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', fontSize: 11, color: 'var(--muted)' }}>
              <span>Created: <strong>2026</strong> · Author: Naavalanarul</span>
              <span>MIT License · AC Induction Motor Digital Twin</span>
            </div>

            <button
              type="button"
              className="btn"
              style={{ height: 32, padding: '0 14px', fontSize: 12 }}
              onClick={onClose}
            >
              Close Documentation
            </button>
          </div>
        </footer>
      </div>
    </div>,
    document.body
  )
}
