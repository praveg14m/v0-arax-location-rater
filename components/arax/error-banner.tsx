"use client"

import { AlertTriangle, X } from "lucide-react"

type Props = {
  message: string
  onRetry?: () => void
  onDismiss?: () => void
}

export function ErrorBanner({ message, onRetry, onDismiss }: Props) {
  return (
    <div
      role="alert"
      aria-live="polite"
      className="border-b"
      style={{
        backgroundColor: "rgba(139,46,46,0.06)",
        borderColor: "var(--color-rule)",
      }}
    >
      <div className="mx-auto flex max-w-[1040px] items-start gap-3 px-6 py-3">
        <AlertTriangle size={18} className="mt-0.5 shrink-0" style={{ color: "var(--color-danger)" }} />
        <p className="flex-1 text-[14px] leading-relaxed" style={{ color: "var(--color-body)" }}>
          {message}
        </p>
        <div className="flex shrink-0 items-center gap-4">
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="text-[13px] font-semibold tracking-[0.1em] uppercase underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:ring-[var(--color-bronze)] focus-visible:outline-none"
              style={{ color: "var(--color-navy)" }}
            >
              Retry
            </button>
          )}
          {onDismiss && (
            <button
              type="button"
              onClick={onDismiss}
              aria-label="Dismiss error"
              className="rounded-[3px] p-1 hover:bg-white focus-visible:ring-2 focus-visible:ring-[var(--color-bronze)] focus-visible:outline-none"
              style={{ color: "var(--color-muted)" }}
            >
              <X size={16} />
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
