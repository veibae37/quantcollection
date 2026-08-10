import json
from http.server import BaseHTTPRequestHandler

from web_runner import public_config, public_programs


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps(
            {"ok": True, "config": public_config(), "programs": public_programs()},
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "public, max-age=60, s-maxage=300")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
