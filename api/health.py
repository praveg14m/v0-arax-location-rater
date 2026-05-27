"""Health check endpoint for the Python serverless runtime.

GET /api/health -> {"status": "ok"}

This file also serves as a placeholder confirming Vercel discovers Python
functions in the repo-root `api/` directory (not `app/api/`).
"""

from http.server import BaseHTTPRequestHandler
import json


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok", "service": "arax-location-rater"}).encode("utf-8"))
