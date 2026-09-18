#!/usr/bin/env python
"""条件を振って、in-sample で選んだ条件が out-of-sample でも通用するかを見る。

チューニングを in-sample だけで行い、選んだ条件を out-of-sample にそのまま当てる。
両者が乖離するなら、その条件は期間に張り付いているだけということになる。

    uv run 03_tune.py
    uv run 03_tune.py --top 15
"""

from __future__ import annotations

import argparse
import itertools
import time
from dataclasses import replace
from pathlib import Path

import pandas as pd

from src import backtest, cache, config, screener
from src.config import ScreenConfig, TradeConfig

# 振る値。Issue の既定値を真ん中に置いている。
PER_GRID = [10.0, 15.0, 20.0]
PBR_GRID = [0.8, 1.0, 1.2]
ROE_GRID = [0.08, 0.10, 0.15]
TP_GRID = [0.10, 0.15, 0.20]
SL_GRID = [0.05, 0.08, 0.12]


def evaluate(
    signals: pd.DataFrame,
    prices: backtest.PriceSeries,
    trade_cfg: TradeConfig,
    start: pd.Timestamp,
    end: pd.Timestamp | None,
) -> dict:
    window = signals[signals[config.DATE_COL] >= start]
    if end is not None:
        window = window[window[config.DATE_COL] < end]
    candidates = window.loc[window["is_candidate"], [config.DATE_COL, config.CODE_COL]]
    trades = backtest.run_backtest(candidates, prices, trade_cfg)
    return backtest.summarize(trades, trade_cfg)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=config.DEFAULT.cache_dir)
    parser.add_argument("--signals-from", default="2025-07-01")
    parser.add_argument("--oos-split", default="2026-01-01")
    parser.add_argument("--top", type=int, default=10, help="in-sample の上位いくつを見るか")
    parser.add_argument("--min-trades", type=int, default=10, help="これ未満の取引数は採用しない")
    parser.add_argument("--out", type=Path, default=Path("outputs/tuning.csv"))
    args = parser.parse_args()

    bars = cache.normalize_bars(cache.load(args.cache_dir, cache.BARS))
    fins = cache.normalize_fins(cache.load(args.cache_dir, cache.FINS))
    prices = backtest.PriceSeries(bars)
    start, split = pd.Timestamp(args.signals_from), pd.Timestamp(args.oos_split)

    screen_grid = list(itertools.product(PER_GRID, PBR_GRID, ROE_GRID))
    trade_grid = list(itertools.product(TP_GRID, SL_GRID))
    total = len(screen_grid) * len(trade_grid)
    print(f"{total} 通り（スクリーニング {len(screen_grid)} × 売買 {len(trade_grid)}）")

    rows: list[dict] = []
    started = time.monotonic()
    for i, (per, pbr, roe) in enumerate(screen_grid, start=1):
        screen_cfg = replace(ScreenConfig(), max_per=per, max_pbr=pbr, min_roe=roe)
        signals = screener.build_signals(bars, fins, screen_cfg)
        for tp, sl in trade_grid:
            trade_cfg = replace(TradeConfig(), take_profit=tp, stop_loss=sl)
            ins = evaluate(signals, prices, trade_cfg, start, split)
            oos = evaluate(signals, prices, trade_cfg, split, None)
            rows.append(
                {
                    "per": per,
                    "pbr": pbr,
                    "roe": roe,
                    "tp": tp,
                    "sl": sl,
                    "is_取引数": ins.get("取引数", 0),
                    "is_勝率": ins.get("勝率"),
                    "is_平均リターン": ins.get("平均リターン"),
                    "is_PF": ins.get("プロフィットファクタ"),
                    "oos_取引数": oos.get("取引数", 0),
                    "oos_勝率": oos.get("勝率"),
                    "oos_平均リターン": oos.get("平均リターン"),
                    "oos_PF": oos.get("プロフィットファクタ"),
                }
            )
        print(
            f"  [{i}/{len(screen_grid)}] PER<={per} PBR<={pbr} ROE>={roe}  経過 {(time.monotonic() - started) / 60:.1f} 分"
        )

    df = pd.DataFrame(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)

    usable = df[(df["is_取引数"] >= args.min_trades) & (df["oos_取引数"] >= args.min_trades)]
    print(f"\n取引数 {args.min_trades} 件以上の組み合わせ: {len(usable)}/{len(df)}")
    if usable.empty:
        return

    print(f"\n=== in-sample の平均リターン上位 {args.top} 件と、その out-of-sample ===")
    top = usable.sort_values("is_平均リターン", ascending=False).head(args.top)
    print(top.to_string(index=False))

    print("\n=== in-sample と out-of-sample の順位相関 ===")
    for metric in ["平均リターン", "勝率", "PF"]:
        pair = usable[[f"is_{metric}", f"oos_{metric}"]].dropna()
        if len(pair) > 2:
            rho = pair.corr(method="spearman").iloc[0, 1]
            print(f"  {metric}: スピアマン順位相関 = {rho:+.3f}  (n={len(pair)})")

    print(f"\n結果を {args.out} に書き出しました。")


if __name__ == "__main__":
    main()
