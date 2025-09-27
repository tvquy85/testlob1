
from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Dict, Tuple, Any, List
from .utils import TICK, from_ticks

def fee_amount(notional: float, bps: float) -> float:
    return notional * (bps / 1e4)

def taker_slippage_price(side: str, size: float, book: Dict[str, np.ndarray],
                         mode: str = "none", L: int = 1, tick: float = TICK) -> float:
    """Return execution price including slippage for taker.
    book = {"bid_px": np.array(L20), "ask_px":..., "bid_sz":..., "ask_sz":...}
    If mode == 'topL_proportional', compute VWAP across top L based on size vs depth.
    If mode == 'microprice_shift', shift by half-spread sign.
    """
    if side not in ("buy","sell"):
        raise ValueError("side must be buy/sell")
    bid_px, ask_px = book["bid_px"], book["ask_px"]
    bid_sz, ask_sz = book["bid_sz"], book["ask_sz"]
    if mode == "none":
        return ask_px[0] if side=="buy" else bid_px[0]

    if mode == "topL_proportional":
        L = min(L, len(bid_px))
        if side == "buy":
            pxs, szs = ask_px[:L], ask_sz[:L]
        else:
            pxs, szs = bid_px[:L], bid_sz[:L]
        remaining = size
        vwap = 0.0; filled = 0.0
        for p, q in zip(pxs, szs):
            if remaining <= 0: break
            take = min(remaining, q)
            vwap += take * p
            filled += take
            remaining -= take
        if filled == 0:
            return ask_px[0] if side=="buy" else bid_px[0]
        return vwap / filled

    if mode == "microprice_shift":
        mid = (bid_px[0] + ask_px[0]) / 2.0
        spread = ask_px[0] - bid_px[0]
        shift = 0.5 * spread   # optimistic microprice move
        return mid + shift if side=="buy" else mid - shift

    raise ValueError(f"Unknown slippage mode: {mode}")
