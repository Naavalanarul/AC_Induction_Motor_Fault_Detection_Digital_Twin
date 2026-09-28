import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { LogOut, AlertTriangle, X } from 'lucide-react'

export interface SignOutConfirmModalProps {
  isOpen: boolean
  username?: string
  onClose: () => void
  onConfirm: () => void
}

export function SignOutConfirmModal({
  isOpen,
  username,
  onClose,
  onConfirm,
}: SignOutConfirmModalProps) {
  useEffect(() => {
    if (!isOpen) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
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

  return createPortal(
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="modal-dialog glass-card signout-modal-dialog"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="signout-dialog-title"
      >
        {/* Header */}
        <header className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div
              style={{
                width: 32,
                height: 32,
                borderRadius: 8,
                background: 'rgba(239, 68, 68, 0.12)',
                border: '1px solid rgba(239, 68, 68, 0.3)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#f87171',
              }}
            >
              <LogOut size={16} strokeWidth={2} />
            </div>
            <div>
              <span className="eyebrow" style={{ color: '#f87171' }}>OPERATOR SESSION</span>
              <h2 id="signout-dialog-title" className="fleet-title" style={{ fontSize: '1.15rem', marginTop: 1 }}>
                Confirm Sign Out
              </h2>
            </div>
          </div>
          <button
            type="button"
            className="nav-icon-btn"
            onClick={onClose}
            aria-label="Close dialog"
            title="Cancel and return to dashboard"
          >
            <X size={18} />
          </button>
        </header>

        {/* Body */}
        <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: 14 }}>
          <p style={{ margin: 0, fontSize: 14, color: 'var(--ink)', lineHeight: 1.5 }}>
            Are you sure you want to sign out{username ? ` from ${username}` : ''}?
          </p>
          <div
            style={{
              padding: '12px 14px',
              borderRadius: 'var(--corner-md)',
              background: 'rgba(245, 158, 11, 0.08)',
              border: '1px solid rgba(245, 158, 11, 0.25)',
              display: 'flex',
              alignItems: 'flex-start',
              gap: 10,
              fontSize: 12,
              color: 'var(--warning)',
              lineHeight: 1.45,
            }}
          >
            <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 1 }} />
            <span>
              Your active digital twin session and telemetry feeds will disconnect. You will need your plant network credentials to sign back in.
            </span>
          </div>
        </div>

        {/* Footer */}
        <footer className="modal-footer" style={{ borderTop: '1px solid var(--border-subtle)' }}>
          <button
            type="button"
            className="btn"
            onClick={onClose}
            style={{ padding: '7px 16px', fontSize: 13 }}
          >
            Cancel
          </button>
          <button
            type="button"
            className="btn"
            onClick={onConfirm}
            style={{
              padding: '7px 18px',
              fontSize: 13,
              fontWeight: 600,
              background: 'rgba(239, 68, 68, 0.9)',
              color: '#ffffff',
              border: '1px solid rgba(239, 68, 68, 1)',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              boxShadow: '0 4px 14px rgba(239, 68, 68, 0.35)',
            }}
          >
            <LogOut size={14} />
            <span>Yes, Sign Out</span>
          </button>
        </footer>
      </div>
    </div>,
    document.body
  )
}
