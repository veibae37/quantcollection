"""Local MiniQMT worker for fee-strict ETF option box-spread scanning.

Run this file only on the Windows machine where QMT/MiniQMT is open.  It uses
QMT's local market-data service, never Vercel, to discover contracts and read
level-1 depth.  Vercel receives only already-calculated positive opportunities.

Environment variables:
    OPTIONS_WEBHOOK_URL       Default: project Vercel /api/options endpoint
    OPTIONS_WEBHOOK_SECRET    Required shared secret (never commit it)
    OPTIONS_SECRET_HEADER     Default: X-Options-Secret
    OPTIONS_SCAN_INTERVAL     Default: 5 seconds
    OPTIONS_INTEREST_RATE     Default: 0.03
    OPTIONS_MIN_NET_CNY       Default: 0.0
    OPTIONS_TOP_N             Default: 50
    OPTIONS_MIN_DEPTH         Default: 1 contract on every executable leg
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import logging
import os
import signal
import threading
import time
from dataclasses import dataclass
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from option_market_scanner import (
    ETF_OPTION_MULTIPLIER,
    MarketWideBoxScanner,
    OptionScanConfig,
    OptionSnapshot,
)


LOGGER = logging.getLogger("scanner_worker")
CHINA_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_SECRET_HEADER = "X-Options-Secret"
DEFAULT_WEBHOOK_URL = "https://quantcollection-aa5n.vercel.app/api/options"
SCHEMA_VERSION = "options-box-spread.v1"


class WorkerConfigurationError(RuntimeError):
    """Raised when local worker configuration is incomplete or unsafe."""


class QMTMarketDataError(RuntimeError):
    """Raised when QMT cannot provide a complete executable snapshot."""


@dataclass(frozen=True)
class WorkerConfig:
    webhook_url: str
    webhook_secret: str
    secret_header: str = DEFAULT_SECRET_HEADER
    scan_interval_seconds: float = 5.0
    interest_rate: float = 0.03
    min_true_net_profit_cny: float = 0.0
    top_n: int = 50
    min_depth: int = 1
    request_timeout_seconds: float = 10.0
    universe_refresh_seconds: float = 300.0

    @classmethod
    def from_env(cls, *, require_webhook: bool = True) -> "WorkerConfig":
        webhook_url = (
            os.environ.get("OPTIONS_WEBHOOK_URL", "").strip()
            or DEFAULT_WEBHOOK_URL
        )
        secret = os.environ.get("OPTIONS_WEBHOOK_SECRET", "").strip()
        if require_webhook and not webhook_url.startswith("https://"):
            raise WorkerConfigurationError(
                "OPTIONS_WEBHOOK_URL must be an https:// Vercel endpoint"
            )
        if require_webhook and not secret:
            raise WorkerConfigurationError(
                "OPTIONS_WEBHOOK_SECRET is required and must match the Vercel value"
            )
        if require_webhook and len(secret) < 24:
            # Keep the worker compatible with an already-configured shorter
            # Vercel secret.  This is a security warning, not a protocol error:
            # both receivers require only a non-empty exact header match.
            LOGGER.warning(
                "OPTIONS_WEBHOOK_SECRET is shorter than the recommended 24 "
                "characters; rotate it to a longer random value when practical"
            )
        if not require_webhook:
            webhook_url = webhook_url or "https://dry-run.invalid/api/options"
            secret = secret or "dry-run-secret-is-never-sent"
        config = cls(
            webhook_url=webhook_url,
            webhook_secret=secret,
            secret_header=os.environ.get(
                "OPTIONS_SECRET_HEADER", DEFAULT_SECRET_HEADER
            ).strip(),
            scan_interval_seconds=float(os.environ.get("OPTIONS_SCAN_INTERVAL", "5")),
            interest_rate=float(os.environ.get("OPTIONS_INTEREST_RATE", "0.03")),
            min_true_net_profit_cny=float(
                os.environ.get("OPTIONS_MIN_NET_CNY", "0")
            ),
            top_n=int(os.environ.get("OPTIONS_TOP_N", "50")),
            min_depth=int(os.environ.get("OPTIONS_MIN_DEPTH", "1")),
            request_timeout_seconds=float(
                os.environ.get("OPTIONS_HTTP_TIMEOUT", "10")
            ),
            universe_refresh_seconds=float(
                os.environ.get("OPTIONS_UNIVERSE_REFRESH", "300")
            ),
        )
        if not config.secret_header or any(char.isspace() for char in config.secret_header):
            raise WorkerConfigurationError("OPTIONS_SECRET_HEADER is invalid")
        if not 0.5 <= config.scan_interval_seconds <= 3600:
            raise WorkerConfigurationError("OPTIONS_SCAN_INTERVAL must be 0.5..3600")
        if not 0 <= config.interest_rate <= 1:
            raise WorkerConfigurationError("OPTIONS_INTEREST_RATE must be 0..1")
        if config.min_true_net_profit_cny < 0:
            raise WorkerConfigurationError("OPTIONS_MIN_NET_CNY cannot be negative")
        if not 1 <= config.top_n <= 500 or config.min_depth < 1:
            raise WorkerConfigurationError("invalid OPTIONS_TOP_N or OPTIONS_MIN_DEPTH")
        return config


def _first_positive(values: Any) -> float:
    if values is None:
        return 0.0
    try:
        # QMT may return list, tuple or numpy.ndarray for five-level depth.
        first = values[0]
        value = float(first if first is not None else 0.0)
    except (IndexError, KeyError, TypeError, ValueError):
        return 0.0
    return value if value > 0 else 0.0


def _parse_expiry(value: Any) -> dt.date | None:
    digits = "".join(char for char in str(value or "") if char.isdigit())[:8]
    if len(digits) != 8:
        return None
    try:
        return dt.datetime.strptime(digits, "%Y%m%d").date()
    except ValueError:
        return None


def _option_type(detail: dict[str, Any]) -> str | None:
    value = str(detail.get("optType") or detail.get("OptType") or "").upper()
    if value in {"CALL", "C", "认购"}:
        return "C"
    if value in {"PUT", "P", "认沽"}:
        return "P"
    return None


class QMTETFOptionProvider:
    """Cache contract metadata and batch-fetch executable level-1 quotes."""

    SECTORS = ("上证期权", "深证期权")

    def __init__(self, universe_refresh_seconds: float = 300.0) -> None:
        self.universe_refresh_seconds = universe_refresh_seconds
        self._metadata: list[dict[str, Any]] = []
        self._metadata_loaded_at = 0.0

    @staticmethod
    def _xtdata():
        try:
            from xtquant import xtdata
        except Exception as exc:
            raise QMTMarketDataError(
                "xtquant is unavailable; run on the logged-in Windows QMT host"
            ) from exc
        return xtdata

    @staticmethod
    def _raw_option_detail(xtdata: Any, code: str) -> dict[str, Any]:
        """Normalize raw QMT metadata when its public option helper is broken.

        Some xtquant builds assume ``OptUndlUniCode`` is always populated.
        Current ETF option records may instead expose only ``OptUndlCode``;
        this adapter uses that documented-equivalent raw field without
        modifying the bundled vendor library.
        """
        raw_getter = getattr(xtdata, "_get_instrument_detail", None)
        if not callable(raw_getter):
            return {}
        raw = raw_getter(code) or {}
        if not isinstance(raw, dict):
            return {}
        extension = raw.get("ExtendInfo") or {}
        if not isinstance(extension, dict):
            extension = {}
        option_flag = extension.get("OptionType")
        option_type = "CALL" if option_flag == 0 else "PUT" if option_flag == 1 else ""
        if not option_type:
            name = str(raw.get("InstrumentName") or "")
            option_type = "CALL" if "购" in name else "PUT" if "沽" in name else ""
        underlying_code = (
            extension.get("OptUndlUniCode") or extension.get("OptUndlCode") or ""
        )
        underlying_market = str(extension.get("OptUndlMarket") or "").strip()
        underlying_full = (
            f"{underlying_code}.{underlying_market}"
            if underlying_code and underlying_market
            else str(underlying_code)
        )
        return {
            "InstrumentName": raw.get("InstrumentName"),
            "ExpireDate": raw.get("ExpireDate"),
            "OptExercisePrice": extension.get("OptExercisePrice"),
            "VolumeMultiple": raw.get("VolumeMultiple") or extension.get("OptUnit"),
            "OptUndlCode": extension.get("OptUndlCode"),
            "OptUndlCodeFull": underlying_full,
            "ProductCode": underlying_full or raw.get("ProductID"),
            "optType": option_type,
        }

    def _load_metadata(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        if self._metadata and now - self._metadata_loaded_at < self.universe_refresh_seconds:
            return self._metadata

        xtdata = self._xtdata()
        codes: set[str] = set()
        for sector in self.SECTORS:
            codes.update(str(code) for code in (xtdata.get_stock_list_in_sector(sector) or []))
        if not codes:
            raise QMTMarketDataError(
                "QMT returned no SSE/SZSE option contracts; update sector data first"
            )

        today = dt.datetime.now(CHINA_TZ).date()
        metadata: list[dict[str, Any]] = []
        malformed_details: list[tuple[str, str]] = []
        nonstandard_multipliers: dict[int, list[str]] = {}
        raw_fallback_count = 0
        prefer_raw_details = False
        for code in sorted(codes):
            detail: dict[str, Any] = {}
            detail_error: Exception | None = None
            try:
                # Some QMT sector snapshots retain stale option records whose
                # OptUndlUniCode is None.  xtquant then raises inside
                # get_option_detail_data while constructing OptUndlCodeFull.
                # One malformed contract must not abort the whole universe.
                if not prefer_raw_details:
                    detail = xtdata.get_option_detail_data(code) or {}
            except Exception as exc:
                detail_error = exc

            if prefer_raw_details or not detail:
                try:
                    raw_detail = self._raw_option_detail(xtdata, code)
                except Exception as exc:
                    detail_error = detail_error or exc
                    raw_detail = {}
                if raw_detail:
                    detail = raw_detail
                    raw_fallback_count += 1
                    # The observed None + str failure affects the whole QMT
                    # metadata build, so avoid repeating 1,000+ doomed calls.
                    if isinstance(detail_error, TypeError):
                        prefer_raw_details = True

            if not detail:
                error_type = type(detail_error).__name__ if detail_error else "EmptyDetail"
                malformed_details.append((code, error_type))
                LOGGER.debug(
                    "skip malformed QMT option metadata for %s",
                    code,
                )
                continue
            kind = _option_type(detail)
            expiry = _parse_expiry(detail.get("ExpireDate"))
            try:
                strike = float(detail.get("OptExercisePrice") or 0.0)
                reported_multiplier = int(float(detail.get("VolumeMultiple") or 0))
            except (TypeError, ValueError):
                continue
            if kind is None or expiry is None or expiry < today or strike <= 0:
                continue
            # A non-zero QMT multiplier must agree with the ETF standard.  A
            # zero value means the local metadata field was unavailable; the
            # mandated ETF multiplier remains explicit in the cost model.
            if reported_multiplier not in {0, ETF_OPTION_MULTIPLIER}:
                nonstandard_multipliers.setdefault(reported_multiplier, []).append(code)
                continue
            suffix = code.rsplit(".", 1)[-1].upper()
            exchange = "SSE" if suffix in {"SH", "SHO"} else "SZSE"
            underlying = str(
                detail.get("OptUndlCodeFull")
                or detail.get("ProductCode")
                or detail.get("OptUndlCode")
                or "UNKNOWN"
            )
            metadata.append(
                {
                    "code": code,
                    "name": str(detail.get("InstrumentName") or code),
                    "underlying": underlying,
                    "exchange": exchange,
                    "expiry_date": expiry.isoformat(),
                    "remaining_days": max((expiry - today).days, 0),
                    "strike": strike,
                    "option_type": kind,
                    "contract_multiplier": ETF_OPTION_MULTIPLIER,
                }
            )
        if malformed_details:
            sample = ", ".join(
                f"{code}({error_type})"
                for code, error_type in malformed_details[:5]
            )
            LOGGER.warning(
                "skipped %s malformed/stale QMT option metadata records: %s",
                len(malformed_details),
                sample,
            )
        if raw_fallback_count:
            LOGGER.info(
                "loaded %s option metadata records through the raw QMT fallback",
                raw_fallback_count,
            )
        if nonstandard_multipliers:
            skipped_count = sum(len(items) for items in nonstandard_multipliers.values())
            multiplier_summary = ", ".join(
                f"{multiplier}: {len(items)}张"
                for multiplier, items in sorted(nonstandard_multipliers.items())
            )
            LOGGER.warning(
                "skipped %s adjusted/nonstandard contracts because the mandated "
                "model supports multiplier 10000 only (%s)",
                skipped_count,
                multiplier_summary,
            )
        if not metadata:
            raise QMTMarketDataError(
                "QMT option metadata contains no active ETF contracts "
                f"({len(malformed_details)} malformed records skipped)"
            )
        self._metadata = metadata
        self._metadata_loaded_at = now
        return metadata

    @staticmethod
    def _batches(values: list[str], size: int = 500) -> Iterable[list[str]]:
        for start in range(0, len(values), size):
            yield values[start : start + size]

    def fetch(self) -> OptionSnapshot:
        xtdata = self._xtdata()
        metadata = self._load_metadata()
        ticks: dict[str, dict[str, Any]] = {}
        codes = [item["code"] for item in metadata]
        # QMT get_full_tick is a vectorized local call; batching avoids one
        # network/IPC request per option contract.
        for batch in self._batches(codes):
            ticks.update(xtdata.get_full_tick(batch) or {})

        rows: list[dict[str, Any]] = []
        for item in metadata:
            tick = ticks.get(str(item["code"])) or {}
            bid = _first_positive(tick.get("bidPrice"))
            ask = _first_positive(tick.get("askPrice"))
            bid_volume = int(_first_positive(tick.get("bidVol")))
            ask_volume = int(_first_positive(tick.get("askVol")))
            if bid <= 0 or ask <= 0 or ask < bid or bid_volume <= 0 or ask_volume <= 0:
                continue
            rows.append(
                {
                    **item,
                    "bid": bid,
                    "ask": ask,
                    "bid_volume": bid_volume,
                    "ask_volume": ask_volume,
                    "volume": min(bid_volume, ask_volume),
                    "last": float(tick.get("lastPrice") or 0.0),
                    "quote_basis": "bid_ask",
                }
            )
        if not rows:
            raise QMTMarketDataError("QMT returned no ETF option contracts with valid BBO depth")
        now = dt.datetime.now(CHINA_TZ).isoformat(timespec="milliseconds")
        return OptionSnapshot(
            data=pd.DataFrame(rows),
            source="MiniQMT 沪深 ETF 期权实时买一/卖一",
            fetched_at=now,
            is_synthetic=False,
        )


class OpportunityPusher:
    """Authenticated, retrying HTTPS delivery without logging the secret."""

    def __init__(self, config: WorkerConfig) -> None:
        self.config = config
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"POST"}),
        )
        self.session = requests.Session()
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def post(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        payload_hash = hashlib.sha256(body).hexdigest()
        response = self.session.post(
            self.config.webhook_url,
            data=body,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                self.config.secret_header: self.config.webhook_secret,
                "X-Payload-SHA256": payload_hash,
                "User-Agent": "QMT-ETF-Box-Scanner/1.0",
            },
            timeout=(3.0, self.config.request_timeout_seconds),
        )
        response.raise_for_status()
        try:
            result = response.json()
        except ValueError as exc:
            raise RuntimeError("webhook returned a non-JSON response") from exc
        if not result.get("ok"):
            raise RuntimeError(f"webhook rejected payload: {result}")
        return result


def build_push_payload(scan_result: dict[str, Any]) -> dict[str, Any]:
    """Build a bounded payload containing positive TRUE-net opportunities only."""
    opportunities = [
        item
        for item in scan_result.get("opportunities", [])
        if float(item.get("true_net_profit_cny", 0.0)) > 0.0
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": scan_result["data_as_of"],
        "source": scan_result["source"],
        "opportunity_count": len(opportunities),
        "assumptions": {
            "contract_multiplier": ETF_OPTION_MULTIPLIER,
            "fee_per_contract_per_leg_cny": 1.7,
            "leg_count": 4,
            "total_fees_per_set_cny": 6.8,
            "slippage_tick_per_unit_per_leg": 0.0001,
            "total_slippage_per_set_cny": 4.0,
        },
        "opportunities": opportunities,
    }


def scan_once(
    config: WorkerConfig,
    provider: QMTETFOptionProvider,
    pusher: OpportunityPusher | None,
) -> dict[str, Any]:
    snapshot = provider.fetch()
    # Dimensional sequence enforced by MarketWideBoxScanner:
    # per-unit debit/fair value -> per-unit profit -> multiply by 10,000 to
    # absolute CNY -> subtract 6.8 CNY fees and 4.0 CNY slippage.  Fixed CNY
    # costs are never subtracted from a per-unit option premium.
    scanner = MarketWideBoxScanner(
        OptionScanConfig(
            top_n=config.top_n,
            interest_rate=config.interest_rate,
            actionpoint=config.min_true_net_profit_cny,
            min_volume=config.min_depth,
            data_mode="live",
        )
    )
    result = scanner.run(snapshot)
    payload = build_push_payload(result)
    if payload["opportunity_count"] > 0 and pusher is not None:
        acknowledgement = pusher.post(payload)
        LOGGER.info(
            "pushed %s positive opportunities; receiver accepted %s",
            payload["opportunity_count"],
            acknowledgement.get("accepted"),
        )
    elif payload["opportunity_count"] == 0:
        LOGGER.info("no positive TRUE-net ETF box opportunities")
    return payload


def main() -> None:
    # Load the project-local .env when python-dotenv is installed.  Existing
    # shell/Vercel environment variables keep precedence over file values.
    try:
        from dotenv import load_dotenv

        load_dotenv(override=False)
        load_dotenv(".env.local", override=False)
    except ImportError:
        LOGGER.warning("python-dotenv is unavailable; using process environment only")

    parser = argparse.ArgumentParser(description="QMT ETF option TRUE-net box scanner")
    parser.add_argument("--once", action="store_true", help="scan one cycle and exit")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="calculate and print positive opportunities without POSTing",
    )
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = WorkerConfig.from_env(require_webhook=not args.dry_run)
    provider = QMTETFOptionProvider(config.universe_refresh_seconds)
    pusher = None if args.dry_run else OpportunityPusher(config)
    stop_event = threading.Event()

    def request_stop(_signum: int, _frame: Any) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_stop)

    while not stop_event.is_set():
        started = time.monotonic()
        try:
            payload = scan_once(config, provider, pusher)
            if args.dry_run:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
        except Exception:
            LOGGER.exception("scan cycle failed")
            if args.once:
                raise
        if args.once:
            break
        elapsed = time.monotonic() - started
        stop_event.wait(max(config.scan_interval_seconds - elapsed, 0.1))


if __name__ == "__main__":
    main()
