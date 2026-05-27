# api/run-log.py
# GET /api/run-log?job_id=...
# Returns the full audit log of the job as text/plain.

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
        audit = job.get("audit_log", [])

        lines = [
            f"Arax Location Rater — Run Log",
            f"=============================",
            f"Deal:          {deal}",
            f"Job ID:        {job_id}",
            f"Started (UTC): {created}",
            f"Source file:   {job.get('file_name', '?')} ({len(job.get('file_bytes', b''))} bytes)",
            f"Status:        {job.get('status', '?')}",
            "",
            "Pipeline audit:",
        ]
        for entry in audit:
            lines.append(f"  - {entry}")

        if job.get("status") == "failed":
            lines.append("")
            lines.append("Error details:")
            lines.append(f"  {job.get('error', 'Unknown')}")
            tb = job.get("traceback")
            if tb:
                lines.append("")
                lines.append("Traceback:")
                lines.append(tb)

        body = ("\n".join(lines) + "\n").encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="run-log-{job_id}.txt"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
