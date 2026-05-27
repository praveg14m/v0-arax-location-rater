"use client"

import { Check, Loader2, AlertTriangle } from "lucide-react"
import type { JobStatus, StatusResponse, StepNumber } from "@/lib/arax/types"

type StepDef = {
  num: StepNumber
  title: string
  // Status values for which this step should appear "active"
  activeFor: JobStatus[]
}

const STEPS: StepDef[] = [
  { num: 1, title: "Parsing rent roll", activeFor: ["queued", "parsing"] },
  { num: 2, title: "Reconciling cities against master list", activeFor: ["matching"] },
  { num: 3, title: "Inheriting prior Arax adjustments", activeFor: ["inheriting"] },
  { num: 4, title: "Calling Walk Score", activeFor: ["scoring", "review_required"] },
  { num: 5, title: "Building workbook", activeFor: ["writing"] },
]

type Props = {
  dealName: string
  status: StatusResponse | null
}

type VisualState = "pending" | "active" | "complete" | "warning"

function stepVisualState(step: StepDef, status: StatusResponse | null): VisualState {
  if (!status) return step.num === 1 ? "active" : "pending"

  // Anything before current_step is complete.
  if (step.num < status.current_step) return "complete"

  // The walk-score step gets a "warning" tone if it surfaced any failures
  // and we've moved past it.
  if (step.num === 4 && status.status !== "scoring" && (status.step_results?.step_4?.failed ?? 0) > 0) {
    if (step.num < status.current_step) return "warning"
  }

  if (step.num === status.current_step) {
    if (step.activeFor.includes(status.status)) return "active"
    // Edge case: review_required keeps step 4 visually active until confirm.
    if (step.num === 4 && status.status === "review_required") return "active"
    return "active"
  }

  return "pending"
}

function stepMessage(step: StepDef, status: StatusResponse | null, dealName: string): string {
  if (!status) return "Waiting"
  const sr = status.step_results

  switch (step.num) {
    case 1:
      if (status.current_step > 1 && sr?.step_1)
        return `Found ${sr.step_1.addresses.toLocaleString()} addresses across ${sr.step_1.cities} cities.`
      if (status.status === "parsing") return `Reading ${dealName} rent roll...`
      return "Waiting"
    case 2:
      if (status.current_step > 2 && sr?.step_2)
        return `${sr.step_2.exact} exact, ${sr.step_2.fuzzy} fuzzy, ${sr.step_2.unmatched} unmatched.`
      if (status.status === "matching") return "Matching against master city list..."
      return "Waiting"
    case 3:
      if (status.current_step > 3 && sr?.step_3)
        return `Inherited ${sr.step_3.cities_inherited} cities from ${sr.step_3.source_deals} prior deals.`
      if (status.status === "inheriting") return "Searching prior deal workbooks..."
      return "Waiting"
    case 4:
      if (status.status === "scoring" && status.step_progress)
        return `Scoring street ${status.step_progress.current} of ${status.step_progress.total}...`
      if (status.status === "review_required") return "Awaiting your review."
      if (status.current_step > 4 && sr?.step_4)
        return `${sr.step_4.scored} streets scored, ${sr.step_4.failed} failures.`
      return "Waiting"
    case 5:
      if (status.status === "writing") return "Populating master workbook (preserving macros)..."
      if (status.status === "complete") return "Workbook ready."
      return "Waiting"
    default:
      return "Waiting"
  }
}

function Indicator({ state, num }: { state: VisualState; num: StepNumber }) {
  if (state === "complete") {
    return (
      <div
        className="flex h-5 w-5 items-center justify-center rounded-full"
        style={{ backgroundColor: "var(--color-navy)" }}
      >
        <Check size={12} strokeWidth={3} style={{ color: "var(--color-white)" }} />
      </div>
    )
  }
  if (state === "warning") {
    return (
      <div
        className="flex h-5 w-5 items-center justify-center rounded-full"
        style={{ backgroundColor: "var(--color-bronze)" }}
      >
        <AlertTriangle size={11} strokeWidth={3} style={{ color: "var(--color-white)" }} />
      </div>
    )
  }
  if (state === "active") {
    return (
      <div
        className="flex h-5 w-5 items-center justify-center rounded-full border-2"
        style={{ borderColor: "var(--color-bronze)" }}
      >
        <Loader2 size={10} className="animate-spin" style={{ color: "var(--color-bronze)" }} />
      </div>
    )
  }
  return (
    <div
      className="flex h-5 w-5 items-center justify-center rounded-full border-2"
      style={{ borderColor: "var(--color-bronze)", backgroundColor: "transparent" }}
    >
      <span
        className="text-[10px] font-semibold tabular-nums"
        style={{ color: "var(--color-bronze)" }}
      >
        {num}
      </span>
    </div>
  )
}

export function StateProcessing({ dealName, status }: Props) {
  return (
    <main className="mx-auto w-full max-w-[720px] px-6 pt-16 pb-24">
      <p className="eyebrow mb-5">Processing — {dealName.toUpperCase()}</p>
      <h1
        className="font-serif text-balance text-4xl leading-[1.15] sm:text-5xl"
        style={{ color: "var(--color-navy)" }}
      >
        Generating ratings...
      </h1>

      <ol className="mt-12 relative">
        {STEPS.map((step, idx) => {
          const v = stepVisualState(step, status)
          const isLast = idx === STEPS.length - 1
          return (
            <li key={step.num} className="relative flex gap-5 pb-8 last:pb-0">
              {!isLast && (
                <span
                  aria-hidden
                  className="absolute left-[10px] top-6 -ml-px h-full w-px"
                  style={{ backgroundColor: "var(--color-bronze)" }}
                />
              )}
              <div className="relative z-10 mt-0.5">
                <Indicator state={v} num={step.num} />
              </div>
              <div className="min-w-0 flex-1">
                <h3
                  className="font-serif text-[18px] leading-tight"
                  style={{ color: "var(--color-navy)" }}
                >
                  {step.title}
                </h3>
                <p
                  className="mt-1 text-[14px]"
                  style={{ color: v === "active" ? "var(--color-body)" : "var(--color-muted)" }}
                >
                  {stepMessage(step, status, dealName)}
                </p>
              </div>
            </li>
          )
        })}
      </ol>
    </main>
  )
}
