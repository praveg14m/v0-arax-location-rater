# api/status.py
# GET /api/status?job_id=...
# Returns the current state of a job. See _state.compute_status for the
# mock progression timeline.

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from _state import compute_status, get_job


def _json(handler: BaseHTTPRequestHandler, status: int, body: dict) -> None:
    payload = json.dumps(body).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        qs = parse_qs(urlparse(self.path).query)
        job_id = (qs.get("job_id") or [""])[0]
        if not job_id:
            _json(self, 400, {"error": "Missing job_id"})
            return

        job = get_job(job_id)
        if job is None:
            _json(self, 404, {"error": "Job not found"})
            return

        _json(self, 200, compute_status(job))
