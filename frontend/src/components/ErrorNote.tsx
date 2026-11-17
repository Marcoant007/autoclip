import { ApiError } from '../api'
import { Icon } from './Icon'

/**
 * A failure and, where the server offered one, the fix.
 *
 * The hint carries most of the value: "YouTube blocked this download" is a
 * dead end, while "set a browser to pull cookies from" is something the user
 * can act on without leaving the app.
 */
export function ErrorNote({
  error,
  onDismiss,
}: {
  error: Error
  onDismiss?: () => void
}) {
  const hint = error instanceof ApiError ? error.hint : ''

  return (
    <div
      role="alert"
      className="fade-in flex items-start gap-3 rounded-xl border border-signal-bad/30 bg-signal-bad/[0.06] px-4 py-3"
    >
      <Icon name="alert" size={17} className="mt-0.5 text-signal-bad" />
      <div className="min-w-0 flex-1">
        <p className="whitespace-pre-line text-sm font-semibold text-ink-100 [overflow-wrap:anywhere]">
          {error.message}
        </p>
        {hint && (
          <p className="mt-1.5 max-w-prose whitespace-pre-line text-sm leading-relaxed text-ink-400">
            {hint}
          </p>
        )}
      </div>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          className="btn btn-quiet btn-icon -mr-1 -mt-1"
          aria-label="Fechar aviso"
        >
          <Icon name="x" size={15} />
        </button>
      )}
    </div>
  )
}
