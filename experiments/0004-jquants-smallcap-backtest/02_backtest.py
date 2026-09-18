#!/usr/bin/env python
"""キャッシュ済みデータでスクリーニングとバックテストを走らせる。

API は叩かないので、何度でもやり直せる。in-sample / out-of-sample の分割も行う。

    uv run 02_backtest.py
    uv run 02_backtest.py --max-per 12 --take-profit 0.20 --stop-loss 0.05
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

import pandas as pd

from src import backtest, cache, config, screener
from src.config import ScreenConfig, TradeConfig


def load_data(cache_dir: Path, universe_limit: int | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    bars = cache.normalize_bars(cache.load(cache_dir, cache.BARS))
    fins = cache.normalize_fins(cache.load(cache_dir, cache.FINS))
    if bars.empty:
        raise SystemExit("四本値のキャッシュが空です。先に 01_fetch.py を実行してください。")
    if universe_limit:
        codes = sorted(bars[config.CODE_COL].unique())[:universe_limit]
        bars = bars[bars[config.CODE_COL].isin(codes)]
        fins = fins[fins[config.CODE_COL].isin(codes)] if not fins.empty else fins
    return bars, fins


def report_period(
    label: str,
    signals: pd.DataFrame,
    bars: pd.DataFrame,
    trade_cfg: TradeConfig,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> dict:
    """期間を切るのは**候補の日付だけ**。四本値は全期間を渡す。

    四本値を先に切ってしまうと、急騰実績の参照窓（250 営業日）と保有期間が
    期間の境界で途切れてしまい、期間ごとに条件の意味が変わってしまう。
    """
    window = signals
    if start is not None:
        window = window[window[config.DATE_COL] >= start]
    if end is not None:
        window = window[window[config.DATE_COL] < end]

    candidates = window.loc[window["is_candidate"], [config.DATE_COL, config.CODE_COL]].reset_index(
        drop=True
    )
    trades = backtest.run_backtest(candidates, bars, trade_cfg)
    stats = backtest.summarize(trades, trade_cfg)

    print(f"\n{'=' * 72}\n{label}\n{'=' * 72}")
    if window.empty:
        print("  対象レコードなし")
        return {"label": label, "candidates": 0, "stats": stats, "trades": trades}
    print(
        f"シグナル対象期間: {window[config.DATE_COL].min():%Y-%m-%d} 〜 {window[config.DATE_COL].max():%Y-%m-%d}"
    )
    print(f"銘柄数: {window[config.CODE_COL].nunique()} / 候補 (銘柄×日): {len(candidates)}")
    print("\n-- 条件ごとの絞り込み --")
    print(screener.funnel(window).to_string(index=False))
    print("\n-- 成績 --")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    return {"label": label, "candidates": len(candidates), "stats": stats, "trades": trades}


def main() -> None:
    base_screen, base_trade = ScreenConfig(), TradeConfig()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=config.DEFAULT.cache_dir)
    parser.add_argument(
        "--universe-limit", type=int, default=None, help="銘柄数を絞る（動作確認用）"
    )
    parser.add_argument(
        "--oos-split", default=config.DEFAULT.oos_split, help="この日より前を in-sample"
    )
    parser.add_argument(
        "--signals-from",
        default=None,
        help="この日以降のシグナルだけを売買する。助走期間（財務の通期開示と"
        "急騰実績の参照窓が埋まるまで）を除くために使う",
    )
    parser.add_argument(
        "--eps-source",
        choices=["fy_actual", "forecast"],
        default=base_screen.eps_source,
        help="PER の分母。fy_actual = 直近通期の実績 EPS、forecast = 会社予想 EPS",
    )
    parser.add_argument("--max-per", type=float, default=base_screen.max_per)
    parser.add_argument("--max-pbr", type=float, default=base_screen.max_pbr)
    parser.add_argument("--min-roe", type=float, default=base_screen.min_roe)
    parser.add_argument("--max-mktcap-mn", type=float, default=base_screen.max_market_cap_mn)
    parser.add_argument("--take-profit", type=float, default=base_trade.take_profit)
    parser.add_argument("--stop-loss", type=float, default=base_trade.stop_loss)
    parser.add_argument("--max-hold-days", type=int, default=base_trade.max_hold_days)
    parser.add_argument("--max-positions", type=int, default=base_trade.max_positions)
    parser.add_argument("--out-dir", type=Path, default=Path("outputs"))
    args = parser.parse_args()

    screen_cfg = replace(
        base_screen,
        max_per=args.max_per,
        max_pbr=args.max_pbr,
        min_roe=args.min_roe,
        max_market_cap_mn=args.max_mktcap_mn,
        eps_source=args.eps_source,
    )
    trade_cfg = replace(
        base_trade,
        take_profit=args.take_profit,
        stop_loss=args.stop_loss,
        max_hold_days=args.max_hold_days,
        max_positions=args.max_positions,
    )

    bars, fins = load_data(args.cache_dir, args.universe_limit)
    # シグナルは全期間で 1 回だけ計算する。期間で切るのは候補の日付のみ。
    signals = screener.build_signals(bars, fins, screen_cfg)
    print(
        f"四本値 {len(bars)} 行 / {bars[config.CODE_COL].nunique()} 銘柄 / "
        f"{bars[config.DATE_COL].min():%Y-%m-%d} 〜 {bars[config.DATE_COL].max():%Y-%m-%d}"
    )

    signals_from = pd.Timestamp(args.signals_from) if args.signals_from else None
    split = pd.Timestamp(args.oos_split)

    results = [report_period("全期間", signals, bars, trade_cfg, start=signals_from)]
    if signals_from is None or split > signals_from:
        results.append(
            report_period(
                f"in-sample (< {args.oos_split})",
                signals,
                bars,
                trade_cfg,
                start=signals_from,
                end=split,
            )
        )
        results.append(
            report_period(
                f"out-of-sample (>= {args.oos_split})", signals, bars, trade_cfg, start=split
            )
        )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for result in results:
        name = result["label"].split()[0].replace("(", "").replace(")", "")
        if not result["trades"].empty:
            result["trades"].to_csv(args.out_dir / f"trades_{name}.csv", index=False)
    (args.out_dir / "summary.json").write_text(
        json.dumps(
            [{"label": r["label"], "candidates": r["candidates"], **r["stats"]} for r in results],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n結果を {args.out_dir}/ に書き出しました。")


if __name__ == "__main__":
    main()
