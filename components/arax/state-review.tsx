"use client"

import { useMemo, useState } from "react"
import { Loader2 } from "lucide-react"
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import type { ReviewData } from "@/lib/arax/types"

const eur = (n: number) =>
  new Intl.NumberFormat("en-IE", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(n)

type Props = {
  dealName: string
  review: ReviewData
  onCancel: () => void
  onFinalize: (cityOverrides: Record<string, string>) => void
  finalizing?: boolean
}

const KEEP_AS_IS = "__keep_as_is__"

export function StateReview({ dealName, review, onCancel, onFinalize, finalizing }: Props) {
  const { cities, inherited_adjustments, walk_score_summary } = review

  // Fuzzy: default to proposed match
  const [fuzzyOverrides, setFuzzyOverrides] = useState<Record<string, string>>(() =>
    Object.fromEntries(cities.fuzzy_matches.map((f) => [f.raw, f.proposed])),
  )
  // Unmatched: no default
  const [unmatchedSelections, setUnmatchedSelections] = useState<Record<string, string>>({})

  const allUnmatchedResolved = useMemo(
    () => cities.unmatched.every((u) => !!unmatchedSelections[u.raw]),
    [cities.unmatched, unmatchedSelections],
  )

  const exactCount = cities.exact_matches.length
  const fuzzyCount = cities.fuzzy_matches.length
  const unmatchedCount = cities.unmatched.length

  const handleFinalize = () => {
    if (!allUnmatchedResolved || finalizing) return
    const overrides: Record<string, string> = {}
    for (const f of cities.fuzzy_matches) {
      const v = fuzzyOverrides[f.raw]
      if (v && v !== KEEP_AS_IS) overrides[f.raw] = v
    }
    for (const u of cities.unmatched) {
      const v = unmatchedSelections[u.raw]
      if (v) overrides[u.raw] = v
    }
    onFinalize(overrides)
  }

  return (
    <main className="mx-auto w-full max-w-[1040px] px-6 pt-12 pb-24">
      <p className="eyebrow mb-5">Review — {dealName.toUpperCase()}</p>
      <h1
        className="font-serif text-balance text-4xl leading-[1.15] sm:text-5xl"
        style={{ color: "var(--color-navy)" }}
      >
        Confirm ratings before finalizing
      </h1>
      <p className="mt-4 max-w-[70ch] text-[15px] leading-relaxed" style={{ color: "var(--color-muted)" }}>
        Review the tool&apos;s matches and overrides below. Once you confirm, the workbook will be generated.
      </p>

      {/* Section A — City matching */}
      <section
        className="mt-10 rounded-[6px] border p-7"
        style={{ backgroundColor: "var(--color-warm-panel)", borderColor: "var(--color-rule)" }}
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-serif text-[22px]" style={{ color: "var(--color-navy)" }}>
            City matches
          </h2>
          <div className="flex flex-wrap gap-2">
            <KpiBadge label={`${exactCount} exact`} tone="success" />
            <KpiBadge label={`${fuzzyCount} fuzzy`} tone="warning" />
            {unmatchedCount > 0 && <KpiBadge label={`${unmatchedCount} unmatched`} tone="danger" />}
          </div>
        </div>

        <Accordion
          type="multiple"
          defaultValue={["fuzzy", ...(unmatchedCount > 0 ? ["unmatched"] : [])]}
          className="mt-5"
        >
          {/* Exact */}
          <AccordionItem value="exact" className="border-b" style={{ borderColor: "var(--color-rule)" }}>
            <AccordionTrigger className="py-4 hover:no-underline">
              <span className="text-[14px]" style={{ color: "var(--color-body)" }}>
                Exact matches{" "}
                <span style={{ color: "var(--color-muted)" }}>({exactCount})</span>
              </span>
            </AccordionTrigger>
            <AccordionContent>
              <ReviewTable
                head={["Raw city", "Mapped to", "Addresses", "Annual rent (€)"]}
                rows={cities.exact_matches.map((m) => [
                  m.raw,
                  m.mapped,
                  m.address_count.toString(),
                  eur(m.annual_rent),
                ])}
                rightAlignCols={[2, 3]}
              />
            </AccordionContent>
          </AccordionItem>

          {/* Fuzzy */}
          <AccordionItem value="fuzzy" className="border-b" style={{ borderColor: "var(--color-rule)" }}>
            <AccordionTrigger className="py-4 hover:no-underline">
              <span className="text-[14px]" style={{ color: "var(--color-body)" }}>
                Fuzzy matches that need confirmation{" "}
                <span style={{ color: "var(--color-muted)" }}>({fuzzyCount})</span>
              </span>
            </AccordionTrigger>
            <AccordionContent>
              <div className="overflow-x-auto">
                <table className="w-full text-[14px]">
                  <thead>
                    <tr className="text-left" style={{ color: "var(--color-muted)" }}>
                      <Th>Raw city</Th>
                      <Th>Proposed match</Th>
                      <Th>Confidence</Th>
                      <Th>Override</Th>
                      <Th align="right">Addresses</Th>
                      <Th align="right">Annual rent (€)</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {cities.fuzzy_matches.map((f) => (
                      <tr key={f.raw} className="border-t" style={{ borderColor: "var(--color-rule)" }}>
                        <Td>{f.raw}</Td>
                        <Td>{f.proposed}</Td>
                        <Td>
                          <span
                            className="inline-flex items-center rounded-[3px] px-2 py-0.5 text-[12px] font-medium"
                            style={{
                              backgroundColor: "rgba(140,123,92,0.14)",
                              color: "var(--color-bronze)",
                            }}
                          >
                            {f.confidence}%
                          </span>
                        </Td>
                        <Td>
                          <Select
                            value={fuzzyOverrides[f.raw]}
                            onValueChange={(v) => setFuzzyOverrides((s) => ({ ...s, [f.raw]: v }))}
                          >
                            <SelectTrigger className="h-9 min-w-[200px] bg-white text-[14px]">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {[f.proposed, ...f.alternatives.filter((c) => c !== f.proposed)]
                                .slice(0, 5)
                                .map((c) => (
                                  <SelectItem key={c} value={c}>
                                    {c}
                                  </SelectItem>
                                ))}
                              <SelectItem value={KEEP_AS_IS}>Keep as-is</SelectItem>
                            </SelectContent>
                          </Select>
                        </Td>
                        <Td align="right">{f.address_count}</Td>
                        <Td align="right">{eur(f.annual_rent)}</Td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </AccordionContent>
          </AccordionItem>

          {/* Unmatched */}
          {unmatchedCount > 0 && (
            <AccordionItem value="unmatched" className="border-b-0">
              <AccordionTrigger className="py-4 hover:no-underline">
                <span className="text-[14px]" style={{ color: "var(--color-danger)" }}>
                  Unmatched cities{" "}
                  <span style={{ color: "var(--color-muted)" }}>({unmatchedCount})</span>
                </span>
              </AccordionTrigger>
              <AccordionContent>
                <div className="overflow-x-auto">
                  <table className="w-full text-[14px]">
                    <thead>
                      <tr className="text-left" style={{ color: "var(--color-muted)" }}>
                        <Th>Raw city</Th>
                        <Th>Suggested matches</Th>
                        <Th align="right">Addresses</Th>
                        <Th align="right">Annual rent (€)</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {cities.unmatched.map((u) => (
                        <tr key={u.raw} className="border-t" style={{ borderColor: "var(--color-rule)" }}>
                          <Td>{u.raw}</Td>
                          <Td>
                            <Select
                              value={unmatchedSelections[u.raw] ?? ""}
                              onValueChange={(v) => setUnmatchedSelections((s) => ({ ...s, [u.raw]: v }))}
                            >
                              <SelectTrigger className="h-9 min-w-[220px] bg-white text-[14px]">
                                <SelectValue placeholder="Choose a match..." />
                              </SelectTrigger>
                              <SelectContent>
                                {u.candidates.slice(0, 5).map((c) => (
                                  <SelectItem key={c} value={c}>
                                    {c}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </Td>
                          <Td align="right">{u.address_count}</Td>
                          <Td align="right">{eur(u.annual_rent)}</Td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </AccordionContent>
            </AccordionItem>
          )}
        </Accordion>
      </section>

      {/* Section B — Inherited adjustments */}
      <section
        className="mt-8 rounded-[6px] border p-7"
        style={{ backgroundColor: "var(--color-warm-panel)", borderColor: "var(--color-rule)" }}
      >
        <h2 className="font-serif text-[22px]" style={{ color: "var(--color-navy)" }}>
          Inherited adjustments
        </h2>
        <p className="mt-1 text-[14px]" style={{ color: "var(--color-muted)" }}>
          {inherited_adjustments.length} cities have ratings from prior deals. These will appear in blue in the workbook.
        </p>

        {inherited_adjustments.length > 0 ? (
          <div className="mt-5 overflow-x-auto">
            <table className="w-full text-[14px]">
              <thead>
                <tr className="text-left" style={{ color: "var(--color-muted)" }}>
                  <Th>City</Th>
                  <Th align="right">Prior adjustment (0–10)</Th>
                  <Th>From deal</Th>
                  <Th>Date rated</Th>
                </tr>
              </thead>
              <tbody>
                {inherited_adjustments.map((r) => (
                  <tr
                    key={`${r.city}-${r.source_deal}`}
                    className="border-t"
                    style={{ borderColor: "var(--color-rule)" }}
                  >
                    <Td>{r.city}</Td>
                    <Td align="right">
                      <span style={{ color: "#0066CC", fontVariantNumeric: "tabular-nums" }}>
                        {r.value.toFixed(1)}
                      </span>
                    </Td>
                    <Td>{r.source_deal}</Td>
                    <Td>{new Date(r.date).toLocaleDateString("en-IE")}</Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="mt-5 text-[14px]" style={{ color: "var(--color-muted)" }}>
            No prior adjustments to inherit.
          </p>
        )}
      </section>

      {/* Section C — Walk Score */}
      <section
        className="mt-8 rounded-[6px] border p-7"
        style={{ backgroundColor: "var(--color-warm-panel)", borderColor: "var(--color-rule)" }}
      >
        <h2 className="font-serif text-[22px]" style={{ color: "var(--color-navy)" }}>
          Micro-location scores
        </h2>

        <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <KpiTile label="Streets scored" value={walk_score_summary.streets_scored.toString()} />
          <KpiTile label="Average score" value={walk_score_summary.average_score.toFixed(0)} />
          <KpiTile
            label="Failed to score"
            value={walk_score_summary.failed.length.toString()}
            danger={walk_score_summary.failed.length > 0}
          />
        </div>

        {walk_score_summary.failed.length > 0 && (
          <Accordion type="single" collapsible className="mt-6">
            <AccordionItem value="failures" className="border-b-0">
              <AccordionTrigger className="py-3 hover:no-underline">
                <span className="text-[14px]" style={{ color: "var(--color-body)" }}>
                  View failures{" "}
                  <span style={{ color: "var(--color-muted)" }}>({walk_score_summary.failed.length})</span>
                </span>
              </AccordionTrigger>
              <AccordionContent>
                <ReviewTable
                  head={["Address", "City", "Reason"]}
                  rows={walk_score_summary.failed.map((f) => [f.address, f.city, f.reason])}
                />
              </AccordionContent>
            </AccordionItem>
          </Accordion>
        )}
      </section>

      {/* Footer actions */}
      <div className="mt-10 flex flex-col-reverse items-stretch gap-3 sm:flex-row sm:items-center sm:justify-between">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-[4px] border px-6 py-3 text-[13px] font-semibold tracking-[0.15em] uppercase transition-colors hover:bg-white focus-visible:ring-2 focus-visible:ring-[var(--color-bronze)] focus-visible:outline-none"
          style={{ borderColor: "var(--color-rule)", color: "var(--color-navy)" }}
        >
          Cancel
        </button>

        <TooltipProvider delayDuration={150}>
          <Tooltip>
            <TooltipTrigger asChild>
              <span className={!allUnmatchedResolved ? "cursor-not-allowed" : ""}>
                <button
                  type="button"
                  onClick={handleFinalize}
                  disabled={!allUnmatchedResolved || finalizing}
                  aria-busy={finalizing}
                  className="inline-flex items-center justify-center gap-2 rounded-[4px] px-6 py-3 text-[13px] font-semibold tracking-[0.15em] uppercase transition-colors focus-visible:ring-2 focus-visible:ring-[var(--color-bronze)] focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-40"
                  style={{ backgroundColor: "var(--color-navy)", color: "var(--color-white)" }}
                >
                  {finalizing ? (
                    <>
                      <Loader2 size={14} className="animate-spin" aria-hidden />
                      <span>Finalizing...</span>
                    </>
                  ) : (
                    "Finalize and generate workbook"
                  )}
                </button>
              </span>
            </TooltipTrigger>
            {!allUnmatchedResolved && (
              <TooltipContent side="top">Resolve all unmatched cities to continue</TooltipContent>
            )}
          </Tooltip>
        </TooltipProvider>
      </div>
    </main>
  )
}

function KpiBadge({ label, tone }: { label: string; tone: "success" | "warning" | "danger" }) {
  const color =
    tone === "success" ? "var(--color-success)" : tone === "warning" ? "var(--color-warning)" : "var(--color-danger)"
  const bg =
    tone === "success"
      ? "rgba(45,106,79,0.12)"
      : tone === "warning"
        ? "rgba(176,128,56,0.14)"
        : "rgba(139,46,46,0.12)"
  return (
    <span
      className="inline-flex items-center rounded-[3px] px-2.5 py-1 text-[12px] font-semibold tracking-wide"
      style={{ color, backgroundColor: bg }}
    >
      {label}
    </span>
  )
}

function KpiTile({ label, value, danger }: { label: string; value: string; danger?: boolean }) {
  return (
    <div className="rounded-[4px] border bg-white p-5" style={{ borderColor: "var(--color-rule)" }}>
      <p
        className="font-serif text-[32px] leading-none"
        style={{
          color: danger ? "var(--color-danger)" : "var(--color-navy)",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </p>
      <p className="eyebrow mt-3">{label}</p>
    </div>
  )
}

function Th({ children, align = "left" }: { children: React.ReactNode; align?: "left" | "right" }) {
  return (
    <th
      className={`pb-2 pr-4 text-[12px] font-semibold tracking-wider uppercase ${align === "right" ? "text-right" : ""}`}
    >
      {children}
    </th>
  )
}
function Td({ children, align = "left" }: { children: React.ReactNode; align?: "left" | "right" }) {
  return (
    <td
      className={`py-3 pr-4 align-middle ${align === "right" ? "text-right" : ""}`}
      style={{
        color: "var(--color-body)",
        fontVariantNumeric: align === "right" ? "tabular-nums" : "normal",
      }}
    >
      {children}
    </td>
  )
}

function ReviewTable({
  head,
  rows,
  rightAlignCols = [],
}: {
  head: string[]
  rows: string[][]
  rightAlignCols?: number[]
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[14px]">
        <thead>
          <tr className="text-left" style={{ color: "var(--color-muted)" }}>
            {head.map((h, i) => (
              <Th key={h} align={rightAlignCols.includes(i) ? "right" : "left"}>
                {h}
              </Th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-t" style={{ borderColor: "var(--color-rule)" }}>
              {row.map((cell, j) => (
                <Td key={j} align={rightAlignCols.includes(j) ? "right" : "left"}>
                  {cell}
                </Td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
