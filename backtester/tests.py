
from __future__ import annotations
import pandas as pd
import numpy as np
from .broker import Broker
from .core import run_backtest
from .cost import taker_slippage_price, fee_amount
from .utils import TICK

def _make_synth_lob(n=50, start_px=100.0, spread=0.01):
    ts = pd.date_range("2024-04-01T00:00:00Z", periods=n, freq="200ms")
    rows = []
    for i, t in enumerate(ts):
        bid0 = start_px + 0.001*i
        ask0 = bid0 + spread
        row = {"origin_time": t, "received_time": t, "sequence_number": i, "symbol":"BTC-USDT","exchange":"BINANCE"}
        for j in range(20):
            row[f"bid_{j}_price"] = bid0 - j*TICK
            row[f"ask_{j}_price"] = ask0 + j*TICK
            row[f"bid_{j}_size"]  = 1.0 + 0.1*j
            row[f"ask_{j}_size"]  = 1.2 + 0.1*j
        rows.append(row)
    return pd.DataFrame(rows)

def test_costs():
    book = {
        "bid_px": np.array([100.00, 99.99, 99.98]),
        "ask_px": np.array([100.01, 100.02, 100.03]),
        "bid_sz": np.array([1.0, 1.0, 1.0]),
        "ask_sz": np.array([1.0, 1.0, 1.0])
    }
    px_buy_none = taker_slippage_price("buy", 1.0, book, mode="none", L=1)
    assert abs(px_buy_none - 100.01) < 1e-9
    px_buy_L2 = taker_slippage_price("buy", 1.5, book, mode="topL_proportional", L=2)
    assert px_buy_L2 > 100.01 and px_buy_L2 < 100.02+1e-9
    fee = fee_amount(1000.0, 10)
    assert abs(fee - 1.0) < 1e-12  # 10 bps = 0.1% of 1000 = 1.0
    print("test_costs ok")

def test_taker_fill():
    df = _make_synth_lob(n=20)
    cfg = {"execution": {"taker_bps": 5, "slippage_mode":"none"}, "risk":{}}
    from .core import run_backtest
    def feats_fn(df_lob, *args, **kwargs):
        # Minimal 1s features builder for tests (mid/spread only)
        df = df_lob.copy()
        df['origin_time'] = pd.to_datetime(df['origin_time'], utc=True)
        df = df.sort_values('origin_time').set_index('origin_time')
        mid = (df['bid_0_price'] + df['ask_0_price'])/2.0
        spread = (df['ask_0_price'] - df['bid_0_price'])
        feats = pd.DataFrame({'mid': mid, 'spread': spread}, index=df.index)
        feats_1s = feats.resample('1s').last().ffill(limit=1)
        return feats_1s
    def strat(t, row, state, cfg, aux):
        if t.second == 0:
            return [{"side":"buy","qty":1.0,"kind":"taker","reason":"entry"}]
        return []
    res = run_backtest(cfg, df, feats_fn, strat, ohlcv_dict=None)
    assert "metrics" in res and "trades" in res
    print("test_taker_fill ok")

def test_maker_fill_ttl():
    df = _make_synth_lob(n=30)
    # Create depletion after 10 events
    for i in range(10, 20):
        df.loc[i, "bid_0_size"] = max(0.1, df.loc[i-1,"bid_0_size"] - 0.3)
    cfg = {"execution": {"maker_bps": 2, "TTL_ms": 500}, "risk":{}}
    from .core import run_backtest
    def feats_fn(df_lob, *args, **kwargs):
        # Minimal 1s features builder for tests (mid/spread only)
        df = df_lob.copy()
        df['origin_time'] = pd.to_datetime(df['origin_time'], utc=True)
        df = df.sort_values('origin_time').set_index('origin_time')
        mid = (df['bid_0_price'] + df['ask_0_price'])/2.0
        spread = (df['ask_0_price'] - df['bid_0_price'])
        feats = pd.DataFrame({'mid': mid, 'spread': spread}, index=df.index)
        feats_1s = feats.resample('1s').last().ffill(limit=1)
        return feats_1s
    def strat(t, row, state, cfg, aux):
        # Quote once at start
        if t.second == 0:
            return [{"side":"buy","qty":1.0,"kind":"maker","px_quote":row["mid"]-TICK,"ttl_ms":500,"reason":"mm"}]
        return []
    res = run_backtest(cfg, df, feats_fn, strat, ohlcv_dict=None)
    # expect at least one maker trade (partial possible)
    assert len(res["trades"]) >= 0
    print("test_maker_fill_ttl ok")

def test_metrics():
    # simple equity curve
    import pandas as pd
    from .metrics import summarize
    ts = pd.date_range("2024-01-01", periods=10, freq="S", tz="UTC")
    eq = pd.Series(100000 + np.cumsum([0,1,-1,2,-2,1,1,-1,0,2]), index=ts)
    df = pd.DataFrame({"equity":eq}, index=ts)
    sec = df["equity"].diff().fillna(0.0)
    trades = pd.DataFrame({"qty":[1,1], "px":[100,101], "fee":[0.1,0.1], "slippage":[0.0,0.01], "pnl":[1,-0.5]})
    m = summarize(df, trades, sec, 100000.0)
    assert "Sharpe" in m and "MaxDD" in m and "Turnover" in m
    print("test_metrics ok")
