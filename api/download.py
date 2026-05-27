# api/download.py
# GET /api/download?job_id=...
# Returns the generated workbook for the job, with the macro-enabled MIME
# type and a Content-Disposition naming it {YYMMDD}_Ratings_{DealName}.xlsm.

from __future__ import annotations

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

        body = job.get("workbook_bytes")
        if not body:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Workbook not generated yet")
            return

        filename: str = job["workbook_filename"]

        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.ms-excel.sheet.macroEnabled.12")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
