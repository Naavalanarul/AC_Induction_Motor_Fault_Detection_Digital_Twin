import { describe, expect, it } from 'vitest'
import {
  PriorityQueue,
  calculateMotorPriority,
  INITIAL_FLEET,
  type FleetMotor,
} from './PriorityQueue'

describe('PriorityQueue DSA Heap Implementation', () => {
  it('correctly maintains Max-Heap property with O(log n) push and pop', () => {
    const pq = new PriorityQueue<string>('max')
    pq.push('Motor C', 50)
    pq.push('Motor A', 10)
    pq.push('Motor D', 100)
    pq.push('Motor B', 30)

    expect(pq.size()).toBe(4)
    expect(pq.peek()?.priority).toBe(100)
    expect(pq.peek()?.data).toBe('Motor D')

    // Pop root (highest priority first)
    const top1 = pq.pop()
    expect(top1?.priority).toBe(100)
    expect(top1?.data).toBe('Motor D')

    const top2 = pq.pop()
    expect(top2?.priority).toBe(50)
    expect(top2?.data).toBe('Motor C')

    const top3 = pq.pop()
    expect(top3?.priority).toBe(30)
    expect(top3?.data).toBe('Motor B')

    const top4 = pq.pop()
    expect(top4?.priority).toBe(10)
    expect(top4?.data).toBe('Motor A')

    expect(pq.isEmpty()).toBe(true)
    expect(pq.pop()).toBeUndefined()
  })

  it('correctly maintains Min-Heap property', () => {
    const pq = new PriorityQueue<string>('min')
    pq.push('Pump 2', 45)
    pq.push('Pump 1', 12)
    pq.push('Pump 3', 88)
    pq.push('Pump 4', 5)

    expect(pq.peek()?.priority).toBe(5)
    expect(pq.peek()?.data).toBe('Pump 4')

    expect(pq.pop()?.priority).toBe(5)
    expect(pq.pop()?.priority).toBe(12)
    expect(pq.pop()?.priority).toBe(45)
    expect(pq.pop()?.priority).toBe(88)
  })

  it('updates node priority dynamically with re-heapify', () => {
    const pq = new PriorityQueue<{ name: string }>('max')
    pq.push({ name: 'Unit 1' }, 20, 1)
    pq.push({ name: 'Unit 2' }, 40, 2)
    pq.push({ name: 'Unit 3' }, 10, 3)

    expect(pq.peek()?.id).toBe(2)

    // Unit 3 suffers a critical trip, priority skyrockets to 1000
    const updated = pq.updatePriority(3, 1000)
    expect(updated).toBe(true)
    expect(pq.peek()?.id).toBe(3)
    expect(pq.peek()?.priority).toBe(1000)
  })

  it('calculates fleet triage and dispatch priorities correctly', () => {
    const trippedMotor: FleetMotor = {
      ...INITIAL_FLEET[0],
      sadaState: 'TRIP',
      severity: 0.95,
      tempC: 98,
    }
    const healthyMotor: FleetMotor = {
      ...INITIAL_FLEET[0],
      sadaState: 'NORMAL',
      severity: 0.05,
      tempC: 40,
    }

    const triageTripped = calculateMotorPriority(trippedMotor, 'triage')
    const triageHealthy = calculateMotorPriority(healthyMotor, 'triage')
    expect(triageTripped).toBeGreaterThan(1000)
    expect(triageTripped).toBeGreaterThan(triageHealthy)

    const dispatchTripped = calculateMotorPriority(trippedMotor, 'dispatch')
    const dispatchHealthy = calculateMotorPriority(healthyMotor, 'dispatch')
    // In dispatch mode, lower priority score = healthier
    expect(dispatchHealthy).toBeLessThan(dispatchTripped)
  })
})
