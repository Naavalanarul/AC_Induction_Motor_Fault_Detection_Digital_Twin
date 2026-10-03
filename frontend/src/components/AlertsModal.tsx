import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Bell, Check, Loader2, X } from 'lucide-react'
import { api } from '../api/client'
import type { AlertOut } from '../api/types'

export interface AlertsModalProps {
  isOpen: boolean
  onClose: () => void
  motorId: number | null
  motorName?: string
  canOperate: boolean
}

export function AlertsModal({
  isOpen,
  onClose,
  motorId,
  motorName,
  canOperate,
}: AlertsModalProps) {
  const queryClient = useQueryClient()
  const [unacknowledgedOnly, setUnacknowledgedOnly] = useState(false)

  const alertsQuery = useQuery({
    queryKey: ['alerts', motorId, unacknowledgedOnly],
    queryFn: () =>
      api<AlertOut[]>(
        `/motors/${motorId}/alerts${unacknowledgedOnly ? '?unacknowledged=true' : ''}`,
      ),
    enabled: isOpen && motorId != null,
    refetchInterval: isOpen ? 3000 : false,
  })

  const ackMutation = useMutation({
    mutationFn: (alertId: number) =>
      api(`/motors/${motorId}/alerts/${alertId}/ack`, { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts', motorId] })
    },
  })

  if (!isOpen) return null

  const alerts = alertsQuery.data ?? []

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="System Alerts"
    >
      <div className="glass-card w-full max-w-2xl max-h-[85vh] flex flex-col p-6 border-[var(--border)] bg-[var(--surface)] shadow-2xl">
        <header className="flex items-center justify-between pb-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-3">
            <span className="w-8 h-8 rounded-lg bg-[var(--surface-raised)] border border-[var(--border)] flex items-center justify-center text-[var(--accent)]">
              <Bell size={18} />
            </span>
            <div>
              <span className="eyebrow block" style={{ fontSize: 9 }}>
                SUPERVISORY AUDIT LOG
              </span>
              <h2 className="text-base font-semibold text-[var(--ink)]">
                Alerts & System Notifications
              </h2>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-md text-[var(--muted)] hover:text-[var(--ink)] hover:bg-[var(--surface-raised)] transition-colors"
            aria-label="Close alerts"
          >
            <X size={20} />
          </button>
        </header>

        <div className="flex items-center justify-between py-3 border-b border-[var(--border-subtle)] text-xs">
          <span className="text-[var(--muted)] font-mono">
            {motorName ? `Motor: ${motorName}` : 'Select a motor to view alerts'}
          </span>
          <label className="flex items-center gap-2 cursor-pointer text-[var(--ink-2)]">
            <input
              type="checkbox"
              checked={unacknowledgedOnly}
              onChange={(e) => setUnacknowledgedOnly(e.target.checked)}
              className="rounded border-[var(--border)]"
            />
            <span>Unacknowledged only</span>
          </label>
        </div>

        <div className="flex-1 overflow-y-auto py-3 space-y-2.5 min-h-[220px]">
          {alertsQuery.isLoading ? (
            <div className="flex items-center justify-center h-40 text-[var(--muted)] gap-2">
              <Loader2 size={18} className="animate-spin" />
              <span>Loading alerts...</span>
            </div>
          ) : alerts.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-40 text-[var(--muted)] text-center">
              <span className="text-sm">No alerts recorded</span>
              <span className="text-xs text-[var(--muted)] mt-1">
                {unacknowledgedOnly
                  ? 'All alerts have been acknowledged.'
                  : 'Motor operating without logged supervisory exceptions.'}
              </span>
            </div>
          ) : (
            alerts.map((alert) => {
              const isWarning = alert.severity === 'warning'
              const isError = alert.severity === 'error' || alert.severity === 'critical'
              const toneClass = isError
                ? 'border-rose-500/30 bg-rose-950/20 text-rose-300'
                : isWarning
                ? 'border-amber-500/30 bg-amber-950/20 text-amber-300'
                : 'border-cyan-500/30 bg-cyan-950/20 text-cyan-300'

              return (
                <div
                  key={alert.id}
                  className="p-3 rounded-lg bg-[var(--surface-raised)] border border-[var(--border)] flex items-start justify-between gap-3 text-xs"
                >
                  <div className="flex-1 space-y-1">
                    <div className="flex items-center gap-2">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-mono uppercase font-bold border ${toneClass}`}>
                        {alert.severity}
                      </span>
                      <span className="text-[11px] font-mono text-[var(--muted)]">
                        {new Date(alert.ts).toLocaleTimeString()}
                      </span>
                      {alert.acknowledged && (
                        <span className="text-[10px] text-emerald-400 font-mono flex items-center gap-1">
                          <Check size={12} /> ACK
                        </span>
                      )}
                    </div>
                    <p className="text-[var(--ink)] font-sans">{alert.message}</p>
                  </div>

                  {!alert.acknowledged && canOperate && (
                    <button
                      className="btn text-xs py-1 px-2.5 whitespace-nowrap"
                      onClick={() => ackMutation.mutate(alert.id)}
                      disabled={ackMutation.isPending}
                    >
                      Acknowledge
                    </button>
                  )}
                </div>
              )
            })
          )}
        </div>

        <footer className="pt-3 border-t border-[var(--border)] flex justify-end">
          <button className="btn" onClick={onClose}>
            Close
          </button>
        </footer>
      </div>
    </div>
  )
}
