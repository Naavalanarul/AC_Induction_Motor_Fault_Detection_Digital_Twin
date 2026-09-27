/**
 * PriorityQueue.ts — High-Performance Binary Heap (Priority Queue) Data Structure
 * Applied to Multi-Motor Fleet Health Triage and Automated Load Dispatching.
 *
 * Time Complexity Guarantees:
 * - Insert (heappush): O(log n)
 * - Extract Max/Min (heappop): O(log n)
 * - Peek Top: O(1)
 * - Dynamic Priority Update: O(log n) with index hash map
 * - Space Complexity: O(n) contiguous array
 */

export interface HeapNode<T> {
  id: string | number
  priority: number
  data: T
  timestamp: number
  key?: string
}

export type HeapType = 'max' | 'min'

export interface HeapTraceStep {
  type: 'compare' | 'swap' | 'insert' | 'extract'
  indices: [number, number]
  message: string
}

export class PriorityQueue<T> {
  private heap: HeapNode<T>[] = []
  private idIndexMap: Map<string | number, number> = new Map()
  public readonly type: HeapType
  public lastTrace: HeapTraceStep[] = []

  constructor(type: HeapType = 'max') {
    this.type = type
  }

  public size(): number {
    return this.heap.length
  }

  public isEmpty(): boolean {
    return this.heap.length === 0
  }

  public peek(): HeapNode<T> | undefined {
    return this.heap[0]
  }

  public toArray(): HeapNode<T>[] {
    return [...this.heap]
  }

  private compare(a: number, b: number): boolean {
    return this.type === 'max' ? a > b : a < b
  }

  private swap(i: number, j: number): void {
    const temp = this.heap[i]
    this.heap[i] = this.heap[j]
    this.heap[j] = temp

    this.idIndexMap.set(this.heap[i].id, i)
    this.idIndexMap.set(this.heap[j].id, j)
  }

  private siftUp(index: number): void {
    let current = index
    while (current > 0) {
      const parent = Math.floor((current - 1) / 2)
      if (this.compare(this.heap[current].priority, this.heap[parent].priority)) {
        this.lastTrace.push({
          type: 'swap',
          indices: [current, parent],
          message: `Swapped node [${this.heap[current].id}] (P: ${this.heap[current].priority.toFixed(1)}) with parent [${this.heap[parent].id}] (P: ${this.heap[parent].priority.toFixed(1)})`,
        })
        this.swap(current, parent)
        current = parent
      } else {
        break
      }
    }
  }

  private siftDown(index: number): void {
    let current = index
    const len = this.heap.length

    while (true) {
      let target = current
      const left = 2 * current + 1
      const right = 2 * current + 2

      if (left < len && this.compare(this.heap[left].priority, this.heap[target].priority)) {
        target = left
      }
      if (right < len && this.compare(this.heap[right].priority, this.heap[target].priority)) {
        target = right
      }

      if (target !== current) {
        this.lastTrace.push({
          type: 'swap',
          indices: [current, target],
          message: `Sifted down [${this.heap[current].id}] with child [${this.heap[target].id}]`,
        })
        this.swap(current, target)
        current = target
      } else {
        break
      }
    }
  }

  public push(data: T, priority: number, id?: string | number): void {
    this.lastTrace = []
    const nodeId = id ?? (typeof (data as { id?: string | number }).id !== 'undefined' ? (data as { id: string | number }).id : this.heap.length)
    
    // If element exists, update priority instead
    if (this.idIndexMap.has(nodeId)) {
      this.updatePriority(nodeId, priority)
      return
    }

    const node: HeapNode<T> = {
      id: nodeId,
      priority,
      data,
      timestamp: Date.now(),
    }

    this.heap.push(node)
    const index = this.heap.length - 1
    this.idIndexMap.set(nodeId, index)

    this.lastTrace.push({
      type: 'insert',
      indices: [index, index],
      message: `Enqueued node [${nodeId}] with priority ${priority.toFixed(1)}`,
    })

    this.siftUp(index)
  }

  public pop(): HeapNode<T> | undefined {
    if (this.isEmpty()) return undefined
    this.lastTrace = []

    const root = this.heap[0]
    this.idIndexMap.delete(root.id)

    const last = this.heap.pop()!
    if (this.heap.length > 0) {
      this.heap[0] = last
      this.idIndexMap.set(last.id, 0)
      this.lastTrace.push({
        type: 'extract',
        indices: [0, 0],
        message: `Extracted root [${root.id}] (P: ${root.priority.toFixed(1)}). Promoted last node [${last.id}] to root`,
      })
      this.siftDown(0)
    }

    return root
  }

  public updatePriority(id: string | number, newPriority: number): boolean {
    const index = this.idIndexMap.get(id)
    if (index === undefined) return false

    const oldPriority = this.heap[index].priority
    this.heap[index].priority = newPriority

    if (this.compare(newPriority, oldPriority)) {
      this.siftUp(index)
    } else {
      this.siftDown(index)
    }
    return true
  }

  public remove(id: string | number): boolean {
    const index = this.idIndexMap.get(id)
    if (index === undefined) return false

    // Bring to top by artificially assigning infinity, then pop
    const inf = this.type === 'max' ? Number.POSITIVE_INFINITY : Number.NEGATIVE_INFINITY
    this.heap[index].priority = inf
    this.siftUp(index)
    this.pop()
    return true
  }

  public clear(): void {
    this.heap = []
    this.idIndexMap.clear()
    this.lastTrace = []
  }

  /**
   * Group heap nodes into hierarchical tree levels for 2D tree visualization
   */
  public getTreeLevels(): HeapNode<T>[][] {
    const levels: HeapNode<T>[][] = []
    let levelStart = 0
    let levelSize = 1

    while (levelStart < this.heap.length) {
      const level = this.heap.slice(levelStart, levelStart + levelSize)
      levels.push(level)
      levelStart += levelSize
      levelSize *= 2
    }
    return levels
  }
}

/**
 * Multi-Motor Fleet Models and Real-Time Priority Scoring
 */
export interface FleetMotor {
  id: number
  name: string
  bay: string
  application: string
  ratedPowerKw: number
  rpm: number
  tempC: number
  currentA: number
  severity: number
  confidence: number
  sadaState: 'NORMAL' | 'WATCH' | 'DERATE' | 'TRIP'
  activeFault: string | null
  loadPct: number
  operatingHours: number
}

/**
 * Calculates priority score for fleet scheduling and triage:
 * 
 * - Triage Mode (Max-Heap): Highest score = most critical emergency requiring operator attention.
 * - Dispatch Mode (Min-Heap): Lowest score = healthiest motor with highest headroom to take process load.
 */
export function calculateMotorPriority(motor: FleetMotor, mode: 'triage' | 'dispatch'): number {
  const severity = motor?.severity ?? 0
  const confidence = motor?.confidence ?? 0
  const tempC = motor?.tempC ?? 45
  const currentA = motor?.currentA ?? 4.5
  const loadPct = motor?.loadPct ?? 50
  const operatingHours = motor?.operatingHours ?? 0
  const sadaState = motor?.sadaState ?? 'NORMAL'

  if (mode === 'triage') {
    let score = 0
    // SADA State Emergency Weight
    if (sadaState === 'TRIP') score += 1000
    else if (sadaState === 'DERATE') score += 250
    else if (sadaState === 'WATCH') score += 80

    // Fault Severity & Confidence
    score += severity * 200
    score += confidence * 40

    // Thermal Overheating Penalty (>75°C)
    if (tempC > 75) {
      score += (tempC - 75) * 8
    }

    // High current stress (> 110% rated)
    if (currentA > 5.5) {
      score += (currentA - 5.5) * 20
    }

    return Math.round(score * 10) / 10
  } else {
    // Dispatch Mode (Min-Heap): lower is better
    let score = 0
    if (sadaState === 'TRIP') score += 9999
    if (sadaState === 'DERATE') score += 400
    if (sadaState === 'WATCH') score += 150

    score += severity * 300
    score += (tempC / 100) * 80
    score += loadPct * 0.8
    score += (operatingHours / 5000) * 20

    return Math.round(score * 10) / 10
  }
}

/**
 * Initial standard fleet of identical / same-kind 5.5 kW 4-pole induction motors
 * typically found in industrial pump & blower stations.
 */
export const INITIAL_FLEET: FleetMotor[] = [
  {
    id: 1,
    name: 'Unit 1: Main Drive Twin',
    bay: 'Bay A-01',
    application: 'Conveyor Head Pulley',
    ratedPowerKw: 5.5,
    rpm: 1474,
    tempC: 48.5,
    currentA: 4.8,
    severity: 0.12,
    confidence: 0.88,
    sadaState: 'NORMAL',
    activeFault: null,
    loadPct: 75,
    operatingHours: 1420,
  },
  {
    id: 2,
    name: 'Unit 2: Chilled Water Pump A',
    bay: 'Bay B-04',
    application: 'HVAC Circulation Loop',
    ratedPowerKw: 5.5,
    rpm: 1462,
    tempC: 82.4,
    currentA: 5.9,
    severity: 0.68,
    confidence: 0.94,
    sadaState: 'DERATE',
    activeFault: 'bearing_outer',
    loadPct: 70,
    operatingHours: 4210,
  },
  {
    id: 3,
    name: 'Unit 3: Chilled Water Pump B',
    bay: 'Bay B-05',
    application: 'HVAC Circulation Standby',
    ratedPowerKw: 5.5,
    rpm: 1488,
    tempC: 38.2,
    currentA: 3.2,
    severity: 0.05,
    confidence: 0.91,
    sadaState: 'NORMAL',
    activeFault: null,
    loadPct: 40,
    operatingHours: 850,
  },
  {
    id: 4,
    name: 'Unit 4: Boiler Feed Booster',
    bay: 'Bay C-12',
    application: 'High-Pressure Steam Feed',
    ratedPowerKw: 5.5,
    rpm: 0,
    tempC: 96.1,
    currentA: 0.0,
    severity: 0.92,
    confidence: 0.98,
    sadaState: 'TRIP',
    activeFault: 'interturn_short',
    loadPct: 0,
    operatingHours: 6300,
  },
  {
    id: 5,
    name: 'Unit 5: Cooling Tower Blower 1',
    bay: 'Bay D-02',
    application: 'Thermal Rejection Fan',
    ratedPowerKw: 5.5,
    rpm: 1469,
    tempC: 56.7,
    currentA: 5.1,
    severity: 0.35,
    confidence: 0.85,
    sadaState: 'WATCH',
    activeFault: 'unbalance',
    loadPct: 82,
    operatingHours: 2900,
  },
  {
    id: 6,
    name: 'Unit 6: Cooling Tower Blower 2',
    bay: 'Bay D-03',
    application: 'Thermal Rejection Fan',
    ratedPowerKw: 5.5,
    rpm: 1478,
    tempC: 44.0,
    currentA: 4.4,
    severity: 0.08,
    confidence: 0.92,
    sadaState: 'NORMAL',
    activeFault: null,
    loadPct: 65,
    operatingHours: 1950,
  },
]
