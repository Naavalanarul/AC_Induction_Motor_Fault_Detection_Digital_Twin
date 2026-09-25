import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, loadSession, saveSession } from './client'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

afterEach(() => {
  vi.unstubAllGlobals()
  saveSession(null)
})

describe('api client', () => {
  it('refreshes the access token once on 401 and retries', async () => {
    saveSession({ access_token: 'old', refresh_token: 'r1', role: 'viewer', username: 'v' })
    const fetch = vi.fn()
      .mockResolvedValueOnce(json({ detail: 'expired' }, 401))
      .mockResolvedValueOnce(json({ access_token: 'new', refresh_token: 'r2', role: 'viewer', username: 'v' }))
      .mockResolvedValueOnce(json([{ id: 1 }]))
    vi.stubGlobal('fetch', fetch)
    const out = await api<{ id: number }[]>('/motors')
    expect(out).toEqual([{ id: 1 }])
    expect(loadSession()?.access_token).toBe('new')
    expect(new Headers((fetch.mock.calls[2][1] as RequestInit).headers).get('Authorization')).toBe('Bearer new')
  })

  it('surfaces the error detail', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ detail: 'motor not found' }, 404)))
    await expect(api('/motors/9')).rejects.toEqual(new ApiError(404, 'motor not found'))
  })
})
