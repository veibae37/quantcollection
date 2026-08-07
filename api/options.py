"""Vercel Python compatibility receiver for the current non-Next.js project."""

from __future__ import annotations

import hmac
import json
import math
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from typing import Any


EXPECTED_SCHEMA = "options-box-spread.v1"
MAX_BODY_BYTES = 256 * 1024


def _response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _valid_opportunity(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    legs = item.get("legs")
    return (
        _number(item.get("true_net_profit_cny"))
        and item["true_net_profit_cny"] > 0
        and _number(item.get("absolute_gross_profit_cny"))
        and item.get("fees_cny") == 6.8
        and item.get("slippage_cny") == 4.0
        and item.get("contract_multiplier") == 10_000
        and isinstance(legs, list)
        and len(legs) == 4
    )


def _valid_payload(payload: Any) -> bool:
    if not isinstance(payload, dict) or payload.get("schema_version") != EXPECTED_SCHEMA:
        return False
    opportunities = payload.get("opportunities")
    count = payload.get("opportunity_count")
    return (
        isinstance(payload.get("generated_at"), str)
        and isinstance(payload.get("source"), str)
        and isinstance(opportunities, list)
        and len(opportunities) <= 500
        and isinstance(count, int)
        and not isinstance(count, bool)
        and count == len(opportunities)
        and all(_valid_opportunity(item) for item in opportunities)
    )


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        expected = os.environ.get("OPTIONS_WEBHOOK_SECRET", "")
        header_name = os.environ.get("OPTIONS_SECRET_HEADER", "X-Options-Secret")
        received = self.headers.get(header_name, "")
        if not expected or not hmac.compare_digest(received, expected):
            return _response(self, 401, {"ok": False, "error": "unauthorized"})
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return _response(self, 413, {"ok": False, "error": "invalid body size"})
        if content_length <= 0 or content_length > MAX_BODY_BYTES:
            return _response(self, 413, {"ok": False, "error": "invalid body size"})
        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _response(self, 400, {"ok": False, "error": "invalid JSON"})
        if not _valid_payload(payload):
            return _response(
                self,
                422,
                {"ok": False, "error": "invalid or non-positive opportunity payload"},
            )
        return _response(
            self,
            200,
            {
                "ok": True,
                "accepted": len(payload["opportunities"]),
                "received_at": datetime.now(timezone.utc).isoformat(),
            },
        )
