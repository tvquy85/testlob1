
from __future__ import annotations
import argparse, json, os, sys
import pandas as pd
from pathlib import Path
from .core import run_backtest
from .utils import ensure_dt_index, TICK

def load_yaml(path: str) -> dict:
    # minimal YAML loader via json when possible; fall back to naive parse
    try:
        import yaml  # optional
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        # crude fallback: not recommended
        import re
        txt = Path(path).read_text(encoding="utf-8")
        # NOT a full YAML parser; expect user has PyYAML available for real usage.
        raise RuntimeError("Please install PyYAML to parse YAML configs.")

def default_features_fn(df_lob: pd.DataFrame, *args, **kwargs) -> pd.DataFrame:
    # Use features.py created earlier in /mnt/data
    sys.path.append("/mnt/data")
    import features as feat
    return feat.build_features_1s(df_lob, *args, **kwargs)

def default_strategy_fn(t, row, state, cfg, aux):
    # Example: no trades
    return []

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, required=True, help="Path to 06_runs_config.yml")
    parser.add_argument("--lob_csv", type=str, nargs="+", help="LOB csv files to concatenate (optional if data section provides path)")
    parser.add_argument("--outdir", type=str, default="runs_out")
    args = parser.parse_args()

    cfg = load_yaml(args.config)
    Path(args.outdir).mkdir(parents=True, exist_ok=True)

    # Load LOB data
    if args.lob_csv:
        dfs = [pd.read_csv(p) for p in args.lob_csv]
        df_lob = pd.concat(dfs, ignore_index=True)
    else:
        data = cfg.get("data", {})
        paths = data.get("paths", [])
        if not paths:
            raise RuntimeError("Please provide --lob_csv or data.paths in config.")
        dfs = [pd.read_csv(p) for p in paths]
        df_lob = pd.concat(dfs, ignore_index=True)

    results = run_backtest(cfg, df_lob, default_features_fn, default_strategy_fn, ohlcv_dict=None)

    # Save outputs
    run_id = cfg.get("run_id", "run")
    outdir = Path(args.outdir) / run_id
    outdir.mkdir(parents=True, exist_ok=True)
    results["trades"].to_csv(outdir / "trades.csv", index=False)
    results["equity_curve"].to_csv(outdir / "equity_curve.csv")
    with open(outdir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(results["metrics"], f, ensure_ascii=False, indent=2)
    print("Saved results to:", outdir)

if __name__ == "__main__":
    main()
