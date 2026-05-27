"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import { TopBar } from "@/components/arax/top-bar"
import { StateUpload } from "@/components/arax/state-upload"
import { StateProcessing } from "@/components/arax/state-processing"
import { StateReview } from "@/components/arax/state-review"
import { StateComplete } from "@/components/arax/state-complete"
import type { StatusResponse } from "@/lib/arax/types"

type View = "upload" | "processing" | "review" | "complete"

export default function Home() {
  const [view, setView] = useState<View>("upload")
  const [jobId, setJobId] = useState<string | null>(null)
  const [dealName, setDealName] = useState<string>("")
  const [status, setStatus] = useState<StatusResponse | null>(null)
  const [finalizing, setFinalizing] = useState(false)
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const cancelled = useRef(false)

  const stopPolling = useCallback(() => {
    if (pollTimer.current) {
      clearTimeout(pollTimer.current)
      pollTimer.current = null
    }
  }, [])

  const reset = useCallback(() => {
    stopPolling()
    cancelled.current = false
    setJobId(null)
    setDealName("")
    setStatus(null)
    setFinalizing(false)
    setView("upload")
  }, [stopPolling])

  // Polling loop — driven by jobId and current view
  useEffect(() => {
    if (!jobId) return
    if (view !== "processing") return

    cancelled.current = false

    const poll = async () => {
      if (cancelled.current) return
      try {
        const res = await fetch(`/api/status?job_id=${encodeURIComponent(jobId)}`, { cache: "no-store" })
        if (!res.ok) {
          toast.error(`Status check failed (${res.status}).`)
        } else {
          const data = (await res.json()) as StatusResponse
          setStatus(data)
          if (data.status === "error") {
            toast.error(data.error || "Job failed.")
            // remain on processing view; user can hit Start over via toast pattern in future
          } else if (data.status === "review_required") {
            setView("review")
            return
          } else if (data.status === "complete") {
            setView("complete")
            return
          }
        }
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Network error while polling.")
      }
      pollTimer.current = setTimeout(poll, 2000)
    }

    poll()
    return () => {
      cancelled.current = true
      stopPolling()
    }
  }, [jobId, view, stopPolling])

  const onJobStarted = useCallback((id: string, name: string) => {
    setJobId(id)
    setDealName(name)
    setStatus(null)
    setView("processing")
  }, [])

  const onCancelReview = useCallback(() => {
    toast("Review cancelled. Returning to upload.")
    reset()
  }, [reset])

  const onFinalize = useCallback(
    async (cityOverrides: Record<string, string>) => {
      if (!jobId) return
      setFinalizing(true)
      try {
        const res = await fetch("/api/confirm", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ job_id: jobId, city_overrides: cityOverrides }),
        })
        if (!res.ok) {
          const txt = await res.text().catch(() => "")
          toast.error(txt || `Finalize failed (${res.status}).`)
          setFinalizing(false)
          return
        }
        // Resume polling — backend will continue from build step
        setFinalizing(false)
        setView("processing")
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Network error.")
        setFinalizing(false)
      }
    },
    [jobId],
  )

  return (
    <div className="min-h-screen">
      <TopBar />
      {view === "upload" && <StateUpload onJobStarted={onJobStarted} />}
      {view === "processing" && <StateProcessing dealName={dealName} status={status} />}
      {view === "review" && status?.review && (
        <StateReview
          dealName={dealName}
          review={status.review}
          onCancel={onCancelReview}
          onFinalize={onFinalize}
          finalizing={finalizing}
        />
      )}
      {view === "complete" && jobId && status?.filename && status?.summary && (
        <StateComplete
          jobId={jobId}
          filename={status.filename}
          summary={status.summary}
          onReset={reset}
        />
      )}
    </div>
  )
}
