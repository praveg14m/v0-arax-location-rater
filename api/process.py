# api/process.py
# POST /api/process
# multipart/form-data:
#   - file:      the rent roll workbook (.xlsx or .xlsm)
#   - deal_name: human-readable deal label
#
# Runs the full pipeline up to the human-review gate:
#   1. parse rent roll  (rule-based + LLM fallback)
#   2. match cities     (three-tier matcher)
#   3. inherit prior Arax Adjustments
#   4. Walk Score every unique address (async)
#   -> review_required
#
# After /api/confirm is called, /api/confirm runs step 5 (workbook write).
#
# Response: { "job_id": str, "status": "queued" }
# The pipeline runs synchronously in this same invocation, updating the
# job dict as it progresses. The frontend polls /api/status to see the
# progress. Vercel function timeout (800s) is plenty for typical portfolios.

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import traceback
from collections import defaultdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from pathlib import Path

# Make lib/python/ importable
_HERE = Path(__file__).parent.resolve()
_REPO_ROOT = _HERE.parent
sys.path.insert(0, str(_REPO_ROOT / "lib" / "python"))

from _state import new_job_id, set_job, update_job  # noqa: E402

MAX_FILE_BYTES = 4 * 1024 * 1024
ALLOWED_EXTS = (".xlsx", ".xlsm")
MASTER_WORKBOOK_PATH = _REPO_ROOT / "data" / "master.xlsm"
WALK_SCORE_API_KEY_ENV = "WALK_SCORE_API_KEY"


def _json(handler: BaseHTTPRequestHandler, status: int, body: dict) -> None:
    payload = json.dumps(body).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def _parse_multipart(content_type: str, raw: bytes) -> dict:
    from multipart import MultipartParser
    from io import BytesIO

    parts = [p.strip() for p in content_type.split(";")]
    boundary = None
    for p in parts:
        if p.lower().startswith("boundary="):
            boundary = p.split("=", 1)[1].strip().strip('"')
            break
    if not boundary:
        raise ValueError("Missing multipart boundary")

    out: dict = {}
    parser = MultipartParser(BytesIO(raw), boundary)
    for part in parser:
        name = part.name or ""
        if part.filename:
            out[name] = {"filename": part.filename, "value": part.raw}
        else:
            out[name] = {"filename": None, "value": part.value}
    return out


# ---------------------------------------------------------------------------
# The actual pipeline
# ---------------------------------------------------------------------------


def _run_pipeline(job_id: str, deal_name: str, file_bytes: bytes) -> None:
    """Run steps 1-4 of the pipeline synchronously, updating job state as we go.

    On success the job is left in status="review_required" with review_data
    populated. On failure the job is marked status="failed" with an error string.
    """
    from parse_rent_roll import parse_rent_roll  # noqa: E402
    from city_mapping import load_city_mapping, match_all_cities  # noqa: E402
    from inheritance import lookup_prior_adjustments  # noqa: E402
    from walk_score import score_addresses  # noqa: E402

    audit: list[str] = []

    def _step(step_num: int, status: str, **extra) -> None:
        update_job(
            job_id,
            current_step=step_num,
            status=status,
            audit_log=list(audit),  # snapshot, not reference
            **extra,
        )

    try:
        # Step 1: parse rent roll
        _step(1, "parsing")
        parsed = parse_rent_roll(file_bytes)
        audit.extend(parsed.audit_log)
        addresses = parsed.addresses
        unique_cities_raw = list({a.city for a in addresses})
        step_1_results = {"addresses": len(addresses), "cities": len(unique_cities_raw)}
        update_job(job_id, step_1=step_1_results, parsed_addresses=[
            {
                "street": a.street, "city": a.city, "area_sqm": a.area_sqm,
                "annual_rent": a.annual_rent, "unit_type": a.unit_type,
                "row_index": a.row_index,
            } for a in addresses
        ])

        # Step 2: match cities
        _step(2, "matching", step_1=step_1_results)
        if not MASTER_WORKBOOK_PATH.exists():
            raise FileNotFoundError(f"Master workbook not found at {MASTER_WORKBOOK_PATH}")
        with open(MASTER_WORKBOOK_PATH, "rb") as f:
            master_bytes = f.read()
        mapping = load_city_mapping(master_bytes)
        match_summary = match_all_cities(unique_cities_raw, mapping)
        audit.extend(match_summary.audit_log)
        step_2_results = {
            "exact": len(match_summary.exact_matches),
            "fuzzy": len(match_summary.fuzzy_matches),
            "unmatched": len(match_summary.unmatched),
        }

        # Build per-city rent aggregates and per-address city remap
        # For the proposed match (fuzzy / unmatched candidates), we use the
        # tool's BEST GUESS; the user can override in the review screen.
        city_remap: dict[str, str | None] = {}
        for m in match_summary.exact_matches:
            city_remap[m.raw] = m.mapped
        for m in match_summary.fuzzy_matches:
            city_remap[m.raw] = m.proposed
        for m in match_summary.unmatched:
            city_remap[m.raw] = None  # blocked - user must resolve

        # Aggregate per-city for the review screen
        city_address_counts = defaultdict(int)
        city_annual_rent = defaultdict(float)
        for a in addresses:
            city_address_counts[a.city] += 1
            city_annual_rent[a.city] += a.annual_rent

        review_cities = {
            "exact_matches": [
                {
                    "raw": m.raw, "mapped": m.mapped,
                    "address_count": city_address_counts[m.raw],
                    "annual_rent": round(city_annual_rent[m.raw], 2),
                }
                for m in match_summary.exact_matches
            ],
            "fuzzy_matches": [
                {
                    "raw": m.raw, "proposed": m.proposed,
                    "confidence": m.confidence, "alternatives": m.alternatives,
                    "address_count": city_address_counts[m.raw],
                    "annual_rent": round(city_annual_rent[m.raw], 2),
                }
                for m in match_summary.fuzzy_matches
            ],
            "unmatched": [
                {
                    "raw": m.raw, "candidates": m.candidates,
                    "address_count": city_address_counts[m.raw],
                    "annual_rent": round(city_annual_rent[m.raw], 2),
                }
                for m in match_summary.unmatched
            ],
        }

        # Step 3: inheritance
        _step(3, "inheriting", step_1=step_1_results, step_2=step_2_results)
        inheritance = lookup_prior_adjustments()  # uses DEALS_FOLDER env var
        audit.extend(inheritance.audit_log)
        # Filter inherited adjustments to ONLY cities in this deal
        # (canonical names of matched cities)
        deal_canonical_cities = set()
        for r in match_summary.exact_matches:
            deal_canonical_cities.add(r.mapped)
        for r in match_summary.fuzzy_matches:
            deal_canonical_cities.add(r.proposed)
        relevant_inheritance = {
            city: adj for city, adj in inheritance.adjustments.items()
            if city in deal_canonical_cities
        }
        review_inherited = [
            {
                "city": city, "value": adj.value,
                "source_deal": adj.source_deal,
                "date": adj.date_rated.isoformat(),
            }
            for city, adj in relevant_inheritance.items()
        ]
        step_3_results = {
            "cities_inherited": len(relevant_inheritance),
            "source_deals": len(inheritance.source_deals_scanned),
        }

        # Step 4: Walk Score
        # Build unique (street, mapped_city) pairs - only for matched cities
        _step(4, "scoring",
              step_1=step_1_results, step_2=step_2_results, step_3=step_3_results)
        api_key = os.environ.get(WALK_SCORE_API_KEY_ENV, "")
        unique_pairs: list[tuple[str, str]] = []
        seen_pairs: set[tuple[str, str]] = set()
        for a in addresses:
            mapped = city_remap.get(a.city)
            if not mapped:
                continue
            key = (a.street, mapped)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            unique_pairs.append(key)

        def _progress(current: int, total: int) -> None:
            update_job(job_id, step_progress={"current": current, "total": total})

        update_job(job_id, step_progress={"current": 0, "total": len(unique_pairs)})

        if api_key and unique_pairs:
            walk_summary = asyncio.run(score_addresses(unique_pairs, api_key, _progress))
            audit.extend(walk_summary.audit_log)
            scores = walk_summary.scores
        else:
            # No API key OR no pairs to score - skip with a clear audit line
            scores = []
            if not api_key:
                audit.append("Walk Score: WALK_SCORE_API_KEY not set; skipping (scores will be blank)")

        # Build a lookup (street, city) -> score for the writer to use later
        score_lookup: dict[tuple[str, str], int | None] = {}
        failures: list[dict] = []
        for s in scores:
            score_lookup[(s.street, s.city)] = s.score
            if s.score is None and s.reason:
                failures.append({"address": s.street, "city": s.city, "reason": s.reason})

        successful = [s.score for s in scores if s.score is not None]
        walk_score_summary = {
            "streets_scored": len(successful),
            "average_score": round(sum(successful) / len(successful), 1) if successful else 0,
            "failed": failures,
        }
        step_4_results = {"scored": len(successful), "failed": len(failures)}

        # Snapshot everything we'll need for confirm.py
        review_data = {
            "cities": review_cities,
            "inherited_adjustments": review_inherited,
            "walk_score_summary": walk_score_summary,
        }

        update_job(
            job_id,
            status="review_required",
            current_step=4,
            step_1=step_1_results,
            step_2=step_2_results,
            step_3=step_3_results,
            step_4=step_4_results,
            audit_log=list(audit),
            review_data=review_data,
            # Pipeline artifacts that confirm.py will use
            _city_remap=city_remap,
            _score_lookup_pairs=[
                {"street": k[0], "city": k[1], "score": v}
                for k, v in score_lookup.items()
            ],
            _inherited_for_writer=[
                {
                    "city": city, "value": adj.value,
                    "source_deal": adj.source_deal,
                    "date_rated": adj.date_rated.isoformat(),
                }
                for city, adj in relevant_inheritance.items()
            ],
        )
    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc()
        audit.append(f"Pipeline failed: {type(e).__name__}: {e}")
        update_job(
            job_id,
            status="failed",
            error=f"{type(e).__name__}: {e}",
            traceback=tb,
            audit_log=list(audit),
        )


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("multipart/form-data"):
            _json(self, 400, {"error": "Content-Type must be multipart/form-data"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            _json(self, 400, {"error": "Invalid Content-Length"})
            return
        if length <= 0:
            _json(self, 400, {"error": "Empty request body"})
            return
        if length > MAX_FILE_BYTES:
            _json(self, 413,
                  {"error": "File exceeds 4MB. Please contact engineering for large-portfolio support."})
            return
        raw = self.rfile.read(length)
        try:
            fields = _parse_multipart(content_type, raw)
        except Exception as e:  # noqa: BLE001
            _json(self, 400, {"error": f"Malformed multipart payload: {e}"})
            return

        file_part = fields.get("file")
        deal_part = fields.get("deal_name")
        if not file_part or not file_part.get("filename"):
            _json(self, 400, {"error": "Missing 'file' field"})
            return
        if not deal_part or not deal_part.get("value"):
            _json(self, 400, {"error": "Missing 'deal_name' field"})
            return

        filename: str = file_part["filename"]
        if not filename.lower().endswith(ALLOWED_EXTS):
            _json(self, 400,
                  {"error": "Unsupported file type. Upload an .xlsx or .xlsm rent roll."})
            return

        file_bytes: bytes = file_part["value"]
        if len(file_bytes) > MAX_FILE_BYTES:
            _json(self, 413,
                  {"error": "File exceeds 4MB. Please contact engineering for large-portfolio support."})
            return

        deal_name = (
            deal_part["value"].decode("utf-8") if isinstance(deal_part["value"], bytes) else deal_part["value"]
        ).strip()

        job_id = new_job_id()
        created_at = time.time()
        date_prefix = datetime.utcfromtimestamp(created_at).strftime("%y%m%d")
        safe_deal = "".join(c for c in deal_name if c.isalnum() or c in ("-", "_")) or "Deal"
        workbook_filename = f"{date_prefix}_Ratings_{safe_deal}.xlsm"

        set_job(job_id, {
            "job_id": job_id,
            "deal_name": deal_name,
            "file_bytes": file_bytes,
            "file_name": filename,
            "created_at": created_at,
            "status": "queued",
            "current_step": 1,
            "workbook_filename": workbook_filename,
            "audit_log": [],
        })

        # Reply BEFORE running the pipeline so the frontend gets a job_id and starts polling.
        # The pipeline runs AFTER the response is sent. Vercel keeps the function alive
        # until do_POST returns - so the pipeline finishes before the function shuts down.
        # The client connection may close from the frontend's perspective once the
        # response is flushed, but that's fine - the frontend polls /api/status
        # for progress and doesn't care that the original POST connection ended.
        _json(self, 200, {"job_id": job_id, "status": "queued"})
        try:
            self.wfile.flush()
        except Exception:  # noqa: BLE001
            pass

        try:
            _run_pipeline(job_id, deal_name, file_bytes)
        except Exception as e:  # noqa: BLE001
            update_job(job_id, status="failed", error=f"{type(e).__name__}: {e}")
