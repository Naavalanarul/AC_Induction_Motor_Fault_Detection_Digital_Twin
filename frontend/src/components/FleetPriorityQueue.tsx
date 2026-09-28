import { useState, useMemo } from 'react'
import {
  PriorityQueue,
  calculateMotorPriority,
  INITIAL_FLEET,
  type FleetMotor,
  type HeapType,
} from '../dsa/PriorityQueue'
import { StatusBadge } from './StatusBadge'

export function FleetPriorityQueue() {
  const [fleet, setFleet] = useState<FleetMotor[]>(INITIAL_FLEET)
  const [heapType, setHeapType] = useState<HeapType>('max')
  const [selectedMotorId, setSelectedMotorId] = useState<number | null>(null)
  const [actionLog, setActionLog] = useState<string[]>([
    'Initialized Binary Heap Priority Queue with 6 same-kind industrial motors.',
  ])

  // Build Priority Queue from current fleet
  const { pq, nodes, levels } = useMemo(() => {
    const queue = new PriorityQueue<FleetMotor>(heapType)
    const mode = heapType === 'max' ? 'triage' : 'dispatch'

    for (const motor of fleet) {
      const priority = calculateMotorPriority(motor, mode)
      queue.push(motor, priority, motor.id)
    }

    return {
      pq: queue,
      nodes: queue.toArray(),
      levels: queue.getTreeLevels(),
    }
  }, [fleet, heapType])

  const addLog = (msg: string) => {
    setActionLog((prev) => [msg, ...prev.slice(0, 15)])
  }


  // Inject / Toggle Fault on a specific motor
  const handleInjectFault = (motorId: number, fault: string, severity: number) => {
    setFleet((prev) =>
      prev.map((m) => {
        if (m.id !== motorId) return m
        const isTrip = severity > 0.85
        const isDerate = severity > 0.5 && !isTrip
        return {
          ...m,
          activeFault: fault,
          severity,
          sadaState: isTrip ? 'TRIP' : isDerate ? 'DERATE' : 'WATCH',
          tempC: Math.min(115, m.tempC + severity * 30),
          rpm: isTrip ? 0 : m.rpm - severity * 60,
          currentA: isTrip ? 0 : m.currentA + severity * 2.5,
        }
      })
    )
    addLog(
      `[Fault Injected] Motor #${motorId} faulted with ${fault} (Sev: ${severity.toFixed(2)}). Priority updated & reheapified.`
    )
  }


  return (
    <div className="grid gap-6">
      {/* Header & Mode Selector */}
      <section className="card p-5 border-[var(--border)] bg-[var(--surface)]">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-[var(--ink-2)]" />
              <h2 className="text-sm font-semibold text-[var(--ink)] uppercase tracking-wider">
                Fleet DSA Engine — Priority-Based Queue (Binary Heap)
              </h2>
            </div>
            <p className="text-xs text-[var(--muted)] mt-1">
              Deterministic O(log n) scheduling & triage for an array of identical 5.5 kW AC Induction Motors.
            </p>
          </div>

          {/* Mode Switcher Buttons */}
          <div className="flex items-center gap-1 bg-[var(--surface-raised)] p-0.5 rounded-lg border border-[var(--border)]">
            <button
              onClick={() => setHeapType('max')}
              className={`text-xs py-1.5 px-3 rounded-md font-medium transition-colors ${
                heapType === 'max'
                  ? 'btn-primary font-semibold'
                  : 'text-[var(--muted)] hover:text-[var(--ink)]'
              }`}
            >
              ▲ Max-Heap: Emergency Triage
            </button>
            <button
              onClick={() => setHeapType('min')}
              className={`text-xs py-1.5 px-3 rounded-md font-medium transition-colors ${
                heapType === 'min'
                  ? 'btn-primary font-semibold'
                  : 'text-[var(--muted)] hover:text-[var(--ink)]'
              }`}
            >
              ▼ Min-Heap: Load Dispatch
            </button>
          </div>
        </div>

        {/* Heap Status Ribbon */}
        <div className="flex flex-wrap items-center justify-between gap-3 mt-4 pt-3.5 border-t border-[var(--border)]">
          <span className="text-xs text-[var(--muted)] uppercase tracking-wider font-medium">Heap Telemetry</span>

          <div className="flex items-center gap-4 text-xs num text-[var(--muted)]">
            <span>Fleet Size: <strong className="text-[var(--ink)]">{fleet.length}</strong></span>
            <span>Heap Depth: <strong className="text-[var(--ink)]">{levels.length}</strong></span>
            <span>
              Top Priority:{' '}
              <strong className="text-[var(--ink)]">
                {pq.peek() ? `${pq.peek()!.priority.toFixed(1)} (${pq.peek()!.data.name})` : 'Empty'}
              </strong>
            </span>
          </div>
        </div>
      </section>

      {/* Main Grid: 2D Binary Heap Tree & Memory Array */}
      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        {/* Left: 2D Binary Tree Diagram */}
        <section className="card p-5 border-[var(--border)] bg-[var(--surface)] flex flex-col justify-between">
          <div>
            <header className="flex items-center justify-between pb-3 border-b border-[var(--border)]">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--muted)] flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--ink-2)]" />
                Binary Heap Visualization (Complete Binary Tree)
              </h3>
              <span className="text-[11px] num px-2 py-0.5 rounded bg-[var(--surface-raised)] text-[var(--muted)] border border-[var(--border)]">
                Property: {heapType === 'max' ? 'Parent ≥ Children' : 'Parent ≤ Children'}
              </span>
            </header>

            {/* Tree Rendering Area */}
            <div className="mt-5 py-6 px-2 overflow-x-auto flex flex-col items-center gap-6 min-h-[300px] bg-[var(--surface-raised)] rounded-lg border border-[var(--border)] relative">
              {levels.map((level, levelIdx) => (
                <div key={levelIdx} className="flex justify-around w-full relative z-10 px-4">
                  {level.map((node, nodeIdx) => {
                    const globalIdx = Math.pow(2, levelIdx) - 1 + nodeIdx
                    const isRoot = globalIdx === 0
                    const motor = node.data
                    const isSelected = selectedMotorId === motor.id

                    const stateBorder =
                      motor.sadaState === 'TRIP'
                        ? 'border-rose-500'
                        : motor.sadaState === 'DERATE'
                        ? 'border-amber-500'
                        : motor.sadaState === 'WATCH'
                        ? 'border-yellow-500'
                        : 'border-[var(--border)]'

                    return (
                      <div
                        key={node.id}
                        onClick={() => setSelectedMotorId(motor.id)}
                        className={`flex flex-col items-center cursor-pointer transition-all ${
                          isSelected ? 'scale-105' : ''
                        }`}
                        style={{ minWidth: '95px' }}
                      >
                        {/* Node Bubble */}
                        <div
                          className={`w-12 h-12 rounded-lg flex flex-col items-center justify-center p-1 border bg-[var(--surface)] transition-colors hover:border-[var(--border-hover)] ${stateBorder} ${
                            isRoot ? 'ring-1 ring-[var(--ink)]' : ''
                          }`}
                        >
                          <span className="text-[10px] num text-[var(--muted)] leading-none">
                            #{motor.id}
                          </span>
                          <span className="text-xs font-bold num mt-0.5 text-[var(--ink)]">
                            {node.priority.toFixed(0)}
                          </span>
                        </div>

                        {/* Node Caption */}
                        <div className="text-center mt-1.5">
                          <span className="text-[11px] font-medium text-[var(--ink-2)] block truncate max-w-[100px]">
                            {motor.name.replace(/Unit \d+: /, '')}
                          </span>
                          <span className="text-[9px] num text-[var(--muted)] block">
                            idx: {globalIdx}
                          </span>
                        </div>
                      </div>
                    )
                  })}
                </div>
              ))}
            </div>

            {/* Array In-Memory Representation */}
            <div className="mt-5">
              <span className="text-[11px] num text-[var(--muted)] block mb-2 uppercase tracking-wider">
                Underlying Linear Array Representation: Array[i]
              </span>
              <div className="flex flex-wrap gap-1.5 p-2 rounded-lg bg-[var(--surface-raised)] border border-[var(--border)] overflow-x-auto">
                {nodes.map((node, i) => (
                  <div
                    key={node.id}
                    onClick={() => setSelectedMotorId(node.data.id)}
                    className={`flex flex-col items-center p-2 rounded-md border text-xs num cursor-pointer transition-colors ${
                      selectedMotorId === node.data.id
                        ? 'bg-[var(--surface)] border-[var(--ink)] text-[var(--ink)]'
                        : i === 0
                        ? 'bg-[var(--surface)] border-[var(--border-hover)] text-[var(--ink)]'
                        : 'bg-[var(--surface)] border-[var(--border)] text-[var(--muted)] hover:border-[var(--border-hover)] hover:text-[var(--ink)]'
                    }`}
                  >
                    <span className="text-[10px] text-[var(--muted)]">[{i}]</span>
                    <span className="font-semibold text-[var(--ink)]">U-{node.data.id}</span>
                    <span className="text-[10px] text-[var(--muted)]">{node.priority.toFixed(0)}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Educational DSA Complexity Callout */}
          <div className="mt-5 pt-3.5 border-t border-[var(--border)] text-xs text-[var(--muted)] grid grid-cols-2 sm:grid-cols-4 gap-2 num">
            <div className="p-2 rounded bg-[var(--surface-raised)] border border-[var(--border)]">
              <span className="text-[10px] text-[var(--muted)] block">INSERT</span>
              <strong className="text-[var(--ink)]">O(log n)</strong>
            </div>
            <div className="p-2 rounded bg-[var(--surface-raised)] border border-[var(--border)]">
              <span className="text-[10px] text-[var(--muted)] block">EXTRACT TOP</span>
              <strong className="text-[var(--ink)]">O(log n)</strong>
            </div>
            <div className="p-2 rounded bg-[var(--surface-raised)] border border-[var(--border)]">
              <span className="text-[10px] text-[var(--muted)] block">PEEK ROOT</span>
              <strong className="text-[var(--ink)]">O(1)</strong>
            </div>
            <div className="p-2 rounded bg-[var(--surface-raised)] border border-[var(--border)]">
              <span className="text-[10px] text-[var(--muted)] block">SPACE</span>
              <strong className="text-[var(--ink)]">O(n) Array</strong>
            </div>
          </div>
        </section>

        {/* Right: Selected Motor Details & Fault Injector */}
        <section className="card p-5 border-[var(--border)] bg-[var(--surface)] flex flex-col justify-between">
          <div>
            <header className="pb-3 border-b border-[var(--border)] flex items-center justify-between">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">
                Selected Unit Telemetry
              </h3>
              <span className="text-[11px] num text-[var(--muted)]">
                {selectedMotorId ? `Motor #${selectedMotorId}` : 'Click any node'}
              </span>
            </header>

            {selectedMotorId ? (
              (() => {
                const motor = fleet.find((m) => m.id === selectedMotorId)
                if (!motor) return null
                const priority = calculateMotorPriority(motor, heapType === 'max' ? 'triage' : 'dispatch')

                return (
                  <div className="mt-4 grid gap-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <h4 className="text-sm font-semibold text-[var(--ink)]">{motor.name}</h4>
                        <span className="text-xs text-[var(--muted)]">{motor.bay} · {motor.application}</span>
                      </div>
                      <StatusBadge state={motor.sadaState} />
                    </div>

                    {/* Stats Grid */}
                    <div className="grid grid-cols-2 gap-2 text-xs num">
                      <div className="p-2.5 rounded-md bg-[var(--surface-raised)] border border-[var(--border)]">
                        <span className="text-[var(--muted)] block text-[10px]">PRIORITY SCORE</span>
                        <span className="text-base font-bold text-[var(--ink)]">{priority.toFixed(1)}</span>
                      </div>
                      <div className="p-2.5 rounded-md bg-[var(--surface-raised)] border border-[var(--border)]">
                        <span className="text-[var(--muted)] block text-[10px]">STATOR TEMP</span>
                        <span className={`text-base font-bold ${motor.tempC > 75 ? 'text-rose-400' : 'text-[var(--ink)]'}`}>
                          {motor.tempC.toFixed(1)} °C
                        </span>
                      </div>
                      <div className="p-2.5 rounded-md bg-[var(--surface-raised)] border border-[var(--border)]">
                        <span className="text-[var(--muted)] block text-[10px]">SHAFT SPEED</span>
                        <span className="text-base font-bold text-[var(--ink)]">{motor.rpm} RPM</span>
                      </div>
                      <div className="p-2.5 rounded-md bg-[var(--surface-raised)] border border-[var(--border)]">
                        <span className="text-[var(--muted)] block text-[10px]">PHASE CURRENT</span>
                        <span className="text-base font-bold text-[var(--ink)]">{motor.currentA.toFixed(1)} A</span>
                      </div>
                    </div>

                    {/* Quick Fault Trigger for testing DSA Heapify */}
                    <div className="mt-2 pt-3 border-t border-[var(--border)]">
                      <span className="text-xs font-medium text-[var(--ink-2)] block mb-2">
                        Simulate Real-Time Telemetry Event on #{motor.id}:
                      </span>
                      <div className="grid grid-cols-2 gap-2">
                        <button
                          onClick={() => handleInjectFault(motor.id, 'interturn_short', 0.95)}
                          className="btn text-xs py-1.5 px-2 bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border-rose-500/20"
                        >
                          Trigger SADA Trip
                        </button>
                        <button
                          onClick={() => handleInjectFault(motor.id, 'bearing_outer', 0.65)}
                          className="btn text-xs py-1.5 px-2 bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border-amber-500/20"
                        >
                          Trigger Derate
                        </button>
                        <button
                          onClick={() => handleInjectFault(motor.id, 'thermal_overheat', 0.75)}
                          className="btn text-xs py-1.5 px-2 bg-orange-500/10 hover:bg-orange-500/20 text-orange-300 border-orange-500/20"
                        >
                          Overheat (95°C)
                        </button>
                        <button
                          onClick={() =>
                            setFleet((prev) =>
                              prev.map((m) =>
                                m.id === motor.id
                                  ? {
                                      ...m,
                                      sadaState: 'NORMAL',
                                      severity: 0.05,
                                      activeFault: null,
                                      tempC: 45,
                                      rpm: 1474,
                                      currentA: 4.8,
                                    }
                                  : m
                              )
                            )
                          }
                          className="btn text-xs py-1.5 px-2 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 border-emerald-500/20"
                        >
                          Restore Health
                        </button>
                      </div>
                    </div>
                  </div>
                )
              })()
            ) : (
              <div className="py-12 text-center text-[var(--muted)] text-xs">
                Select any node in the Binary Tree or Linear Array to view telemetry and trigger heap mutations.
              </div>
            )}
          </div>

          {/* Action Log Stream */}
          <div className="mt-5 pt-3 border-t border-[var(--border)]">
            <span className="text-[10px] num uppercase text-[var(--muted)] block mb-1.5">
              Live Heap Mutator Log
            </span>
            <div className="h-28 overflow-y-auto space-y-1 text-[11px] num text-[var(--ink-2)] bg-[var(--surface-raised)] p-2.5 rounded-md border border-[var(--border)]">
              {actionLog.map((log, i) => (
                <div key={i} className="leading-tight">
                  <span className="text-[var(--ink)] mr-1.5 font-bold">›</span>
                  {log}
                </div>
              ))}
            </div>
          </div>
        </section>
      </div>

      {/* Fleet Overview Table */}
      <section className="card p-5 border-[var(--border)] bg-[var(--surface)]">
        <header className="flex items-center justify-between pb-3 border-b border-[var(--border)] mb-4">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">
            Multi-Motor Fleet Inventory (Same-Kind 5.5 kW Induction Motors)
          </h3>
          <span className="text-xs num text-[var(--muted)]">Total Units: {fleet.length}</span>
        </header>

        <div className="overflow-x-auto">
          <table className="w-full text-xs text-left">
            <thead>
              <tr className="border-b border-[var(--border)] text-[var(--muted)] num text-[11px]">
                <th className="py-2 px-3 font-medium">Unit</th>
                <th className="py-2 px-2 font-medium">Location / App</th>
                <th className="py-2 px-2 font-medium">SADA State</th>
                <th className="py-2 px-2 font-medium text-right">RPM</th>
                <th className="py-2 px-2 font-medium text-right">Temp (°C)</th>
                <th className="py-2 px-2 font-medium text-right">Current (A)</th>
                <th className="py-2 px-2 font-medium text-right">Severity</th>
                <th className="py-2 px-3 font-medium text-right">Heap Priority</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border-subtle)] num">
              {fleet.map((m) => {
                const prio = calculateMotorPriority(m, heapType === 'max' ? 'triage' : 'dispatch')
                const isSelected = selectedMotorId === m.id
                return (
                  <tr
                    key={m.id}
                    onClick={() => setSelectedMotorId(m.id)}
                    className={`cursor-pointer transition-colors ${
                      isSelected
                        ? 'bg-[var(--surface-raised)] text-[var(--ink)]'
                        : 'hover:bg-white/[0.02]'
                    }`}
                  >
                    <td className="py-2.5 px-3 font-medium text-[var(--ink)]">{m.name}</td>
                    <td className="py-2.5 px-2 text-[var(--muted)]">{m.bay}</td>
                    <td className="py-2.5 px-2">
                      <StatusBadge state={m.sadaState} />
                    </td>
                    <td className="py-2.5 px-2 text-right text-[var(--ink)]">{m.rpm}</td>
                    <td className={`py-2.5 px-2 text-right ${m.tempC > 75 ? 'text-rose-400 font-bold' : 'text-[var(--ink-2)]'}`}>
                      {m.tempC.toFixed(1)}
                    </td>
                    <td className="py-2.5 px-2 text-right text-[var(--ink-2)]">{m.currentA.toFixed(1)}</td>
                    <td className="py-2.5 px-2 text-right text-[var(--ink-2)]">{(m.severity * 100).toFixed(0)}%</td>
                    <td className="py-2.5 px-3 text-right font-bold text-[var(--ink)]">{prio.toFixed(1)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
