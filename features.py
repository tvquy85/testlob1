
"""
features.py — LOB feature engineering to 1s grid (vectorized)

Inputs:
  - LOB DataFrame with columns:
      origin_time, received_time, sequence_number, symbol, exchange,
      bid_{i}_price, bid_{i}_size, ask_{i}_price, ask_{i}_size for i=0..19
  - Optional OHLCV DataFrames for 1m/5m/15m with columns:
      time (datetime, UTC), open, high, low, close, volume

Output:
  - 1-second indexed DataFrame of engineered features and targets (see schema)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Dict, Optional, Tuple

DEFAULT_PARAMS = {
    "tick_size": 0.01,
    "obi_levels": [1,3,5,10,20],
    "ofi_levels": [1,3,5],
    "ofi_zscore_window_seconds": 60,
    "liquidity_windows": ["500ms","1s"],
    "momentum_windows_ms": [250,500,1000],
    "resample_1s": {
        "ffill_limit_seconds": 1
    },
    "ohlcv_join_tolerance_ms": 500,
}

def _to_dt(s: pd.Series) -> pd.Series:
    """Parse to timezone-aware UTC datetime."""
    if np.issubdtype(s.dtype, np.number):
        med = float(np.nanmedian(s.values))
        if med > 1e17:
            unit = "ns"
        elif med > 1e14:
            unit = "us"
        elif med > 1e12:
            unit = "ms"
        elif med > 1e10:
            unit = "s"
        else:
            unit = "ms"
        return pd.to_datetime(s, unit=unit, utc=True)
    else:
        return pd.to_datetime(s, utc=True, errors="coerce")

def _colnames(levels: int = 20):
    bid_p = [f"bid_{i}_price" for i in range(levels)]
    ask_p = [f"ask_{i}_price" for i in range(levels)]
    bid_s = [f"bid_{i}_size" for i in range(levels)]
    ask_s = [f"ask_{i}_size" for i in range(levels)]
    return bid_p, ask_p, bid_s, ask_s

def _resample_1s_last(df: pd.DataFrame, limit: int = 1) -> pd.DataFrame:
    """Resample to 1s using last observation, then forward-fill up to 'limit' seconds."""
    out = df.resample("1s").last()
    if limit is not None and limit > 0:
        out = out.ffill(limit=limit)
    return out

def _rolling_zscore(s: pd.Series, win: int) -> pd.Series:
    """Compute rolling z-score with protection against zero std."""
    mu = s.rolling(win, min_periods=max(10, win//5)).mean()
    sd = s.rolling(win, min_periods=max(10, win//5)).std(ddof=0)
    return (s - mu) / sd.replace(0.0, np.nan)

def _safe_div(numer, denom):
    return numer / denom.replace(0.0, np.nan)

def _build_basic(df_ev: pd.DataFrame) -> pd.DataFrame:
    """Basic mid/spread/microprice features at event-level (index=origin_time)."""
    mid = (df_ev["bid_0_price"] + df_ev["ask_0_price"]) / 2.0
    spread = df_ev["ask_0_price"] - df_ev["bid_0_price"]
    denom = (df_ev["bid_0_size"] + df_ev["ask_0_size"]).replace(0.0, np.nan)
    microprice = (df_ev["ask_0_price"]*df_ev["bid_0_size"] + df_ev["bid_0_price"]*df_ev["ask_0_size"]) / denom
    microprice = microprice.fillna(mid)  # if denom==0 fallback to mid
    microspread = microprice - mid
    bi = _safe_div(df_ev["bid_0_size"], (df_ev["bid_0_size"] + df_ev["ask_0_size"]))
    out = pd.DataFrame({
        "mid": mid, "spread": spread, "microprice": microprice, "microspread": microspread, "BI": bi
    }, index=df_ev.index)
    return out

def _build_depth_obi(df_ev: pd.DataFrame, levels: int = 20, obi_levels = [1,3,5,10,20]) -> pd.DataFrame:
    """Depth sums and OBI at event-level."""
    bid_p, ask_p, bid_s, ask_s = _colnames(levels)
    out = pd.DataFrame(index=df_ev.index)
    # precompute cumulative sums across levels efficiently
    bid_sizes = df_ev[bid_s].to_numpy()
    ask_sizes = df_ev[ask_s].to_numpy()
    # cumulative sums along levels axis (columns)
    bid_cumsum = np.cumsum(bid_sizes, axis=1)
    ask_cumsum = np.cumsum(ask_sizes, axis=1)
    # Depths and OBI
    for L in obi_levels:
        depth_bid = pd.Series(bid_cumsum[:, L-1], index=df_ev.index, name=f"depth_bid_L{L}")
        depth_ask = pd.Series(ask_cumsum[:, L-1], index=df_ev.index, name=f"depth_ask_L{L}")
        out[depth_bid.name] = depth_bid
        out[depth_ask.name] = depth_ask
        denom = (depth_bid + depth_ask).replace(0.0, np.nan)
        out[f"OBI_L{L}"] = (depth_bid - depth_ask) / denom
    return out

def _ofi_event(df_ev: pd.DataFrame, ofi_levels=[1,3,5], levels: int = 20) -> pd.DataFrame:
    """Compute OFI at event-level using Cont-style update at each level, sum to L."""
    bid_p_cols, ask_p_cols, bid_s_cols, ask_s_cols = _colnames(levels)
    # current and previous snapshots
    df_prev = df_ev.shift(1)

    res = pd.DataFrame(index=df_ev.index)

    # Vectorized computation per level
    for L in ofi_levels:
        # Slice columns 0..L-1
        bp = df_ev[bid_p_cols[:L]].to_numpy()
        ap = df_ev[ask_p_cols[:L]].to_numpy()
        bs = df_ev[bid_s_cols[:L]].to_numpy()
        as_arr = df_ev[ask_s_cols[:L]].to_numpy()

        bp_prev = df_prev[bid_p_cols[:L]].to_numpy()
        ap_prev = df_prev[ask_p_cols[:L]].to_numpy()
        bs_prev = df_prev[bid_s_cols[:L]].to_numpy()
        as_prev = df_prev[ask_s_cols[:L]].to_numpy()

        # Indicators
        ib_up   = (bp > bp_prev).astype(float)
        ib_dn   = (bp < bp_prev).astype(float)
        ib_eq   = (bp == bp_prev).astype(float)

        ia_dn   = (ap < ap_prev).astype(float)   # ask price down = more aggressive bids
        ia_up   = (ap > ap_prev).astype(float)
        ia_eq   = (ap == ap_prev).astype(float)

        dWb = ib_up*bs - ib_dn*bs_prev + ib_eq*(bs - bs_prev)
        dWa = ia_dn*as_arr - ia_up*as_prev + ia_eq*(as_arr - as_prev)
        ofi = (dWb - dWa).sum(axis=1)
        res[f"ofi_L{L}_event"] = ofi

    return res

def _liquidity_vacuum_event(df_ev: pd.DataFrame, obi_levels=[1,3,5,10,20]) -> pd.DataFrame:
    """Compute liquidity vacuum measures per event using time-based rolling windows."""
    out = pd.DataFrame(index=df_ev.index)
    # Use precomputed depths if present
    depth_cols = [c for c in df_ev.columns if c.startswith("depth_bid_L") or c.startswith("depth_ask_L")]
    if not depth_cols:
        # We expect caller to have concatenated depth features before calling this
        return out

    for L in obi_levels:
        bid_col = f"depth_bid_L{L}"
        ask_col = f"depth_ask_L{L}"
        if bid_col not in df_ev.columns or ask_col not in df_ev.columns:
            continue
        # time-based rolling maxima for 500ms and 1s
        for window in ["500ms","1s"]:
            roll_max_bid = df_ev[bid_col].rolling(window, min_periods=1).max()
            roll_max_ask = df_ev[ask_col].rolling(window, min_periods=1).max()
            drop_bid = (roll_max_bid - df_ev[bid_col]) / roll_max_bid.replace(0.0, np.nan)
            drop_ask = (roll_max_ask - df_ev[ask_col]) / roll_max_ask.replace(0.0, np.nan)
            out[f"vac_bid_L{L}_{'0p5s' if window=='500ms' else '1s'}"] = drop_bid.clip(lower=0.0)
            out[f"vac_ask_L{L}_{'0p5s' if window=='500ms' else '1s'}"] = drop_ask.clip(lower=0.0)
            # rate-of-change over exact window using shift by time
            prev_bid = df_ev[bid_col].shift(freq=window)
            prev_ask = df_ev[ask_col].shift(freq=window)
            out[f"roc_bid_L{L}_{'0p5s' if window=='500ms' else '1s'}"] = (df_ev[bid_col] - prev_bid) / prev_bid.replace(0.0, np.nan)
            out[f"roc_ask_L{L}_{'0p5s' if window=='500ms' else '1s'}"] = (df_ev[ask_col] - prev_ask) / prev_ask.replace(0.0, np.nan)
    return out

def _micro_momentum_event(df_ev: pd.DataFrame, windows_ms=[250,500,1000]) -> pd.DataFrame:
    out = pd.DataFrame(index=df_ev.index)
    for ms in windows_ms:
        delta = f"{ms}ms" if ms != 1000 else "1s"
        prev_mid = df_ev["mid"].shift(freq=delta)
        prev_micro = df_ev["microprice"].shift(freq=delta)
        out[f"dmid_{'1s' if ms==1000 else str(ms)+'ms'}"] = df_ev["mid"] - prev_mid
        out[f"dmicro_{'1s' if ms==1000 else str(ms)+'ms'}"] = df_ev["microprice"] - prev_micro
    return out

def _resample_feature_blocks(ev_blocks: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Resample different blocks with appropriate aggregations, then merge."""
    # Determine base index union
    # We will resample each block separately
    out_blocks = []
    for name, df in ev_blocks.items():
        if df.empty:
            continue
        if not isinstance(df.index, pd.DatetimeIndex):
            raise ValueError(f"Block {name} must be indexed by DatetimeIndex (origin_time).")
        if name in ("ofi",):
            # sum to 1s and rename *_event -> *_1s
            out = df.resample("1s").sum(min_count=1)
            out = out.rename(columns=lambda c: c.replace("_event", "_1s"))
        elif name in ("vacuum",):
            # max within 1s for drop_*, mean for roc_*
            drop_cols = [c for c in df.columns if c.startswith("vac_")]
            roc_cols = [c for c in df.columns if c.startswith("roc_")]
            out = pd.DataFrame(index=df.resample("1s").mean().index)
            if drop_cols:
                out[drop_cols] = df[drop_cols].resample("1s").max()
            if roc_cols:
                out[roc_cols] = df[roc_cols].resample("1s").mean()
        elif name in ("momentum",):
            out = df.resample("1s").mean()
        else:
            # basic, depth, etc. -> last
            out = df.resample("1s").last()
        out_blocks.append(out)

    if not out_blocks:
        return pd.DataFrame()
    out = out_blocks[0]
    for b in out_blocks[1:]:
        out = out.join(b, how="outer")

    # forward-fill up to 1s for price-like gaps
    out = out.ffill(limit=1)
    return out

def _ofi_zscores_1s(df_1s: pd.DataFrame, ofi_levels=[1,3,5], win=60) -> pd.DataFrame:
    out = pd.DataFrame(index=df_1s.index)
    for L in ofi_levels:
        col = f"ofi_L{L}_1s"
        if col in df_1s.columns:
            out[f"ofi_L{L}_z_{win}s"] = _rolling_zscore(df_1s[col], win)
    return out

def _join_ohlcv_multi_tf(df_1s: pd.DataFrame,
                         ohlcv: Optional[Dict[str, pd.DataFrame]] = None,
                         tolerance_ms: int = 500) -> pd.DataFrame:
    """Join EMA/RV/trend from 1m/5m/15m OHLCV to 1s features."""
    if ohlcv is None:
        return pd.DataFrame(index=df_1s.index)

    out = pd.DataFrame(index=df_1s.index)
    for tf in ["1m","5m","15m"]:
        if tf not in ohlcv:
            continue
        df = ohlcv[tf].copy()
        # Expect 'time' column or DatetimeIndex
        if "time" in df.columns:
            df["time"] = pd.to_datetime(df["time"], utc=True)
            df = df.set_index("time")
        if not isinstance(df.index, pd.DatetimeIndex):
            raise ValueError(f"OHLCV[{tf}] must have datetime index or 'time' column.")
        df = df.sort_index()
        close = df["close"].astype(float)
        # EMA(20), EMA(50)
        ema20 = close.ewm(span=20, adjust=False).mean().rename(f"ema_{tf}_20")
        ema50 = close.ewm(span=50, adjust=False).mean().rename(f"ema_{tf}_50")
        # Realized volatility using squared log returns
        logret = np.log(close/close.shift(1))
        rv20 = (logret**2).rolling(20, min_periods=5).sum().rename(f"rv_{tf}_20")
        rv50 = (logret**2).rolling(50, min_periods=10).sum().rename(f"rv_{tf}_50")
        trend = (ema20 > ema50).astype(int).rename(f"trend_{tf}")
        feat_tf = pd.concat([ema20, ema50, rv20, rv50, trend], axis=1)
        # align to 1s via nearest within tolerance
        joined = pd.merge_asof(
            pd.DataFrame(index=df_1s.index),
            feat_tf.sort_index(), left_index=True, right_index=True,
            direction="backward", tolerance=pd.Timedelta(milliseconds=tolerance_ms)
        )
        out = out.join(joined)
    return out

def build_features_1s(df_lob: pd.DataFrame,
                      ohlcv_1m: Optional[pd.DataFrame] = None,
                      ohlcv_5m: Optional[pd.DataFrame] = None,
                      ohlcv_15m: Optional[pd.DataFrame] = None,
                      params: Dict = None) -> pd.DataFrame:
    """
    Build 1-second features from LOB snapshots.

    Parameters
    ----------
    df_lob : DataFrame
        Raw LOB with required columns.
    ohlcv_* : optional DataFrames with columns ['time','open','high','low','close','volume'] (UTC)
    params : dict
        Overrides DEFAULT_PARAMS.

    Returns
    -------
    DataFrame (1s index, UTC) with engineered features and targets.
    """
    P = DEFAULT_PARAMS.copy()
    if params:
        P.update(params)

    # Ensure datetime index by origin_time
    df = df_lob.copy()
    df["origin_time"] = _to_dt(df["origin_time"])
    df = df.sort_values("origin_time")
    df = df.set_index("origin_time")
    # Basic first
    basic = _build_basic(df)
    depth = _build_depth_obi(df, levels=20, obi_levels=P["obi_levels"])
    ev_blocks = {"basic": basic, "depth": depth}

    # OFI event-level
    ofi_ev = _ofi_event(df, ofi_levels=P["ofi_levels"], levels=20)
    ev_blocks["ofi"] = ofi_ev

    # Liquidity vacuum requires depths within event-level
    vac_ev = _liquidity_vacuum_event(pd.concat([depth], axis=1), obi_levels=P["obi_levels"])
    ev_blocks["vacuum"] = vac_ev

    # Momentum event-level (use basic mid/microprice)
    mom_ev = _micro_momentum_event(basic, windows_ms=P["momentum_windows_ms"])
    ev_blocks["momentum"] = mom_ev

    # Resample to 1s
    df_1s = _resample_feature_blocks(ev_blocks)

    # OFI z-scores
    zdf = _ofi_zscores_1s(df_1s, ofi_levels=P["ofi_levels"], win=P["ofi_zscore_window_seconds"])
    df_1s = df_1s.join(zdf)

    # Join OHLCV features (if provided)
    ohlcv_dict = {}
    if ohlcv_1m is not None: ohlcv_dict["1m"] = ohlcv_1m
    if ohlcv_5m is not None: ohlcv_dict["5m"] = ohlcv_5m
    if ohlcv_15m is not None: ohlcv_dict["15m"] = ohlcv_15m
    if ohlcv_dict:
        mtf = _join_ohlcv_multi_tf(df_1s, ohlcv=ohlcv_dict, tolerance_ms=P["ohlcv_join_tolerance_ms"])
        df_1s = df_1s.join(mtf)

    # Targets from 1s mid
    if "mid" in df_1s.columns:
        for h in [1,2,3]:
            df_1s[f"target_r_{h}s"] = np.log(df_1s["mid"].shift(-h) / df_1s["mid"])
            df_1s[f"target_c_{h}s"] = np.sign(df_1s[f"target_r_{h}s"]).astype("float").astype("Int64")
        # Cast classification to int8 when exporting
        df_1s[["target_c_1s","target_c_2s","target_c_3s"]] = df_1s[["target_c_1s","target_c_2s","target_c_3s"]]\
            .astype("Int64")

    # Clean: remove inf, keep NaN
    num_cols = df_1s.select_dtypes(include=[np.number]).columns
    df_1s[num_cols] = df_1s[num_cols].replace([np.inf, -np.inf], np.nan)

    return df_1s

# --- Unit test (quick smoke) ---
if __name__ == "__main__":
    import os
    sample = os.environ.get("SAMPLE_LOB", "/mnt/data/sample_BOOK_BINANCE_BTC-USDT_APR-2024_1000.csv")
    if os.path.exists(sample):
        df = pd.read_csv(sample)
        feats = build_features_1s(df)
        print(feats.head(8))
        print("Columns:", len(feats.columns))
    else:
        print("Sample file not found:", sample)


def _smoke_test(sample_path="/mnt/data/sample_BOOK_BINANCE_BTC-USDT_APR-2024_1000.csv"):
    import os
    if not os.path.exists(sample_path):
        print("Sample not found:", sample_path)
        return
    df = pd.read_csv(sample_path)
    feats = build_features_1s(df)
    # Basic sanity checks
    assert "mid" in feats.columns and "spread" in feats.columns
    assert feats.index.tz is not None  # UTC aware
    # OFI 1s columns exist
    for L in [1,3,5]:
        assert f"ofi_L{L}_1s" in feats.columns
        assert f"ofi_L{L}_z_60s" in feats.columns
    # Targets exist
    for h in [1,2,3]:
        assert f"target_r_{h}s" in feats.columns
        assert f"target_c_{h}s" in feats.columns
    print("Smoke test passed. shape=", feats.shape)
    return feats

if __name__ == "__main__":
    _ = _smoke_test()
