# api/_state.py
# In-memory job store. job_id -> job dict.
#
# IMPORTANT: This is a module-level dict shared across requests within a single
# serverless worker instance. In Vercel's serverless model each invocation may
# land on a different worker, so this is unreliable across cold starts and
# horizontal scale. For an interview demo on a warm Pro/Enterprise instance
# this is fine; for production migrate to Vercel KV (Upstash Redis) or a
# managed cache. The interface (`get_job`, `set_job`, `update_job`) is
# intentionally narrow so swapping the backing store is a one-file change.

from __future__ import annotations

import uuid
from threading import Lock
from typing import Any

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
# Public status payload
# ---------------------------------------------------------------------------
#
# The pipeline (in process.py / confirm.py) writes progress and review_data
# directly onto the job dict. This function projects that into the schema
# the frontend expects.


def compute_status(job: dict[str, Any]) -> dict[str, Any]:
    """Translate a job dict into the public status payload."""
    job_id: str = job["job_id"]
    status = job.get("status", "queued")
    current_step = job.get("current_step", 1)

    out: dict[str, Any] = {
        "job_id": job_id,
        "status": status,
        "current_step": current_step,
    }

    # step_results - cumulative per-step counts (visible to the timeline)
    step_results: dict[str, Any] = {}
    for k in ("step_1", "step_2", "step_3", "step_4"):
        if k in job:
            step_results[k] = job[k]
    if step_results:
        out["step_results"] = step_results

    # step_progress - for the scoring step (Walk Score current/total)
    if "step_progress" in job:
        out["step_progress"] = job["step_progress"]

    # review_data - populated when status="review_required"
    if "review_data" in job and status in ("review_required", "writing", "complete"):
        out["review_data"] = job["review_data"]

    # result - populated when status="complete"
    if "result" in job and status == "complete":
        out["result"] = job["result"]

    # error - populated when status="failed"
    if status == "failed":
        out["error"] = job.get("error", "Unknown error")

    return out
