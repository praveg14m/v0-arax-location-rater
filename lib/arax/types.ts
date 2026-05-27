export type JobStatus =
  | "queued"
  | "parsing"
  | "reconciling"
  | "inheriting"
  | "scoring"
  | "review_required"
  | "building"
  | "complete"
  | "error"

export type StepKey = "parse" | "reconcile" | "inherit" | "walkscore" | "build"
export type StepState = "pending" | "active" | "complete" | "warning"

export type StepProgress = {
  state: StepState
  message: string
}

export type ExactMatch = {
  raw_city: string
  mapped_to: string
  addresses: number
  annual_rent: number
}

export type FuzzyMatch = {
  raw_city: string
  proposed_match: string
  confidence: number // 0-100
  candidates: string[]
  addresses: number
  annual_rent: number
}

export type UnmatchedCity = {
  raw_city: string
  candidates: string[]
  addresses: number
  annual_rent: number
}

export type InheritedAdjustment = {
  city: string
  adjustment: number // 0-10
  from_deal: string
  date_rated: string // ISO
}

export type WalkScoreFailure = {
  address: string
  city: string
  reason: string
}

export type ReviewPayload = {
  exact_matches: ExactMatch[]
  fuzzy_matches: FuzzyMatch[]
  unmatched_cities: UnmatchedCity[]
  inherited: InheritedAdjustment[]
  walkscore: {
    streets_scored: number
    average_score: number
    failed: number
    failures: WalkScoreFailure[]
  }
}

export type RunSummary = {
  deal_name: string
  cities_scored: number
  unique_streets_called: number
  walkscore_successes: number
  walkscore_failures: number
  prior_adjustments_inherited: number
  total_processing_time_seconds: number
}

export type StatusResponse = {
  job_id: string
  status: JobStatus
  steps: Record<StepKey, StepProgress>
  review?: ReviewPayload
  filename?: string
  summary?: RunSummary
  error?: string
}
