"use client"

import { useCallback, useRef, useState } from "react"
import { toast } from "sonner"
import { FileText, Loader2, Upload } from "lucide-react"

const MAX_BYTES = 4 * 1024 * 1024 // 4 MB
const ACCEPTED_EXT = [".xlsx", ".xlsm"]

type Props = {
  onJobStarted: (jobId: string, dealName: string) => void
}

export function StateUpload({ onJobStarted }: Props) {
  const [dealName, setDealName] = useState("")
  const [file, setFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const validateAndSetFile = useCallback((f: File | null) => {
    if (!f) {
      setFile(null)
      setFileError(null)
      return
    }
    const lower = f.name.toLowerCase()
    const okExt = ACCEPTED_EXT.some((ext) => lower.endsWith(ext))
    if (!okExt) {
      setFile(null)
      setFileError("Unsupported file type. Upload an .xlsx or .xlsm file.")
      return
    }
    if (f.size > MAX_BYTES) {
      setFile(f)
      setFileError("File exceeds 4MB limit. Vercel serverless functions cap upload bodies at this size.")
      return
    }
    setFile(f)
    setFileError(null)
  }, [])

  const onDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragOver(false)
    const f = e.dataTransfer.files?.[0] ?? null
    validateAndSetFile(f)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!dealName.trim() || !file || fileError) return
    setSubmitting(true)
    try {
      const fd = new FormData()
      fd.append("file", file)
      fd.append("deal_name", dealName.trim())
      const res = await fetch("/api/process", { method: "POST", body: fd })
      if (res.status === 413) {
        toast.error("File too large. The upload limit is 4MB. Please contact engineering for large-portfolio support.")
        setSubmitting(false)
        return
      }
      if (!res.ok) {
        const text = await res.text().catch(() => "")
        toast.error(text || `Request failed (${res.status}).`)
        setSubmitting(false)
        return
      }
      const data = (await res.json()) as { job_id: string; status: string }
      if (!data?.job_id) {
        toast.error("Server did not return a job id.")
        setSubmitting(false)
        return
      }
      onJobStarted(data.job_id, dealName.trim())
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Network error. Please retry.")
      setSubmitting(false)
    }
  }

  const formValid = !!dealName.trim() && !!file && !fileError

  return (
    <main className="mx-auto w-full max-w-[720px] px-6 pt-16 pb-24">
      <p className="eyebrow mb-5">Location Rater</p>
      <h1
        className="font-serif text-balance text-4xl leading-[1.15] sm:text-5xl"
        style={{ color: "var(--color-navy)" }}
      >
        Score a German residential acquisition
      </h1>
      <p className="mt-5 max-w-[60ch] text-[15px] leading-relaxed" style={{ color: "var(--color-muted)" }}>
        Upload a rent roll. Get a finished location-ratings workbook against Arax&apos;s 5-pillar methodology.
      </p>

      <form
        onSubmit={handleSubmit}
        className="mt-10 rounded-[6px] border p-7 sm:p-9"
        style={{ backgroundColor: "var(--color-warm-panel)", borderColor: "var(--color-rule)" }}
      >
        {/* Deal name */}
        <label htmlFor="deal-name" className="eyebrow mb-3 block">
          Deal name
        </label>
        <input
          id="deal-name"
          type="text"
          required
          value={dealName}
          onChange={(e) => setDealName(e.target.value)}
          placeholder="e.g. Project Falcon"
          className="w-full rounded-[4px] border bg-white px-3 py-2.5 text-[15px] outline-none transition-colors focus:border-[var(--color-navy)] focus:ring-2 focus:ring-[var(--color-bronze)]/40"
          style={{ borderColor: "var(--color-rule)", color: "var(--color-body)" }}
        />

        {/* Rent roll dropzone */}
        <label className="eyebrow mt-7 mb-3 block">Rent roll</label>
        <div
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault()
            setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") inputRef.current?.click()
          }}
          className="flex cursor-pointer flex-col items-center justify-center rounded-[4px] border-2 border-dashed bg-white px-6 py-10 text-center transition-colors"
          style={{
            borderColor: dragOver ? "var(--color-navy)" : "var(--color-bronze)",
            backgroundColor: dragOver ? "rgba(140,123,92,0.06)" : "#ffffff",
          }}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".xlsx,.xlsm"
            className="hidden"
            onChange={(e) => validateAndSetFile(e.target.files?.[0] ?? null)}
          />
          {file ? (
            <div className="flex w-full items-center justify-between gap-4">
              <div className="flex min-w-0 items-center gap-3">
                <FileText size={20} style={{ color: "var(--color-bronze)" }} />
                <div className="min-w-0 text-left">
                  <p className="truncate text-[14px] font-medium" style={{ color: "var(--color-navy)" }}>
                    {file.name}
                  </p>
                  <p className="text-[12px]" style={{ color: "var(--color-muted)" }}>
                    {(file.size / (1024 * 1024)).toFixed(2)} MB
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  validateAndSetFile(null)
                  if (inputRef.current) inputRef.current.value = ""
                  setTimeout(() => inputRef.current?.click(), 0)
                }}
                className="text-[13px] font-medium underline-offset-4 hover:underline"
                style={{ color: "var(--color-bronze)" }}
              >
                Replace
              </button>
            </div>
          ) : (
            <>
              <Upload size={22} style={{ color: "var(--color-bronze)" }} />
              <p className="mt-3 text-[14px]" style={{ color: "var(--color-body)" }}>
                Drag and drop your rent roll, or click to browse
              </p>
              <p className="mt-1 text-[12px]" style={{ color: "var(--color-muted)" }}>
                Accepted formats: .xlsx, .xlsm · Maximum size: 4 MB
              </p>
            </>
          )}
        </div>
        {fileError && (
          <p className="mt-2 text-[13px]" style={{ color: "var(--color-danger)" }}>
            {fileError}
          </p>
        )}

        {/* Submit */}
        <button
          type="submit"
          disabled={!formValid || submitting}
          className="mt-8 flex w-full items-center justify-center gap-2 rounded-[4px] py-3 text-[13px] font-semibold tracking-[0.15em] uppercase transition-colors focus:ring-2 focus:ring-[var(--color-bronze)] focus:outline-none disabled:cursor-not-allowed disabled:opacity-40"
          style={{ backgroundColor: "var(--color-navy)", color: "var(--color-white)" }}
        >
          {submitting ? (
            <>
              <Loader2 size={16} className="animate-spin" />
              Uploading and starting job...
            </>
          ) : (
            "Generate Ratings"
          )}
        </button>

        <p className="mt-4 text-[12px] leading-relaxed" style={{ color: "var(--color-muted)" }}>
          Outputs a date-stamped working copy of the master location-ratings workbook. The master file is never
          modified.
        </p>
      </form>
    </main>
  )
}
