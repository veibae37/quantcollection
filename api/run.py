import json
import os
import time
from http.server import BaseHTTPRequestHandler

from web_runner import run_registered


def response(handler_instance, status, payload):
    body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    handler_instance.send_response(status)
    handler_instance.send_header("Content-Type", "application/json; charset=utf-8")
    handler_instance.send_header("Cache-Control", "no-store")
    handler_instance.send_header("Content-Length", str(len(body)))
    handler_instance.end_headers()
    handler_instance.wfile.write(body)


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        max_bytes = int(os.environ.get("MAX_INPUT_BYTES", "16384"))
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return response(self, 400, {"ok": False, "error": "Content-Length 无效"})
        if content_length <= 0 or content_length > max_bytes:
            return response(self, 413, {"ok": False, "error": "请求内容为空或过大"})
        try:
            request = json.loads(self.rfile.read(content_length).decode("utf-8"))
            program_id = str(request.get("program", ""))
            parameters = request.get("parameters", {})
            if not isinstance(parameters, dict):
                raise ValueError("parameters 必须是对象")
            started = time.perf_counter()
            result = run_registered(program_id, parameters)
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            return response(self, 200, {"ok": True, "duration_ms": duration_ms, "result": result})
        except json.JSONDecodeError:
            return response(self, 400, {"ok": False, "error": "请求不是有效的 JSON"})
        except (KeyError, ValueError, PermissionError) as exc:
            return response(self, 400, {"ok": False, "error": str(exc)})
        except Exception as exc:
            return response(self, 500, {"ok": False, "error": f"程序运行失败：{type(exc).__name__}"})
