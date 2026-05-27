"use client"

import { useEffect, useRef, useState } from "react"
import { ApiError, getStatus, TERMINAL_STATUSES } from "@/lib/api-client"
import type { StatusResponse } from "@/lib/arax/types"

export type UseJobStatusResult = {
  status: StatusResponse | null
  loading: boolean
  /** Set when the polling loop has hit consecutive failures or a hard error (e.g. 404). */
  error: ApiError | null
  /** True once the job has reached a terminal state (complete / failed / review_required). */
  isTerminal: boolean
}

const POLL_INTERVAL_MS = 2000
// Number of consecutive transient failures before we surface a persistent error.
// (404 / non-network errors short-circuit immediately.)
const MAX_TRANSIENT_FAILURES = 3

/**
 * Polls /api/status every 2 seconds for the given jobId.
 *
 * Stops automatically when:
 *   - jobId is null
 *   - status reaches "complete", "failed", or "review_required"
 *   - the component unmounts
 *   - a 404 or other hard error is returned
 *   - too many consecutive transient (network) failures
 */
export function useJobStatus(jobId: string | null, options?: { paused?: boolean }): UseJobStatusResult {
  const paused = options?.paused ?? false
  const [status, setStatus] = useState<StatusResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const cancelledRef = useRef(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const failuresRef = useRef(0)

  useEffect(() => {
    cancelledRef.current = false
    failuresRef.current = 0
    if (!jobId || paused) {
      setLoading(false)
      return
    }

    setLoading(true)
    setError(null)

    const controller = new AbortController()

    const tick = async () => {
      if (cancelledRef.current) return
      try {
        const data = await getStatus(jobId, controller.signal)
        if (cancelledRef.current) return
        failuresRef.current = 0
        setStatus(data)
        setError(null)
        if (TERMINAL_STATUSES.has(data.status)) {
          setLoading(false)
          return
        }
      } catch (err) {
        if (cancelledRef.current) return
        if (err instanceof ApiError) {
          // Hard errors stop the loop immediately.
          if (err.code === "not_found" || err.code === "bad_request" || err.code === "server") {
            setError(err)
            setLoading(false)
            return
          }
          // Transient (network) — count and keep going up to the threshold.
          failuresRef.current += 1
          if (failuresRef.current >= MAX_TRANSIENT_FAILURES) {
            setError(err)
            setLoading(false)
            return
          }
        } else if ((err as { name?: string })?.name === "AbortError") {
          return
        } else {
          failuresRef.current += 1
          if (failuresRef.current >= MAX_TRANSIENT_FAILURES) {
            setError(new ApiError("Server unreachable.", 0, "network"))
            setLoading(false)
            return
          }
        }
      }
      timerRef.current = setTimeout(tick, POLL_INTERVAL_MS)
    }

    void tick()

    return () => {
      cancelledRef.current = true
      controller.abort()
      if (timerRef.current) {
        clearTimeout(timerRef.current)
        timerRef.current = null
      }
    }
  }, [jobId, paused])

  const isTerminal = !!status && TERMINAL_STATUSES.has(status.status)

  return { status, loading, error, isTerminal }
}
