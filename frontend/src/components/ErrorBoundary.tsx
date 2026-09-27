import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  fallbackTitle?: string
  resetOnPropChange?: unknown
}

interface State {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  public override state: State = {
    hasError: false,
    error: null,
  }

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  public override componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('[ErrorBoundary caught error]:', error, errorInfo)
  }

  public override componentDidUpdate(prevProps: Props) {
    if (this.props.resetOnPropChange !== prevProps.resetOnPropChange && this.state.hasError) {
      this.setState({ hasError: false, error: null })
    }
  }

  public handleReset = () => {
    this.setState({ hasError: false, error: null })
  }

  public override render() {
    if (this.state.hasError) {
      return (
        <div className="card p-5 border-rose-500/40 bg-rose-950/20 text-slate-200 flex flex-col gap-3 my-2">
          <div className="flex items-center gap-2 text-rose-400 font-semibold text-sm">
            <svg className="w-5 h-5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="2"
                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
              />
            </svg>
            <span>{this.props.fallbackTitle || 'Component Encountered a Display Anomaly'}</span>
          </div>

          <p className="text-xs text-slate-400 font-mono break-words bg-slate-950/60 p-2.5 rounded border border-rose-900/30">
            {this.state.error?.message || 'An unexpected rendering error occurred.'}
          </p>

          <div className="flex items-center gap-3 pt-1">
            <button
              onClick={this.handleReset}
              className="btn text-xs py-1.5 px-3 bg-rose-900/60 hover:bg-rose-800/80 text-rose-200 border border-rose-700/50 rounded font-medium transition-colors"
            >
              Retry Component
            </button>
            <button
              onClick={() => window.location.reload()}
              className="text-xs text-slate-400 hover:text-slate-200 underline font-mono"
            >
              Reload Page
            </button>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
