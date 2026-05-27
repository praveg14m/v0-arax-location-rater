// Typed API client for the Python serverless endpoints.
// Mirrors the contract in lib/arax/types.ts and api/_state.py.

import type { JobStatus, StatusResponse } from "@/lib/arax/types"

export class ApiError extends Error {
  status: number
  /** Stable code: "too_large", "not_found", "bad_request", "server", "network". */
  code: "too_large" | "not_found" | "bad_request" | "server" | "network" | "unknown"

  constructor(message: string, status: number, code: ApiError["code"]) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.code = code
  }
}

function classify(status: number): ApiError["code"] {
  if (status === 413) return "too_large"
  if (status === 404) return "not_found"
  if (status >= 400 && status < 500) return "bad_request"
  if (status >= 500) return "server"
  return "unknown"
}

async function readErrorMessage(res: Response): Promise<string> {
  const ctype = res.headers.get("content-type") ?? ""
  try {
    if (ctype.includes("application/json")) {
      const j = (await res.json()) as { error?: string; message?: string }
      return j.error ?? j.message ?? `Request failed (${res.status}).`
    }
    const text = await res.text()
    return text || `Request failed (${res.status}).`
  } catch {
    return `Request failed (${res.status}).`
  }
}

export type ProcessResponse = {
  job_id: string
  status: JobStatus
}

export async function uploadRentRoll(args: { file: File; dealName: string }): Promise<ProcessResponse> {
  const fd = new FormData()
  fd.append("file", args.file)
  fd.append("deal_name", args.dealName)
  let res: Response
  try {
    res = await fetch("/api/process", { method: "POST", body: fd })
  } catch (err) {
    throw new ApiError(err instanceof Error ? err.message : "Network error.", 0, "network")
  }
  if (!res.ok) {
    const msg = await readErrorMessage(res)
    throw new ApiError(msg, res.status, classify(res.status))
  }
  return (await res.json()) as ProcessResponse
}

export async function getStatus(jobId: string, signal?: AbortSignal): Promise<StatusResponse> {
  let res: Response
  try {
    res = await fetch(`/api/status?job_id=${encodeURIComponent(jobId)}`, {
      cache: "no-store",
      signal,
    })
  } catch (err) {
    if (signal?.aborted) throw err
    throw new ApiError(err instanceof Error ? err.message : "Network error.", 0, "network")
  }
  if (!res.ok) {
    const msg = await readErrorMessage(res)
    throw new ApiError(msg, res.status, classify(res.status))
  }
  return (await res.json()) as StatusResponse
}

export type ConfirmRequest = {
  jobId: string
  cityOverrides: Record<string, string>
}

export async function confirmReview(req: ConfirmRequest): Promise<StatusResponse> {
  let res: Response
  try {
    res = await fetch("/api/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: req.jobId, city_overrides: req.cityOverrides }),
    })
  } catch (err) {
    throw new ApiError(err instanceof Error ? err.message : "Network error.", 0, "network")
  }
  if (!res.ok) {
    const msg = await readErrorMessage(res)
    throw new ApiError(msg, res.status, classify(res.status))
  }
  return (await res.json()) as StatusResponse
}

export function downloadUrl(jobId: string): string {
  return `/api/download?job_id=${encodeURIComponent(jobId)}`
}

export function runLogUrl(jobId: string): string {
  return `/api/run-log?job_id=${encodeURIComponent(jobId)}`
}

export const TERMINAL_STATUSES: ReadonlySet<JobStatus> = new Set<JobStatus>([
  "complete",
  "failed",
  "review_required",
])
