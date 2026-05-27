# api/confirm.py
# POST /api/confirm
# Body: { "job_id": str, "city_overrides": { raw_city: chosen_mapping } }
#
# Reads the job state (which was populated by /api/process up to the review
# gate), applies the user's city overrides, and writes the final workbook.
# Synchronous - the workbook write takes a few seconds.
#
# Response: { "status": "writing" } sent immediately, then the workbook is
# written and the job is flipped to "complete".

from __future__ import annotations

import io
import json
import sys
import time
import traceback
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler
from pathlib import Path

_HERE = Path(__file__).parent.resolve()
_REPO_ROOT = _HERE.parent
sys.path.insert(0, str(_REPO_ROOT / "lib" / "python"))

from _state import get_job, update_job  # noqa: E402

MASTER_WORKBOOK_PATH = _REPO_ROOT / "data" / "master.xlsm"


def _json(handler: BaseHTTPRequestHandler, status: int, body: dict) -> None:
    payload = json.dumps(body).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def _write_workbook(job_id: str, overrides: dict[str, str]) -> None:
    """Build the working-copy workbook for the job.

    Applies the user's city overrides on top of the tool's proposed mappings,
    then assembles CityRow + TenancySchedRow lists and calls write_ratings_workbook.
    On completion writes job.result and flips status to 'complete'.
    """
    from collections import defaultdict
    from workbook_writer import (  # noqa: E402
        write_ratings_workbook, CityRow, TenancySchedRow, InheritedAdjustment,
    )

    job = get_job(job_id)
    if job is None:
        return

    audit: list[str] = list(job.get("audit_log", []))
    audit.append(f"Confirm: starting workbook write for deal '{job['deal_name']}'")

    try:
        # Build the final city remap from tool's choices + user overrides
        tool_remap: dict[str, str | None] = job.get("_city_remap", {})
        final_remap: dict[str, str] = {}
        for raw, tool_choice in tool_remap.items():
            override = overrides.get(raw)
            if override:
                final_remap[raw] = override
            elif tool_choice:
                final_remap[raw] = tool_choice
            # else: still unmatched; will be skipped below
        audit.append(
            f"Confirm: city remap = {len(final_remap)} entries "
            f"({len(overrides)} user overrides applied)"
        )

        # Build parsed_addresses list back
        addresses_raw = job.get("parsed_addresses", [])

        # Aggregate per-city annual rent for sort order
        city_totals: dict[str, float] = defaultdict(float)
        for a in addresses_raw:
            mapped = final_remap.get(a["city"])
            if mapped:
                city_totals[mapped] += a["annual_rent"]

        cities = [
            CityRow(raw_name=mapped, mapped_name=mapped, total_annual_rent=total)
            for mapped, total in city_totals.items()
        ]
        if not cities:
            raise RuntimeError(
                "No cities mapped successfully. All city matches were rejected or unmatched."
            )

        # Build score lookup
        score_lookup: dict[tuple[str, str], int | None] = {}
        for entry in job.get("_score_lookup_pairs", []):
            score_lookup[(entry["street"], entry["city"])] = entry["score"]

        # Build inheritance dict
        inherited: dict[str, InheritedAdjustment] = {}
        for entry in job.get("_inherited_for_writer", []):
            inherited[entry["city"]] = InheritedAdjustment(
                city=entry["city"],
                value=entry["value"],
                source_deal=entry["source_deal"],
                date_rated=entry["date_rated"],
            )

        # Build tenancy schedule rows
        tenancy_rows: list[TenancySchedRow] = []
        for a in addresses_raw:
            mapped = final_remap.get(a["city"])
            if not mapped:
                continue
            ws = score_lookup.get((a["street"], mapped))
            tenancy_rows.append(TenancySchedRow(
                deal=job["deal_name"],
                addresses=a["street"],
                city_and_street=f"{mapped}, {a['street']}",
                city=mapped,
                area=a["area_sqm"],
                rent=a["annual_rent"],
                walk_score=ws,
            ))

        # Load master and write
        with open(MASTER_WORKBOOK_PATH, "rb") as f:
            master_bytes = f.read()
        write_result = write_ratings_workbook(
            master_xlsm_bytes=master_bytes,
            deal_name=job["deal_name"],
            cities=cities,
            tenancy_rows=tenancy_rows,
            inherited=inherited,
        )
        audit.extend(write_result.audit_log)

        # Stamp on job
        successful_scores = [
            v for v in score_lookup.values() if v is not None
        ]
        run_summary = {
            "cities_scored": len(cities),
            "unique_streets": len(score_lookup),
            "walk_score_successes": len(successful_scores),
            "walk_score_failures": sum(1 for v in score_lookup.values() if v is None),
            "inherited_adjustments": len(inherited),
            "processing_time_seconds": round(time.time() - job["created_at"], 1),
        }

        update_job(
            job_id,
            status="complete",
            current_step=5,
            workbook_bytes=write_result.workbook_bytes,
            audit_log=list(audit),
            result={
                "workbook_filename": write_result.filename,
                "run_summary": run_summary,
            },
        )

    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc()
        audit.append(f"Confirm failed: {type(e).__name__}: {e}")
        update_job(
            job_id,
            status="failed",
            error=f"{type(e).__name__}: {e}",
            traceback=tb,
            audit_log=list(audit),
        )


class handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            _json(self, 400, {"error": "Invalid Content-Length"})
            return
        if length <= 0:
            _json(self, 400, {"error": "Empty body"})
            return
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:  # noqa: BLE001
            _json(self, 400, {"error": "Body must be JSON"})
            return

        job_id = body.get("job_id")
        overrides = body.get("city_overrides") or {}
        if not isinstance(job_id, str) or not job_id:
            _json(self, 400, {"error": "Missing job_id"})
            return
        if not isinstance(overrides, dict):
            _json(self, 400, {"error": "city_overrides must be an object"})
            return

        job = get_job(job_id)
        if job is None:
            _json(self, 404, {"error": "Job not found"})
            return

        # Flip to "writing" first so a status poll between now and the
        # workbook write shows the right state
        update_job(job_id, status="writing", current_step=5, confirmed_at=time.time(),
                   city_overrides=overrides)
        # Reply immediately, then do the work
        _json(self, 200, {"status": "writing"})
        _write_workbook(job_id, overrides)
