# api/confirm.py
# POST /api/confirm
# Body: { "job_id": str, "city_overrides": { raw_city: chosen_mapping } }
#
# Flips the job into the "writing" state. /api/status will progress to
# "complete" ~3 seconds later (see _state.compute_status).

from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler

from _state import get_job, update_job


def _json(handler: BaseHTTPRequestHandler, status: int, body: dict) -> None:
    payload = json.dumps(body).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


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

        update_job(
            job_id,
            status="writing",
            current_step=5,
            confirmed_at=time.time(),
            city_overrides=overrides,
        )
        _json(self, 200, {"status": "writing"})
