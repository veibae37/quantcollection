"""Authenticated MiniQMT snapshot upload and public read-only retrieval API."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from live_snapshot_store import (
    LiveSnapshotUnavailable,
    LiveSnapshotValidationError,
    get_program_snapshot,
    load_live_bundle,
    save_live_bundle,
)
from qmt_auth import resolve_qmt_webhook_secret


def _response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _reject_constant(value: str):
    raise ValueError(f"JSON 不允许 {value}")


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            query = parse_qs(urlparse(self.path).query)
            program_id = str((query.get("program") or [""])[0]).strip()
            if program_id:
                result, metadata = get_program_snapshot(program_id)
                return _response(self, 200, {"ok": True, "snapshot_meta": metadata, "result": result})
            bundle = load_live_bundle()
            # The complete bundle is public read-only, but never contains account,
            # terminal path, credentials, holdings or order submission capability.
            return _response(self, 200, {"ok": True, "bundle": bundle})
        except KeyError as exc:
            return _response(self, 404, {"ok": False, "error": str(exc)})
        except LiveSnapshotUnavailable as exc:
            return _response(self, 503, {"ok": False, "error": str(exc)})
        except Exception:
            return _response(self, 500, {"ok": False, "error": "读取 QMT 实盘快照失败"})

    def do_POST(self):
        secret = resolve_qmt_webhook_secret()
        secret_header = os.environ.get("QMT_SECRET_HEADER", "X-QMT-Secret")
        supplied = self.headers.get(secret_header, "")
        if not secret or not hmac.compare_digest(supplied, secret):
            return _response(self, 401, {"ok": False, "error": "QMT 上传认证失败"})

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return _response(self, 400, {"ok": False, "error": "Content-Length 无效"})
        max_bytes = int(os.environ.get("QMT_MAX_UPLOAD_BYTES", "2097152"))
        if length <= 0 or length > max_bytes:
            return _response(self, 413, {"ok": False, "error": "QMT 快照为空或超过大小限制"})

        body = self.rfile.read(length)
        supplied_hash = self.headers.get("X-Payload-SHA256", "").strip().lower()
        actual_hash = hashlib.sha256(body).hexdigest()
        if supplied_hash and not hmac.compare_digest(supplied_hash, actual_hash):
            return _response(self, 400, {"ok": False, "error": "QMT 快照哈希校验失败"})
        try:
            payload = json.loads(body.decode("utf-8"), parse_constant=_reject_constant)
            stored = save_live_bundle(payload)
            return _response(
                self,
                200,
                {
                    "ok": True,
                    "accepted": len(payload["programs"]),
                    "programs": sorted(payload["programs"]),
                    "generated_at": payload["generated_at"],
                    "storage": stored["storage"],
                },
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, LiveSnapshotValidationError) as exc:
            return _response(self, 400, {"ok": False, "error": str(exc)})
        except LiveSnapshotUnavailable as exc:
            return _response(self, 503, {"ok": False, "error": str(exc)})
        except Exception:
            return _response(self, 500, {"ok": False, "error": "QMT 实盘快照保存失败"})
