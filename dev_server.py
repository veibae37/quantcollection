"""Small local preview server; production uses Vercel's routing."""

import json
import os
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from web_runner import PROGRAMS, public_config, run_registered


PUBLIC = Path(__file__).resolve().parent / "public"


class PreviewHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/api/programs":
            return self._json(200, {"ok": True, "config": public_config(), "programs": PROGRAMS})
        if self.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/api/run":
            return self._json(404, {"ok": False, "error": "接口不存在"})
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            max_bytes = int(os.environ.get("MAX_INPUT_BYTES", "16384"))
            if content_length <= 0 or content_length > max_bytes:
                return self._json(413, {"ok": False, "error": "请求内容为空或过大"})
            request = json.loads(self.rfile.read(content_length).decode("utf-8"))
            parameters = request.get("parameters", {})
            if not isinstance(parameters, dict):
                raise ValueError("parameters 必须是对象")
            started = time.perf_counter()
            result = run_registered(str(request.get("program", "")), parameters)
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            return self._json(200, {"ok": True, "duration_ms": duration_ms, "result": result})
        except (json.JSONDecodeError, KeyError, ValueError, PermissionError) as exc:
            return self._json(400, {"ok": False, "error": str(exc)})
        except Exception as exc:
            return self._json(500, {"ok": False, "error": f"程序运行失败：{type(exc).__name__}"})


if __name__ == "__main__":
    host = os.environ.get("DEV_HOST", "127.0.0.1")
    port = int(os.environ.get("DEV_PORT", "8000"))
    print(f"Preview: http://{host}:{port}")
    ThreadingHTTPServer((host, port), PreviewHandler).serve_forever()
