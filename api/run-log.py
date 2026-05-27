# api/run-log.py
# GET /api/run-log?job_id=...
# Returns text/plain run log. Mock: a few descriptive lines.

from __future__ import annotations

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from _state import get_job


class handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        qs = parse_qs(urlparse(self.path).query)
        job_id = (qs.get("job_id") or [""])[0]
        if not job_id:
            self.send_response(400)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Missing job_id")
            return

        job = get_job(job_id)
        if job is None:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Job not found")
            return

        deal = job.get("deal_name", "Unknown")
        created = datetime.fromtimestamp(job["created_at"], tz=timezone.utc).isoformat()
        lines = [
            f"Arax Ratings run log — {deal}",
            f"Job ID:        {job_id}",
            f"Started (UTC): {created}",
            f"Source file:   {job.get('file_name', '?')} ({len(job.get('file_bytes', b''))} bytes)",
            "",
            "Step 1 — Parsed rent roll: 171 addresses across 9 cities.",
            "Step 2 — City matching: 5 exact, 3 fuzzy, 1 unmatched.",
            "Step 3 — Inherited 3 prior adjustments from 2 source deals.",
            "Step 4 — Walk Score: 28 streets scored, average 62, 2 failures.",
            "Step 5 — Workbook written with master macros preserved.",
        ]
        body = ("\n".join(lines) + "\n").encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="run-log-{job_id}.txt"',
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
