"use client"

import { Check, Loader2, AlertTriangle } from "lucide-react"
import type { StatusResponse, StepKey, StepState } from "@/lib/arax/types"

const STEPS: { key: StepKey; title: string }[] = [
  { key: "parse", title: "Parsing rent roll" },
  { key: "reconcile", title: "Reconciling cities" },
  { key: "inherit", title: "Inheriting prior Arax adjustments" },
  { key: "walkscore", title: "Calling Walk Score" },
  { key: "build", title: "Building workbook" },
]

type Props = {
  dealName: string
  status: StatusResponse | null
}

function Indicator({ state }: { state: StepState }) {
  if (state === "complete") {
    return (
      <div
        className="flex h-4 w-4 items-center justify-center rounded-full"
        style={{ backgroundColor: "var(--color-navy)" }}
      >
        <Check size={10} strokeWidth={3} style={{ color: "var(--color-white)" }} />
      </div>
    )
  }
  if (state === "warning") {
    return (
      <div
        className="flex h-4 w-4 items-center justify-center rounded-full"
        style={{ backgroundColor: "var(--color-bronze)" }}
      >
        <AlertTriangle size={9} strokeWidth={3} style={{ color: "var(--color-white)" }} />
      </div>
    )
  }
  if (state === "active") {
    return (
      <div
        className="flex h-4 w-4 items-center justify-center rounded-full border-2"
        style={{ borderColor: "var(--color-bronze)" }}
      >
        <Loader2 size={9} className="animate-spin" style={{ color: "var(--color-bronze)" }} />
      </div>
    )
  }
  return (
    <div
      className="h-4 w-4 rounded-full border-2"
      style={{ borderColor: "var(--color-bronze)", backgroundColor: "transparent" }}
    />
  )
}

export function StateProcessing({ dealName, status }: Props) {
  const getStep = (key: StepKey) =>
    status?.steps[key] ?? { state: "pending" as StepState, message: "Waiting" }

  return (
    <main className="mx-auto w-full max-w-[720px] px-6 pt-16 pb-24">
      <p className="eyebrow mb-5">Processing — {dealName.toUpperCase()}</p>
      <h1 className="font-serif text-balance text-4xl leading-[1.15] sm:text-5xl" style={{ color: "var(--color-navy)" }}>
        Generating ratings...
      </h1>

      <ol className="mt-12 relative">
        {STEPS.map((step, idx) => {
          const s = getStep(step.key)
          const isLast = idx === STEPS.length - 1
          return (
            <li key={step.key} className="relative flex gap-5 pb-8 last:pb-0">
              {!isLast && (
                <span
                  aria-hidden
                  className="absolute left-2 top-5 -ml-px h-full w-px"
                  style={{ backgroundColor: "var(--color-bronze)" }}
                />
              )}
              <div className="relative z-10 mt-1">
                <Indicator state={s.state} />
              </div>
              <div className="min-w-0 flex-1">
                <h3 className="font-serif text-[18px] leading-tight" style={{ color: "var(--color-navy)" }}>
                  {step.title}
                </h3>
                <p
                  className="mt-1 text-[14px]"
                  style={{
                    color: s.state === "active" ? "var(--color-body)" : "var(--color-muted)",
                  }}
                >
                  {s.message}
                </p>
              </div>
            </li>
          )
        })}
      </ol>
    </main>
  )
}
