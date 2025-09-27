
from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Dict, Any, Tuple, List
from .utils import within_window, TICK
from .cost import fee_amount, taker_slippage_price

class Broker:
    def __init__(self, config: Dict[str, Any]):
        self.cfg = config

    def snapshot_to_book(self, row: pd.Series) -> Dict[str, np.ndarray]:
        bid_px = np.array([row[f"bid_{i}_price"] for i in range(20)], dtype=float)
        ask_px = np.array([row[f"ask_{i}_price"] for i in range(20)], dtype=float)
        bid_sz = np.array([row[f"bid_{i}_size"] for i in range(20)], dtype=float)
        ask_sz = np.array([row[f"ask_{i}_size"] for i in range(20)], dtype=float)
        return {"bid_px": bid_px, "ask_px": ask_px, "bid_sz": bid_sz, "ask_sz": ask_sz}

    def exec_taker(self, ts: pd.Timestamp, side: str, qty: float, lob_event: pd.Series) -> Dict[str, Any]:
        ex = self.cfg.get("execution", {})
        L = int(ex.get("slippage_L", 1))
        mode = ex.get("slippage_mode", "none")
        taker_bps = float(ex.get("taker_bps", 8))
        book = self.snapshot_to_book(lob_event)
        px_fill = taker_slippage_price(side, qty, book, mode=mode, L=L, tick=TICK)
        notional = qty * px_fill
        fee = fee_amount(notional, taker_bps)
        # slippage relative to best quote
        ref_px = book["ask_px"][0] if side=="buy" else book["bid_px"][0]
        slippage = (px_fill - ref_px) if side=="buy" else (ref_px - px_fill)
        return {"ts": ts, "side": side, "qty": qty, "px": float(px_fill), "fee": float(fee), "slippage": float(slippage)}

    def exec_maker_ttl(self, t0: pd.Timestamp, side: str, qty: float, px_quote: float,
                        events_window: pd.DataFrame) -> Dict[str, Any]:
        """
        Approximate maker fill as probability proportional to top-of-book depletion within TTL.
        - For 'buy' quote (bid): use depletion of bid_0_size while bid_0_price >= px_quote.
        - For 'sell' quote (ask): use depletion of ask_0_size while ask_0_price <= px_quote.
        """
        ex = self.cfg.get("execution", {})
        maker_bps = float(ex.get("maker_bps", 2))
        fills = 0.0
        last_px = px_quote
        if side == "buy":
            # Track depletion on bid side
            mask = events_window["bid_0_price"] >= px_quote
            evs = events_window[mask]
            if len(evs) >= 2:
                q0 = evs["bid_0_size"].iloc[0]
                q_min = evs["bid_0_size"].min()
                depletion = max(0.0, float(q0 - q_min))
                # Assume joining back of queue: fill fraction ~ depletion/(q0 + qty)
                frac = min(1.0, depletion / max(1e-12, q0 + qty))
                fills = qty * frac
                # execution price approx at px_quote
                px_exec = px_quote
        else:
            mask = events_window["ask_0_price"] <= px_quote
            evs = events_window[mask]
            if len(evs) >= 2:
                q0 = evs["ask_0_size"].iloc[0]
                q_min = evs["ask_0_size"].min()
                depletion = max(0.0, float(q0 - q_min))
                frac = min(1.0, depletion / max(1e-12, q0 + qty))
                fills = qty * frac
                px_exec = px_quote

        if fills <= 0.0:
            return {"ts": t0, "side": side, "qty": 0.0, "px": float(px_quote), "fee": 0.0, "slippage": 0.0}

        notional = fills * px_exec
        fee = fee_amount(notional, maker_bps)
        # Maker slippage measured vs quote (should be 0 if filled at quote)
        slippage = 0.0
        return {"ts": t0, "side": side, "qty": float(fills), "px": float(px_exec), "fee": float(fee), "slippage": float(slippage)}
