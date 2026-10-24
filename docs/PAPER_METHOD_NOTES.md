# Paper Method Notes: Mathematical Formulations, Constants, and Supervisory Logic

This document specifies the governing mathematical models, physical parameters, empirical thresholds, and algorithmic workflows implemented in the AC Induction Motor Digital Twin. Every equation and parameter directly mirrors the production codebase in `backend/app/`.

---

## 1. Core Physics & Digital Twin Plant Dynamics

### 1.1 State-Space Dynamic Model (Stationary $\alpha-\beta$ Frame)
The continuous electromagnetic dynamics of the squirrel-cage induction motor are modeled in the stationary stator reference frame ($\alpha-\beta$) following standard Krause/Chen representations (`backend/app/simulation/plant.py`, `core_physics/dq_model.py`):

$$\frac{d i_{s\alpha}}{dt} = -\gamma i_{s\alpha} + \frac{K}{\tau_r} \psi_{r\alpha} + K p \omega_m \psi_{r\beta} + \frac{1}{\sigma L_s} u_{s\alpha}$$

$$\frac{d i_{s\beta}}{dt} = -\gamma i_{s\beta} - K p \omega_m \psi_{r\alpha} + \frac{K}{\tau_r} \psi_{r\beta} + \frac{1}{\sigma L_s} u_{s\beta}$$

$$\frac{d \psi_{r\alpha}}{dt} = \frac{L_m}{\tau_r} i_{s\alpha} - \frac{1}{\tau_r} \psi_{r\alpha} - p \omega_m \psi_{r\beta}$$

$$\frac{d \psi_{r\beta}}{dt} = \frac{L_m}{\tau_r} i_{s\beta} + p \omega_m \psi_{r\alpha} - \frac{1}{\tau_r} \psi_{r\beta}$$

where derived coupling coefficients are:
$$\sigma = 1 - \frac{L_m^2}{L_s L_r}, \quad \tau_r = \frac{L_r}{R_r}, \quad K = \frac{L_m}{\sigma L_s L_r}, \quad \gamma = \frac{R_s}{\sigma L_s} + \frac{R_r L_m^2}{\sigma L_s L_r^2}$$

### 1.2 Mechanical Rotor Dynamics
$$\frac{d \omega_m}{dt} = \frac{1}{J} \left( T_e - T_L - B \omega_m \right)$$
$$\frac{d \theta_m}{dt} = \omega_m$$

Electromagnetic torque $T_e$:
$$T_e = \frac{3}{2} p \frac{L_m}{L_r} \left( \psi_{r\alpha} i_{s\beta} - \psi_{r\beta} i_{s\alpha} \right) = \frac{3}{2} p \left( \psi_{s\alpha} i_{s\beta} - \psi_{s\beta} i_{s\alpha} \right)$$

Numerical integration is performed via explicit 4th-order Runge-Kutta (RK4) with fixed time-step $\Delta t = 0.0002$ s ($f_s = 5000$ Hz).

---

## 2. Thermal Dynamics & Resistance Drift

### 2.1 Thermal Transient Modeling
The lumped-parameter thermal network (`core_physics/thermal_lptn.py`, `diagnostics/thermal.py`) captures copper heat accumulation and winding hotspot rise:

$$C_{\text{th}} \frac{d T_w}{dt} = P_{\text{loss}}(t) - \frac{T_w - T_{\text{ambient}}}{R_{\text{th}}}$$

where total power dissipation combines stator copper losses, rotor losses, and fault heating:
$$P_{\text{loss}} = \frac{3}{2} R_s |I_s|^2 + \frac{3}{2} R_r |I_r|^2 + P_{\text{core}} + P_{\text{fault}}$$

### 2.2 Temperature Compensation of Observer Resistances
To prevent false electrical residual alarms during normal motor heating, the observer updates winding resistances in real time:

$$R_s(T_w) = R_{s, 25^\circ\text{C}} \left[ 1 + \alpha_{\text{Cu}} \left( T_w - 25.0 \right) \right]$$
$$R_r(T_w) = R_{r, 25^\circ\text{C}} \left[ 1 + \alpha_{\text{Cu}} \left( T_w - 25.0 \right) \right]$$

with copper temperature coefficient $\alpha_{\text{Cu}} = 0.00393 \text{ K}^{-1}$.

---

## 3. Diagnostic Residuals and Feature Extraction

### 3.1 Electrical Fault Detection Scalar (FD)
The electrical residual channel (`diagnostics/electrical.py`) compares measured stator currents with the nominal temperature-compensated digital twin observer currents:

$$\mathbf{r}_i(t) = \begin{bmatrix} i_{s\alpha}(t) - \hat{i}_{s\alpha}(t) \\ i_{s\beta}(t) - \hat{i}_{s\beta}(t) \end{bmatrix}$$

The normalized residual fault scalar $FD \in [0.0, 1.0]$ is computed as:
$$FD = \min\left(1.0, \frac{\|\mathbf{r}_i\|_{\text{RMS}}}{\sqrt{2} I_{\text{rated}}}\right)$$

### 3.2 MCSA Spectral Defect Characteristic Frequencies
For slip $s = \frac{\omega_{\text{sync}} - p \omega_m}{\omega_{\text{sync}}}$ and supply frequency $f_e$:
- **Broken Rotor Bars (BRB):** Lower and upper sidebands:
  $$f_{\text{brb}} = (1 \pm 2s) f_e$$
- **Dynamic Eccentricity:**
  $$f_{\text{ecc}} = f_e \pm f_r = f_e \pm \frac{\omega_m}{2\pi}$$
- **Bearing Defect Pass Frequencies** ($n_b$ balls, pitch diameter $D_p$, ball diameter $d_b$, contact angle $\beta$):
  $$f_{\text{BPFO}} = \frac{n_b}{2} f_r \left( 1 - \frac{d_b}{D_p} \cos \beta \right)$$
  $$f_{\text{BPFI}} = \frac{n_b}{2} f_r \left( 1 + \frac{d_b}{D_p} \cos \beta \right)$$
  $$f_{\text{BSF}} = \frac{D_p}{2 d_b} f_r \left( 1 - \left( \frac{d_b}{D_p} \cos \beta \right)^2 \right)$$

---

## 4. Multi-Source Evidence Fusion

The fusion engine (`diagnostics/fusion.py`) receives channel verdicts $V_k = (F_k, c_k, s_k)$ from 5 diagnostic channels:
1. $E$: Electrical Residual Observer (`ELECTRICAL_RESIDUAL`)
2. $M$: ML Conv-BiLSTM Classifier (`ML_CLASSIFIER`)
3. $T$: Thermal Diagnostic (`THERMAL`)
4. $S$: Supply Quality Analyzer (`SUPPLY`)
5. $P$: Protection Diagnostic (`PROTECTION`)

### 4.1 Supply Fault Isolation Gate
If the supply diagnostic identifies voltage anomalies (unbalance $> 2\%$, total harmonic distortion $\text{THD} > 5\%$, or voltage sag $> 10\%$), the electrical residual channel is inhibited from triggering motor internal fault diagnoses:
$$\text{If } V_S.\text{fault} \neq \text{HEALTHY} \implies w_E \leftarrow 0.0, \quad F_{\text{fused}} \leftarrow V_S.\text{fault}$$

This prevents electrical supply disturbances from causing false trips on broken rotor bars or stator winding insulation.

---

## 5. Supervisory Automated Derating Architecture (SADA)

The supervisory state machine (`supervisory/sada.py`) executes at $10$ Hz ($\Delta t = 0.1$ s) and coordinates closed-loop anti-hunting actions:

```
          s_ema < 0.20
       +--------------------------------------------+
       |                                            |
       v                                            |
  +----------+   s_ema >= 0.20   +----------+       |
  |  NORMAL  | ----------------> |  WATCH   | ------+
  +----------+                   +----------+
       ^                               |
       | cooldown > 10s & s_ema < 0.40 | s_ema >= 0.50 & dwell >= 5s
       |                               v
  +----------+   s_ema >= 0.80   +----------+
  |   TRIP   | <---------------- |  DERATE  |
  +----------+                   +----------+
```

### 5.1 Exponential Smoothing & Confidence Gating
Instantaneous severity $s_t$ is filtered through an Exponential Moving Average (EMA) only when diagnosis confidence exceeds the gate threshold $\tau_{\text{conf}} = 0.35$:
$$s_{\text{gated}} = \begin{cases} s_t & \text{if } c_t \ge 0.35 \\ s_{\text{ema}, t-1} & \text{if } c_t < 0.35 \end{cases}$$
$$s_{\text{ema}, t} = \alpha s_{\text{gated}} + (1 - \alpha) s_{\text{ema}, t-1}, \quad \alpha = 0.15$$

### 5.2 Anti-Hunting Derating Actuation
During the `DERATE` state, the load torque command sent to the motor drive is scaled smoothly to alleviate mechanical/thermal stress:
$$T_{\text{cmd}} = T_{\text{base}} \times \max\left(0.20, 1.0 - 0.5 \times s_{\text{ema}}\right)$$

### 5.3 Safety Constraints
- **Dwell Time:** Must persist continuously in `WATCH` for $t_{\text{dwell}} \ge 5.0$ s before transitioning to `DERATE` (prevents false derating on transient spikes).
- **Reset Cooldown:** After derating, recovery back to `NORMAL` requires $t_{\text{cooldown}} \ge 10.0$ s with $s_{\text{ema}} < 0.40$ (prevents rapid limit-cycle hunting).

---

## 6. Motor Health Index (MHI)

The composite MHI scalar (`diagnostics/health_index.py`) maps operational health into $[0.0, 100.0]$:

$$\text{MHI} = \max\left(0.0, \min\left(100.0, 100.0 - 60 \cdot s - P_{\text{state}} - P_{\text{channel}}\right)\right)$$

### 6.1 State and Channel Deductions
- **State Penalty $P_{\text{state}}$:** $\text{NORMAL} = 0$, $\text{WATCH} = 10$, $\text{DERATE} = 25$, $\text{TRIP} = 60$.
- **Channel Penalty $P_{\text{channel}}$:** Sum of criticalities for degraded/offline sensors (capped at $50$):
  - Phase Current: $12.0$
  - Line Voltage: $10.0$
  - Shaft Speed: $10.0$
  - Vibration: $8.0$
  - Temperature: $6.0$
  - Acoustic: $4.0$

### 6.2 ISO 20816 Condition Zones
- **Zone A (Good):** $85.0 \le \text{MHI} \le 100.0$
- **Zone B (Acceptable):** $70.0 \le \text{MHI} < 85.0$
- **Zone C (Alert):** $50.0 \le \text{MHI} < 70.0$
- **Zone D (Danger):** $0.0 \le \text{MHI} < 50.0$

---

## 7. Master Parameter & Constant Classification Table

| Parameter / Constant | Symbol | Value | Units | Code Location | Category | Source / Rationale |
|:---|:---:|:---:|:---:|:---|:---:|:---|
| Rated Mechanical Power | $P_{\text{rated}}$ | 4000.0 | W | `simulation/params.py` | Physical | Nameplate rating (4 kW benchmark) |
| Rated RMS Line Voltage | $V_{\text{rated}}$ | 400.0 | V | `simulation/params.py` | Physical | Standard 400V 3-phase European grid |
| Rated Line Current | $I_{\text{rated}}$ | 8.6 | A | `simulation/params.py` | Physical | Motor nameplate full-load current |
| Rated Shaft Speed | $n_{\text{rated}}$ | 1440.0 | rpm | `simulation/params.py` | Physical | 4-pole induction motor at 50 Hz |
| Pole Pairs | $p$ | 2 | -- | `simulation/params.py` | Physical | 4-pole magnetic design |
| Stator Resistance ($25^\circ$C) | $R_s$ | 1.405 | $\Omega$ | `simulation/params.py` | Physical | Measured experimentally |
| Rotor Resistance ($25^\circ$C) | $R_r$ | 1.395 | $\Omega$ | `simulation/params.py` | Physical | Referred to stator |
| Stator Inductance | $L_s$ | 0.0058 | H | `simulation/params.py` | Physical | Leakage inductance component |
| Rotor Inductance | $L_r$ | 0.0058 | H | `simulation/params.py` | Physical | Leakage inductance component |
| Magnetizing Inductance | $L_m$ | 0.1722 | H | `simulation/params.py` | Physical | Mutual flux coupling |
| Total Rotor Inertia | $J$ | 0.0131 | $\text{kg}\cdot\text{m}^2$ | `simulation/params.py` | Physical | Motor rotor + shaft coupling |
| Friction Damping | $B$ | 0.001 | $\text{N}\cdot\text{m}\cdot\text{s}$ | `simulation/params.py` | Physical | Bearing windage and friction |
| Simulation Integration Step | $\Delta t$ | 0.0002 | s | `simulation/plant.py` | Standard | Fixed step for 5 kHz resolution |
| SADA Supervisory Cycle | $\Delta t_{\text{sada}}$ | 0.1 | s | `supervisory/sada.py` | Tuned on sim | 10 Hz industrial SCADA polling rate |
| Supervisory EMA Smoothing | $\alpha_{\text{ema}}$ | 0.15 | -- | `supervisory/sada.py` | Tuned on sim | Balance between responsiveness & noise rejection |
| Confidence Gate Threshold | $\tau_{\text{conf}}$ | 0.35 | -- | `supervisory/sada.py` | Authors' design | Minimum model confidence required to update EMA |
| Supervisory WATCH Threshold | $s_{\text{watch}}$ | 0.20 | -- | `supervisory/sada.py` | Authors' design | Threshold for early advisory monitoring |
| Supervisory DERATE Threshold | $s_{\text{derate}}$ | 0.50 | -- | `supervisory/sada.py` | Authors' design | Incipient damage boundary triggering derating |
| Supervisory TRIP Threshold | $s_{\text{trip}}$ | 0.80 | -- | `supervisory/sada.py` | Authors' design | Safety limit for emergency shutdown |
| Anti-Hunting Dwell Time | $t_{\text{dwell}}$ | 5.0 | s | `supervisory/sada.py` | Tuned on sim | Prevents chatter on transient spikes |
| Reset Cooldown Period | $t_{\text{cooldown}}$ | 10.0 | s | `supervisory/sada.py` | Tuned on sim | Prevents rapid cyclic reactivation |
| Winding Warning Temp (Class F) | $T_{\text{warn}}$ | 130.0 | $^\circ$C | `simulation/params.py` | Standard | IEC 60034-1 Class F thermal limit margin |
| Winding Trip Temp (Class F) | $T_{\text{trip}}$ | 155.0 | $^\circ$C | `simulation/params.py` | Standard | IEC 60034-1 Class F maximum hotspot limit |
| Supply Imbalance Threshold | $\text{Imb}_{\text{crit}}$ | 0.02 | -- | `diagnostics/supply.py` | Standard | IEEE 1159 / EN 50160 power quality standard |
| Copper Temp Coefficient | $\alpha_{\text{Cu}}$ | 0.00393 | $\text{K}^{-1}$ | `simulation/plant.py` | Physical | Handbook physical constant for annealed copper |
| Bearing Nominal Base Life | $L_{10h}$ | 20000.0 | h | `diagnostics/rul_engine.py` | Standard | ISO 281 catalog rating for deep-groove bearings |
