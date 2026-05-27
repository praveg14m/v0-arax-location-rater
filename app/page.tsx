"use client"

import { useCallback, useEffect, useState } from "react"
import { toast } from "sonner"
import { TopBar } from "@/components/arax/top-bar"
import { StateUpload } from "@/components/arax/state-upload"
import { StateProcessing } from "@/components/arax/state-processing"
import { StateReview } from "@/components/arax/state-review"
import { StateComplete } from "@/components/arax/state-complete"
import { ErrorBanner } from "@/components/arax/error-banner"
import { useJobStatus } from "@/hooks/use-job-status"
import { ApiError, confirmReview } from "@/lib/api-client"

type View = "upload" | "processing" | "review" | "complete"

export default function Home() {
  const [view, setView] = useState<View>("upload")
  const [jobId, setJobId] = useState<string | null>(null)
  const [dealName, setDealName] = useState<string>("")
  const [finalizing, setFinalizing] = useState(false)
  const [pollPaused, setPollPaused] = useState(false)
  const [bannerDismissed, setBannerDismissed] = useState(false)

  // Stop polling once we leave the processing screen — the review screen reads
  // the snapshot already in `status`, and `complete` does the same. We resume
  // polling after `confirm` to drive the writing → complete transition.
  const paused = pollPaused || (view !== "processing")
  const { status, error: pollError } = useJobStatus(jobId, { paused })

  // Drive view transitions from polled status.
  useEffect(() => {
    if (!status || view !== "processing") return
    if (status.status === "failed") {
      toast.error(status.error || "Job failed.", {
        action: { label: "Start over", onClick: () => reset() },
      })
      setPollPaused(true)
      return
    }
    if (status.status === "review_required") {
      setView("review")
    } else if (status.status === "complete") {
      setView("complete")
    }
    // We intentionally exclude `reset` from deps; it's stable below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, view])

  const reset = useCallback(() => {
    setJobId(null)
    setDealName("")
    setFinalizing(false)
    setPollPaused(false)
    setBannerDismissed(false)
    setView("upload")
  }, [])

  const onJobStarted = useCallback((id: string, name: string) => {
    setJobId(id)
    setDealName(name)
    setPollPaused(false)
    setBannerDismissed(false)
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
        await confirmReview({ jobId, cityOverrides })
        // Resume polling — backend will progress through "writing" -> "complete".
        setPollPaused(false)
        setFinalizing(false)
        setView("processing")
      } catch (err) {
        const msg = err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Network error."
        toast.error(msg)
        setFinalizing(false)
      }
    },
    [jobId],
  )

  const onRetryPolling = useCallback(() => {
    setBannerDismissed(false)
    // Force a fresh polling cycle by toggling pause.
    setPollPaused(true)
    setTimeout(() => setPollPaused(false), 0)
  }, [])

  const showBanner = !!pollError && !bannerDismissed && view !== "upload"
  const bannerMessage = pollError
    ? pollError.code === "not_found"
      ? "Job not found. The function instance may have restarted — please start over."
      : pollError.code === "server"
        ? `Server error while checking job status: ${pollError.message}`
        : "Server unreachable. Check your connection and retry."
    : ""

  return (
    <div className="min-h-screen">
      <TopBar />
      {showBanner && (
        <ErrorBanner
          message={bannerMessage}
          onRetry={pollError?.code === "not_found" ? reset : onRetryPolling}
          onDismiss={() => setBannerDismissed(true)}
        />
      )}
      {view === "upload" && <StateUpload onJobStarted={onJobStarted} />}
      {view === "processing" && <StateProcessing dealName={dealName} status={status} />}
      {view === "review" && status?.review_data && (
        <StateReview
          dealName={dealName}
          review={status.review_data}
          onCancel={onCancelReview}
          onFinalize={onFinalize}
          finalizing={finalizing}
        />
      )}
      {view === "complete" && jobId && status?.result && (
        <StateComplete jobId={jobId} dealName={dealName} result={status.result} onReset={reset} />
      )}
    </div>
  )
}
