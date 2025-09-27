
from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional, Dict, Any

TICK = 0.01

@dataclass
class Order:
    ts: pd.Timestamp
    side: str             # 'buy' or 'sell'
    qty: float            # in lots (base units abstract)
    px: float             # price (pre-slippage/fees for taker; quote px for maker)
    kind: str             # 'taker' or 'maker'
    reason: str           # 'entry', 'exit', 'mm_quote', etc.
    ttl_ms: Optional[int] = None

@dataclass
class Fill:
    ts: pd.Timestamp
    side: str
    qty: float
    px: float             # executed price
    fee: float
    slippage: float       # px_exe - reference px for buy; reference px - px_exe for sell
    reason: str

def ensure_dt_index(df: pd.DataFrame, col: str = "origin_time") -> pd.DataFrame:
    out = df.copy()
    out[col] = pd.to_datetime(out[col], utc=True)
    out = out.sort_values(col).set_index(col)
    return out

def within_window(df: pd.DataFrame, t0: pd.Timestamp, ms: int) -> pd.DataFrame:
    t1 = t0 + pd.Timedelta(milliseconds=ms)
    return df[(df.index >= t0) & (df.index <= t1)]

def nearest_row(df: pd.DataFrame, t: pd.Timestamp) -> pd.Series:
    # fast nearest: asof
    return df.iloc[df.index.get_indexer([t], method="nearest")]

def cap(val, lo=None, hi=None):
    if lo is not None:
        val = max(lo, val)
    if hi is not None:
        val = min(hi, val)
    return val

def to_ticks(px_diff: float, tick: float = TICK) -> float:
    return px_diff / tick

def from_ticks(ticks: float, tick: float = TICK) -> float:
    return ticks * tick
