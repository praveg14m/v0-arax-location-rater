# api/process.py
# POST /api/process
# multipart/form-data:
#   - file:      the rent roll workbook (.xlsx or .xlsm)
#   - deal_name: human-readable deal label
#
# The file is read fully into memory and stored on the in-memory job state
# object alongside the deal name. No external storage is used. See _state.py
# for the production migration path (Vercel KV / managed cache).
#
# Response: { "job_id": str, "status": "queued" }

from __future__ import annotations

import json
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler

from _state import new_job_id, set_job

MAX_FILE_BYTES = 4 * 1024 * 1024  # 4 MB hard ceiling; Vercel request body cap is 4.5 MB
ALLOWED_EXTS = (".xlsx", ".xlsm")


def _json(handler: BaseHTTPRequestHandler, status: int, body: dict) -> None:
    payload = json.dumps(body).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def _parse_multipart(content_type: str, raw: bytes) -> dict[str, dict]:
    """Tiny RFC 7578 multipart parser. Returns {field_name: {filename, value}}.

    Uses python-multipart for robustness.
    """
    from multipart import MultipartParser  # python-multipart
    from io import BytesIO

    # Extract boundary
    parts = [p.strip() for p in content_type.split(";")]
    boundary = None
    for p in parts:
        if p.lower().startswith("boundary="):
            boundary = p.split("=", 1)[1].strip().strip('"')
            break
    if not boundary:
        raise ValueError("Missing multipart boundary")

    out: dict[str, dict] = {}
    parser = MultipartParser(BytesIO(raw), boundary)
    for part in parser:
        name = part.name or ""
        if part.filename:
            out[name] = {"filename": part.filename, "value": part.raw}
        else:
            out[name] = {"filename": None, "value": part.value}
    return out


class handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 — Vercel handler convention
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
            _json(
                self,
                413,
                {"error": "File exceeds 4MB. Please contact engineering for large-portfolio support."},
            )
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
            _json(
                self,
                400,
                {"error": "Unsupported file type. Upload an .xlsx or .xlsm rent roll."},
            )
            return

        file_bytes: bytes = file_part["value"]
        if len(file_bytes) > MAX_FILE_BYTES:
            _json(
                self,
                413,
                {"error": "File exceeds 4MB. Please contact engineering for large-portfolio support."},
            )
            return

        deal_name = (
            deal_part["value"].decode("utf-8") if isinstance(deal_part["value"], bytes) else deal_part["value"]
        ).strip()

        job_id = new_job_id()
        created_at = time.time()
        # Workbook filename uses YYMMDD per Arax convention.
        date_prefix = datetime.utcfromtimestamp(created_at).strftime("%y%m%d")
        safe_deal = "".join(c for c in deal_name if c.isalnum() or c in ("-", "_")) or "Deal"
        workbook_filename = f"{date_prefix}_Ratings_{safe_deal}.xlsm"

        set_job(
            job_id,
            {
                "job_id": job_id,
                "deal_name": deal_name,
                "file_bytes": file_bytes,
                "file_name": filename,
                "created_at": created_at,
                "status": "queued",
                "current_step": 1,
                "workbook_filename": workbook_filename,
            },
        )

        # NOTE: For the mock, the "pipeline" is purely time-driven (see _state.compute_status).
        # The real implementation will run the openpyxl + Walk Score pipeline here, writing
        # progress back onto the job dict. Because Vercel functions can run up to 800s, the
        # entire pipeline (including the human-review gate via /api/confirm) fits inside one
        # function invocation lifetime.

        _json(self, 200, {"job_id": job_id, "status": "queued"})
