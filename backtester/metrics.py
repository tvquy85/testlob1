
from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Dict, Any

def sharpe(returns, scale= np.sqrt(365*24*60*60)):  # per second -> annual-ish
    r = np.asarray(returns)
    mu = np.nanmean(r); sd = np.nanstd(r, ddof=0)
    return float(mu / sd) * scale if sd > 0 else np.nan

def sortino(returns, scale= np.sqrt(365*24*60*60)):
    r = np.asarray(returns)
    dr = r[r < 0]
    dd = np.nanstd(dr, ddof=0)
    mu = np.nanmean(r)
    return float(mu / dd) * scale if dd > 0 else np.nan

def drawdown(equity):
    e = np.asarray(equity)
    peak = np.maximum.accumulate(e)
    dd = (e - peak) / peak
    return dd, float(np.min(dd))

def calmar(equity, pnl_per_sec):
    _, mdd = drawdown(equity)
    if mdd >= 0 or np.isnan(mdd):
        return np.nan
    # annualize pnl: sum per second * (seconds per year)
    ann = np.nanmean(pnl_per_sec) * (365*24*60*60)
    return float(ann / abs(mdd))

def t_stat(returns):
    r = np.asarray(returns)
    mu = np.nanmean(r); sd = np.nanstd(r, ddof=1)
    n = np.isfinite(r).sum()
    return float(mu / (sd / np.sqrt(max(1, n)))) if sd>0 and n>1 else np.nan

def hit_rate(trades_df: pd.DataFrame):
    if trades_df.empty:
        return np.nan
    wins = (trades_df["pnl"] > 0).sum()
    return float(wins / len(trades_df))

def tail_risk(returns, q=0.99):
    r = np.asarray(returns)
    if len(r)==0: return np.nan, np.nan
    var = np.nanquantile(r, 1-q)
    es = np.nanmean(r[r <= var]) if np.any(r <= var) else np.nan
    return float(var), float(es)

def turnover(trades_df: pd.DataFrame, equity0: float):
    if trades_df.empty: return 0.0
    notionals = np.abs(trades_df["qty"] * trades_df["px"])
    return float(notionals.sum() / equity0)

def summarize(equity_curve: pd.DataFrame, trades: pd.DataFrame, sec_returns: pd.Series, equity0: float) -> Dict[str, Any]:
    sharp = sharpe(sec_returns)
    sor = sortino(sec_returns)
    dd, mdd = drawdown(equity_curve["equity"].values)
    cal = calmar(equity_curve["equity"].values, sec_returns.values)
    tstat = t_stat(sec_returns.values)
    hr = hit_rate(trades.assign(pnl=trades.get("pnl", 0.0)))
    var, es = tail_risk(sec_returns.values)
    cost_bps = float( (trades["fee"].sum() / max(1e-12, (trades["qty"]*trades["px"]).abs().sum())) * 1e4 ) if not trades.empty else 0.0
    avg_slip = float(trades["slippage"].mean()) if "slippage" in trades.columns and not trades.empty else 0.0
    return {
        "Sharpe": sharp, "Sortino": sor, "Calmar": cal, "t_stat": tstat,
        "Hit_rate": hr, "MaxDD": float(mdd), "VaR_1%": var, "ES_1%": es,
        "Turnover": turnover(trades, equity0), "Cost_bps": cost_bps, "Avg_slippage": avg_slip
    }
