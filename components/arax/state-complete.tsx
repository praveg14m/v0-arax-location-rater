"use client"

import { CheckCircle2 } from "lucide-react"
import type { RunSummary } from "@/lib/arax/types"

type Props = {
  jobId: string
  filename: string
  summary: RunSummary
  onReset: () => void
}

const fmtDuration = (s: number) => {
  if (s < 60) return `${s.toFixed(0)}s`
  const m = Math.floor(s / 60)
  const r = Math.round(s - m * 60)
  return `${m}m ${r}s`
}

export function StateComplete({ jobId, filename, summary, onReset }: Props) {
  return (
    <main className="mx-auto w-full max-w-[720px] px-6 pt-16 pb-24">
      <div className="flex flex-col items-center text-center">
        <CheckCircle2 size={64} strokeWidth={1.5} style={{ color: "var(--color-bronze)" }} />
        <h1
          className="mt-6 font-serif text-balance text-4xl leading-[1.15] sm:text-5xl"
          style={{ color: "var(--color-navy)" }}
        >
          Workbook ready
        </h1>
        <p
          className="mt-5 font-medium tracking-tight text-[15px]"
          style={{ color: "var(--color-body)" }}
        >
          {filename}
        </p>

        <a
          href={`/api/download?job_id=${encodeURIComponent(jobId)}`}
          className="mt-8 inline-flex items-center justify-center rounded-[4px] px-8 py-3 text-[13px] font-semibold tracking-[0.15em] uppercase transition-colors focus:ring-2 focus:ring-[var(--color-bronze)] focus:outline-none"
          style={{ backgroundColor: "var(--color-navy)", color: "var(--color-white)" }}
        >
          Download workbook
        </a>
      </div>

      <section
        className="mt-12 rounded-[6px] border p-7"
        style={{ backgroundColor: "var(--color-warm-panel)", borderColor: "var(--color-rule)" }}
      >
        <p className="eyebrow mb-5">Run summary</p>
        <dl className="grid grid-cols-1 gap-y-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <Row k="Deal name" v={summary.deal_name} />
          <Row k="Cities scored" v={summary.cities_scored.toString()} />
          <Row k="Unique streets called" v={summary.unique_streets_called.toString()} />
          <Row
            k="Walk Score successes / failures"
            v={`${summary.walkscore_successes} / ${summary.walkscore_failures}`}
          />
          <Row k="Prior adjustments inherited" v={summary.prior_adjustments_inherited.toString()} />
          <Row k="Total processing time" v={fmtDuration(summary.total_processing_time_seconds)} />
        </dl>

        <div className="mt-6 border-t pt-4" style={{ borderColor: "var(--color-rule)" }}>
          <a
            href={`/api/run-log?job_id=${encodeURIComponent(jobId)}`}
            className="text-[13px] font-medium underline-offset-4 hover:underline"
            style={{ color: "var(--color-bronze)" }}
          >
            Download run log (.txt)
          </a>
        </div>
      </section>

      <div className="mt-10 flex justify-center">
        <button
          type="button"
          onClick={onReset}
          className="text-[13px] font-semibold tracking-[0.15em] uppercase transition-colors hover:opacity-70"
          style={{ color: "var(--color-muted)" }}
        >
          Score another portfolio
        </button>
      </div>
    </main>
  )
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <>
      <dt className="text-[14px]" style={{ color: "var(--color-muted)" }}>
        {k}
      </dt>
      <dd
        className="text-[14px] sm:text-right"
        style={{ color: "var(--color-body)", fontVariantNumeric: "tabular-nums" }}
      >
        {v}
      </dd>
    </>
  )
}
