
from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Dict, Any, Callable, Iterable, Tuple, List
from .utils import ensure_dt_index, within_window, from_ticks, TICK
from .broker import Broker
from .metrics import summarize

def _default_strategy_fn(t, row, state, cfg, aux):
    """Very simple strategy placeholder: no trades."""
    return []  # list of orders

def _extract_event_at(events_df: pd.DataFrame, t: pd.Timestamp):
    # nearest event at or before t
    try:
        idx = events_df.index.get_indexer([t], method="pad")[0]
        if idx == -1: idx = 0
        return events_df.iloc[idx]
    except Exception:
        return events_df.iloc[0]

def run_backtest(config: Dict[str, Any],
                 data_iter: Iterable[pd.DataFrame] | pd.DataFrame,
                 features_fn: Callable[..., pd.DataFrame],
                 strategy_fn: Callable[..., list] = _default_strategy_fn,
                 ohlcv_dict: Dict[str, pd.DataFrame] | None = None
                ) -> Dict[str, Any]:
    """
    Event-driven backtest. Compute 1s features, then iterate each 1s bar to generate orders.
    Taker fills at nearest event; Maker fills via TTL window.
    """
    # Prepare events DataFrame
    if isinstance(data_iter, pd.DataFrame):
        events_df = ensure_dt_index(data_iter, "origin_time")
    else:
        events_df = pd.concat(list(data_iter), ignore_index=True)
        events_df = ensure_dt_index(events_df, "origin_time")

    # Build features 1s
    if ohlcv_dict:
        feats_1s = features_fn(events_df.reset_index(), 
                               ohlcv_dict.get("1m"), ohlcv_dict.get("5m"), ohlcv_dict.get("15m"))
    else:
        feats_1s = features_fn(events_df.reset_index())
    feats_1s = feats_1s.sort_index()

    # Initialize
    broker = Broker(config)
    eq0 = float(config.get("initial_equity", 100_000.0))
    equity = eq0
    position = 0.0
    inventory = 0.0
    last_trade_side = None
    last_trade_time = None  # set after first iteration

    trades = []
    eq_curve = []

    risk = config.get("risk", {})
    cooling = pd.Timedelta(seconds=float(risk.get("cooling_time_s", 0)))
    max_pos = int(risk.get("max_positions", 3))
    max_gross = float(risk.get("max_gross_exposure", 3.0))

    exec_cfg = config.get("execution", {})
    ttl_ms_default = int(exec_cfg.get("TTL_ms", 500))

    # Iterate 1s grid
    for t, row in feats_1s.iterrows():
        # Strategy to generate orders (list of dicts or Orders)
        actions = strategy_fn(t, row, {"position": position, "inventory": inventory}, config, {"feats": feats_1s})
        if not isinstance(actions, list):
            actions = []

        # Enforce risk cooling
        if last_trade_time is not None and (t - last_trade_time) < cooling:
            actions = []

        # Execute actions
        lob_at_t = _extract_event_at(events_df, t)
        for act in actions:
            side = act.get("side")
            kind = act.get("kind", "taker")
            qty  = float(act.get("qty", 1.0))

            # Risk checks
            if abs(position + (qty if side=="buy" else -qty)) > max_gross:
                continue

            if kind == "taker":
                fill = broker.exec_taker(t, side, qty, lob_at_t)
                pnl = (fill["px"] - row["mid"]) * qty * (1 if side=="sell" else -1)  # mid as ref for sec PnL
                equity += -fill["fee"]
                position += (qty if side=="buy" else -qty)
                trades.append({**fill, "reason": act.get("reason",""), "pnl": pnl})
                last_trade_time = t
                last_trade_side = side

            elif kind == "maker":
                ttl_ms = int(act.get("ttl_ms", ttl_ms_default))
                pxq = float(act.get("px_quote", row["mid"]))
                win = events_df[(events_df.index >= t) & (events_df.index <= t + pd.Timedelta(milliseconds=ttl_ms))]
                fill = broker.exec_maker_ttl(t, side, qty, pxq, win)
                if fill["qty"] > 0:
                    pnl = (row["mid"] - fill["px"]) * fill["qty"] if side=="buy" else (fill["px"] - row["mid"]) * fill["qty"]
                    equity += -fill["fee"]
                    position += (fill["qty"] if side=="buy" else -fill["qty"])
                    trades.append({**fill, "reason": act.get("reason","mm"), "pnl": pnl})
                    last_trade_time = t
                    last_trade_side = side

        # Mark-to-market PnL for equity curve per second: position * (Δmid)
        # approximate second return if previous row exists
        # We'll compute per-second return later from equity curve if needed.
        eq_curve.append({"ts": t, "equity": equity, "position": position})

    eq_df = pd.DataFrame(eq_curve).set_index("ts")
    eq_df["equity"] = eq_df["equity"].ffill()
    eq_df["pnl_sec"] = eq_df["equity"].diff().fillna(0.0)

    trades_df = pd.DataFrame(trades)
    metrics = summarize(eq_df, trades_df, eq_df["pnl_sec"], eq0)
    results = {"trades": trades_df, "equity_curve": eq_df, "metrics": metrics, "config_resolved": config}
    return results
