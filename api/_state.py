# api/_state.py
# Shared in-memory job store + mock progression logic.
#
# IMPORTANT: This is a module-level dict shared across requests within a single
# serverless worker instance. In Vercel's serverless model each invocation may
# land on a different worker, so this is unreliable across cold starts and
# horizontal scale.
#
# TODO(prod): replace with Vercel KV (Upstash Redis) or a managed cache so job
# state survives cold starts and is consistent across workers. The interface
# (`get_job`, `set_job`, `update_job`) is intentionally narrow so swapping the
# backing store is a one-file change.

from __future__ import annotations

import time
import uuid
from threading import Lock
from typing import Any

# job_id -> job dict
_JOBS: dict[str, dict[str, Any]] = {}
_LOCK = Lock()


def new_job_id() -> str:
    return uuid.uuid4().hex


def set_job(job_id: str, data: dict[str, Any]) -> None:
    with _LOCK:
        _JOBS[job_id] = data


def get_job(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        return _JOBS.get(job_id)


def update_job(job_id: str, **fields: Any) -> dict[str, Any] | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return None
        job.update(fields)
        return job


# ---------------------------------------------------------------------------
# Mock progression
# ---------------------------------------------------------------------------
#
# Timeline (relative to job.created_at, in seconds):
#   0 .. 3   parsing      step 1 active
#   3 .. 6   matching     step 2 active
#   6 .. 8   inheriting   step 3 active
#   8 .. 14  scoring      step 4 active (count 1 -> 28)
#   14+      review_required (with mock review_data)
#
# After /api/confirm is called, the job is flipped to "writing" with
# `confirmed_at` recorded. Then:
#   confirmed_at .. confirmed_at+3   writing       step 5 active
#   confirmed_at+3+                  complete      result populated

MOCK_REVIEW_DATA: dict[str, Any] = {
    "cities": {
        "exact_matches": [
            {"raw": "Essen", "mapped": "Essen", "address_count": 47, "annual_rent": 1_842_000},
            {"raw": "Dortmund", "mapped": "Dortmund", "address_count": 38, "annual_rent": 1_456_000},
            {"raw": "Gelsenkirchen", "mapped": "Gelsenkirchen", "address_count": 22, "annual_rent": 612_000},
            {"raw": "Bochum", "mapped": "Bochum", "address_count": 19, "annual_rent": 731_000},
            {"raw": "Duisburg", "mapped": "Duisburg", "address_count": 15, "annual_rent": 488_000},
        ],
        "fuzzy_matches": [
            {
                "raw": "Köln",
                "proposed": "Cologne",
                "confidence": 94,
                "alternatives": ["Cologne", "Köln-Mülheim", "Köln-Ehrenfeld"],
                "address_count": 12,
                "annual_rent": 524_000,
            },
            {
                "raw": "Düsseldorf-Bilk",
                "proposed": "Düsseldorf",
                "confidence": 88,
                "alternatives": ["Düsseldorf", "Düsseldorf-Oberbilk", "Neuss"],
                "address_count": 8,
                "annual_rent": 412_000,
            },
            {
                "raw": "Mönchengladbach",
                "proposed": "Moenchengladbach",
                "confidence": 96,
                "alternatives": ["Moenchengladbach", "Mönchengladbach-Rheydt", "Viersen"],
                "address_count": 6,
                "annual_rent": 198_000,
            },
        ],
        "unmatched": [
            {
                "raw": "Wuppertal-Elberfeld",
                "candidates": [
                    "Wuppertal",
                    "Wuppertal-Barmen",
                    "Wuppertal-Vohwinkel",
                    "Solingen",
                    "Remscheid",
                ],
                "address_count": 4,
                "annual_rent": 142_000,
            }
        ],
    },
    "inherited_adjustments": [
        {"city": "Essen", "value": 7.5, "source_deal": "Project Hawk", "date": "2025-08-14"},
        {"city": "Dortmund", "value": 6.0, "source_deal": "Project Hawk", "date": "2025-08-14"},
        {"city": "Duisburg", "value": 5.5, "source_deal": "Project Eagle", "date": "2024-11-22"},
    ],
    "walk_score_summary": {
        "streets_scored": 28,
        "average_score": 62,
        "failed": [
            {
                "address": "Hauptstrasse 12",
                "city": "Wuppertal-Elberfeld",
                "reason": "address not found in Germany",
            },
            {
                "address": "Bahnhofstrasse 3",
                "city": "Essen",
                "reason": "rate limit",
            },
        ],
    },
}


def _step_results_for(elapsed: float) -> dict[str, Any]:
    """Cumulative step results visible at a given elapsed time."""
    out: dict[str, Any] = {}
    if elapsed >= 3:
        out["step_1"] = {"addresses": 171, "cities": 9}
    if elapsed >= 6:
        out["step_2"] = {"exact": 5, "fuzzy": 3, "unmatched": 1}
    if elapsed >= 8:
        out["step_3"] = {"cities_inherited": 3, "source_deals": 2}
    if elapsed >= 14:
        out["step_4"] = {"scored": 28, "failed": 2}
    return out


def compute_status(job: dict[str, Any]) -> dict[str, Any]:
    """Translate a job dict into the public status payload."""
    job_id: str = job["job_id"]
    now = time.time()
    elapsed = now - job["created_at"]

    # Terminal states recorded on the job take priority.
    if job.get("status") == "failed":
        return {
            "job_id": job_id,
            "status": "failed",
            "current_step": job.get("current_step", 1),
            "error": job.get("error", "Unknown error"),
        }

    confirmed_at = job.get("confirmed_at")
    if confirmed_at is not None:
        confirm_elapsed = now - confirmed_at
        if confirm_elapsed < 3:
            return {
                "job_id": job_id,
                "status": "writing",
                "current_step": 5,
                "step_results": _step_results_for(99),
            }
        # Complete
        result = job.get("result")
        if result is None:
            # Stamp result on first complete observation so subsequent calls are stable.
            result = {
                "workbook_filename": job["workbook_filename"],
                "run_summary": {
                    "cities_scored": 9,
                    "unique_streets": 28,
                    "walk_score_successes": 26,
                    "walk_score_failures": 2,
                    "inherited_adjustments": 3,
                    "processing_time_seconds": round(elapsed, 1),
                },
            }
            job["result"] = result
            job["status"] = "complete"
        return {
            "job_id": job_id,
            "status": "complete",
            "current_step": 5,
            "step_results": _step_results_for(99),
            "result": result,
        }

    # Pre-review timeline
    if elapsed < 3:
        return {
            "job_id": job_id,
            "status": "parsing",
            "current_step": 1,
            "step_results": _step_results_for(elapsed),
        }
    if elapsed < 6:
        return {
            "job_id": job_id,
            "status": "matching",
            "current_step": 2,
            "step_results": _step_results_for(elapsed),
        }
    if elapsed < 8:
        return {
            "job_id": job_id,
            "status": "inheriting",
            "current_step": 3,
            "step_results": _step_results_for(elapsed),
        }
    if elapsed < 14:
        # Scoring with progress 1..28 spread across 6s.
        frac = (elapsed - 8) / 6
        current = max(1, min(28, int(frac * 28) + 1))
        return {
            "job_id": job_id,
            "status": "scoring",
            "current_step": 4,
            "step_progress": {"current": current, "total": 28},
            "step_results": _step_results_for(elapsed),
        }

    # >= 14s: awaiting human review.
    return {
        "job_id": job_id,
        "status": "review_required",
        "current_step": 4,
        "step_results": _step_results_for(elapsed),
        "review_data": MOCK_REVIEW_DATA,
    }
