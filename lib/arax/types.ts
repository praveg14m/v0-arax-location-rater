// Authoritative contract — mirrors api/_state.compute_status.
// Any change here MUST be made in lockstep with the Python side.

export type JobStatus =
  | "queued"
  | "parsing"
  | "matching"
  | "inheriting"
  | "scoring"
  | "writing"
  | "review_required"
  | "complete"
  | "failed"

export type StepNumber = 1 | 2 | 3 | 4 | 5

export type StepProgress = {
  current: number
  total: number
}

export type StepResults = {
  step_1?: { addresses: number; cities: number }
  step_2?: { exact: number; fuzzy: number; unmatched: number }
  step_3?: { cities_inherited: number; source_deals: number }
  step_4?: { scored: number; failed: number }
}

export type ExactMatch = {
  raw: string
  mapped: string
  address_count: number
  annual_rent: number
}

export type FuzzyMatch = {
  raw: string
  proposed: string
  confidence: number // 0–100
  alternatives: string[]
  address_count: number
  annual_rent: number
}

export type UnmatchedCity = {
  raw: string
  candidates: string[]
  address_count: number
  annual_rent: number
}

export type InheritedAdjustment = {
  city: string
  value: number // 0–10
  source_deal: string
  date: string // ISO yyyy-mm-dd
}

export type WalkScoreFailure = {
  address: string
  city: string
  reason: string
}

export type WalkScoreSummary = {
  streets_scored: number
  average_score: number
  failed: WalkScoreFailure[]
}

export type ReviewData = {
  cities: {
    exact_matches: ExactMatch[]
    fuzzy_matches: FuzzyMatch[]
    unmatched: UnmatchedCity[]
  }
  inherited_adjustments: InheritedAdjustment[]
  walk_score_summary: WalkScoreSummary
}

export type RunSummary = {
  cities_scored: number
  unique_streets: number
  walk_score_successes: number
  walk_score_failures: number
  inherited_adjustments: number
  processing_time_seconds: number
}

export type JobResult = {
  workbook_filename: string
  run_summary: RunSummary
}

export type StatusResponse = {
  job_id: string
  status: JobStatus
  current_step: StepNumber
  step_progress?: StepProgress
  step_results?: StepResults
  review_data?: ReviewData
  result?: JobResult
  error?: string
}
