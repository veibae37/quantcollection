"""Fee-strict A-share ETF option box-spread scanner facade.

The cloud/web entry point is deliberately read-only.  Live QMT quote polling
and authenticated webhook delivery live in :mod:`scanner_worker`; keeping the
worker separate prevents a Vercel page view from ever touching a broker.

All option premiums are per-unit prices.  Fixed CNY costs are deducted only
after the per-unit theoretical profit has been multiplied by 10,000.
"""

from __future__ import annotations

import json
from typing import Any

from option_market_scanner import (
    BOX_LEG_COUNT,
    ETF_OPTION_MULTIPLIER,
    FEE_PER_CONTRACT_CNY,
    SLIPPAGE_TICK_PER_UNIT,
    calculate_true_box_profit_cny,
    run_option_market_scan,
)


def calculate_true_net_profit(
    *,
    call_low_ask: float,
    put_low_bid: float,
    put_high_ask: float,
    call_high_bid: float,
    low_strike: float,
    high_strike: float,
    interest_rate: float,
    remaining_days: int,
) -> dict[str, float]:
    """Expose the exact five-step ETF-option box calculation.

    Constants are intentionally explicit: 10,000 multiplier, 1.7 CNY per
    contract per leg, four legs, and one 0.0001 tick of slippage per leg.
    """
    return calculate_true_box_profit_cny(
        call_low_ask=call_low_ask,
        put_low_bid=put_low_bid,
        put_high_ask=put_high_ask,
        call_high_bid=call_high_bid,
        low_strike=low_strike,
        high_strike=high_strike,
        interest_rate=interest_rate,
        remaining_days=remaining_days,
        contract_multiplier=ETF_OPTION_MULTIPLIER,
        fee_per_contract_cny=FEE_PER_CONTRACT_CNY,
        slippage_tick_per_unit=SLIPPAGE_TICK_PER_UNIT,
    )


def run_demo(
    interest_rate: float = 0.03,
    actionpoint: float = 0.0,
    desir_mount: int = 1,
    data_mode: str = "demo",
    top_n: int = 20,
    min_volume: int = 1,
) -> dict[str, Any]:
    """Run the read-only ETF-option scan used by the Vercel dashboard.

    ``actionpoint`` is retained for web-client compatibility, but now means
    minimum TRUE net profit in CNY per complete set, not a per-unit decimal.
    Returned opportunities always have ``true_net_profit_cny > actionpoint``.
    """
    return run_option_market_scan(
        data_mode=str(data_mode),
        top_n=int(top_n),
        interest_rate=float(interest_rate),
        actionpoint=float(actionpoint),
        desir_mount=int(desir_mount),
        min_volume=int(min_volume),
    )


__all__ = [
    "BOX_LEG_COUNT",
    "ETF_OPTION_MULTIPLIER",
    "FEE_PER_CONTRACT_CNY",
    "SLIPPAGE_TICK_PER_UNIT",
    "calculate_true_net_profit",
    "run_demo",
]


if __name__ == "__main__":
    print(json.dumps(run_demo(data_mode="auto"), ensure_ascii=False, indent=2))
