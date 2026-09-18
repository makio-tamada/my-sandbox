#!/usr/bin/env python
"""スクリーニングに意味があるのかを、同じ売買ルールの帰無モデルと比べて確かめる。

成績が良く（悪く）見えても、それが地合いのせいなのかスクリーニングのおかげなのかは、
成績だけを見ても分からない。そこで 2 つの比較対象を置く。

1. **ランダム建玉**: 候補を無作為に選び、利確・損切り・保有上限は同じルールで回す。
   スクリーニングが効いているなら、実際の候補はこの分布の上側に出るはず。
2. **単純保有**: 小型株ユニバースを期間の頭から終わりまで等ウェイトで持ち続ける。

    uv run 04_benchmark.py --trials 200
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from src import backtest, cache, config, screener
from src.config import ScreenConfig, TradeConfig


def buy_and_hold(
    bars: pd.DataFrame, universe: set[str], start: pd.Timestamp, end: pd.Timestamp
) -> float:
    """期間の頭から終わりまで等ウェイトで持ち続けたときの平均リターン。"""
    window = bars[(bars[config.DATE_COL] >= start) & (bars[config.DATE_COL] < end)]
    window = window[window[config.CODE_COL].isin(universe)]
    if window.empty:
        return float("nan")
    ordered = window.sort_values(config.DATE_COL)
    first = ordered.groupby(config.CODE_COL)[config.CLOSE_COL].first()
    last = ordered.groupby(config.CODE_COL)[config.CLOSE_COL].last()
    return float((last / first - 1.0).mean())


def random_trial(
    pool: pd.DataFrame,
    n: int,
    prices: backtest.PriceSeries,
    cfg: TradeConfig,
    rng: np.random.Generator,
) -> float:
    """候補と同じ件数だけ無作為に選び、同じ売買ルールで回したときの平均リターン。"""
    picked = pool.iloc[rng.choice(len(pool), size=min(n, len(pool)), replace=False)]
    trades = backtest.run_backtest(picked, prices, cfg)
    return float(trades["return"].mean()) if not trades.empty else float("nan")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=config.DEFAULT.cache_dir)
    parser.add_argument("--signals-from", default="2025-07-01")
    parser.add_argument("--oos-split", default="2026-01-01")
    parser.add_argument("--trials", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20260918)
    args = parser.parse_args()

    bars = cache.normalize_bars(cache.load(args.cache_dir, cache.BARS))
    fins = cache.normalize_fins(cache.load(args.cache_dir, cache.FINS))
    prices = backtest.PriceSeries(bars)
    trade_cfg = TradeConfig()
    signals = screener.build_signals(bars, fins, ScreenConfig())

    start, split = pd.Timestamp(args.signals_from), pd.Timestamp(args.oos_split)
    end = bars[config.DATE_COL].max() + pd.Timedelta(days=1)
    periods = [
        ("in-sample", start, split),
        ("out-of-sample", split, end),
        ("全期間", start, end),
    ]

    rng = np.random.default_rng(args.seed)
    for label, lo, hi in periods:
        window = signals[(signals[config.DATE_COL] >= lo) & (signals[config.DATE_COL] < hi)]
        cand = window.loc[window["is_candidate"], [config.DATE_COL, config.CODE_COL]]
        actual = backtest.run_backtest(cand, prices, trade_cfg)
        actual_mean = float(actual["return"].mean()) if not actual.empty else float("nan")

        # 帰無モデルの母集団は「小型株かつ流動性あり」。割安条件と急騰実績だけを外す。
        pool_mask = window["pass_size"].fillna(False) & window["pass_liquidity"].fillna(False)
        pool = window.loc[pool_mask, [config.DATE_COL, config.CODE_COL]]
        trials = [random_trial(pool, len(cand), prices, trade_cfg, rng) for _ in range(args.trials)]
        trials_arr = np.array([t for t in trials if np.isfinite(t)])

        universe = set(window.loc[pool_mask, config.CODE_COL].unique())
        bh = buy_and_hold(bars, universe, lo, hi)

        pct = float((trials_arr < actual_mean).mean()) if len(trials_arr) else float("nan")
        print(f"\n=== {label}  ({lo:%Y-%m-%d} 〜 {hi:%Y-%m-%d}) ===")
        print(f"  スクリーニング後   : 取引 {len(actual):>3} 件 / 平均リターン {actual_mean:+.4f}")
        print(
            f"  ランダム建玉 {len(trials_arr)} 回 : 平均 {trials_arr.mean():+.4f} / 標準偏差 {trials_arr.std():.4f}"
            f" / 5-95% [{np.percentile(trials_arr, 5):+.4f}, {np.percentile(trials_arr, 95):+.4f}]"
        )
        print(f"  → スクリーニングはランダムの {pct:.1%} 分位")
        print(f"  小型株ユニバースの単純保有 : {bh:+.4f}")


if __name__ == "__main__":
    main()
