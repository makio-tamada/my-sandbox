#!/usr/bin/env python
"""実データのカラム名を確認する。まずこれを実行してから src/config.py を直す。

J-Quants API V2 はフィールド名が V1 から短縮形に変わっている（Close -> C など）。
推測で書くと静かに全部 NaN になるので、実際のレスポンスを見て確かめる。

Free プランは 5 リクエスト/分。このスクリプトは 3 リクエストしか使わない。

    uv run 00_explore_schema.py
"""

from __future__ import annotations

import argparse
import json

import pandas as pd

from src import config
from src.jquants import JQuantsClient


def show(title: str, records: list[dict]) -> None:
    print(f"\n{'=' * 72}\n{title}  ({len(records)} 件)\n{'=' * 72}")
    if not records:
        print("  レコードなし")
        return
    df = pd.DataFrame(records)
    print("\n-- カラム一覧 --")
    for col in df.columns:
        non_null = int(df[col].notna().sum())
        print(f"  {col:<16} {str(df[col].dtype):<10} 非 NULL {non_null}/{len(df)}")
    print("\n-- 先頭 1 件 --")
    print(json.dumps(records[0], ensure_ascii=False, indent=2, default=str))


def check_expected(records: list[dict], expected: dict[str, str]) -> None:
    """src/config.py で参照しているカラムが実在するかを突き合わせる。"""
    if not records:
        return
    actual = set(records[0].keys())
    print("\n-- src/config.py との突き合わせ --")
    for name, col in expected.items():
        mark = "OK  " if col in actual else "無い"
        print(f"  [{mark}] {name} = {col!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="2026-06-01", help="四本値を確認する日付")
    parser.add_argument("--code", default="86970", help="財務を確認する銘柄コード")
    args = parser.parse_args()

    client = JQuantsClient(requests_per_minute=config.DEFAULT_REQUESTS_PER_MINUTE)

    master = client.listed_master()
    show(f"{config.EP_MASTER} 上場銘柄一覧", master[:3])
    print(f"\n  上場銘柄数: {len(master)}")

    bars = client.daily_bars_by_date(args.date)
    show(f"{config.EP_BARS_DAILY} 四本値 date={args.date}", bars[:3])
    check_expected(
        bars,
        {
            "CLOSE_COL": config.CLOSE_COL,
            "OPEN_COL": config.OPEN_COL,
            "HIGH_COL": config.HIGH_COL,
            "LOW_COL": config.LOW_COL,
            "VOLUME_COL": config.VOLUME_COL,
            "MKTCAP_COL": config.MKTCAP_COL,
        },
    )

    fins = client.fin_summary_by_code(args.code)
    show(f"{config.EP_FIN_SUMMARY} 財務サマリ code={args.code}", fins[:3])
    check_expected(
        fins,
        {
            "EPS_COL": config.EPS_COL,
            "BPS_COL": config.BPS_COL,
            "EQUITY_COL": config.EQUITY_COL,
            "ROE_COL": config.ROE_COL,
            "DISC_DATE_COL": config.DISC_DATE_COL,
            "PERIOD_TYPE_COL": config.PERIOD_TYPE_COL,
        },
    )
    if fins:
        periods = sorted({str(r.get(config.PERIOD_TYPE_COL)) for r in fins})
        print(f"\n  {config.PERIOD_TYPE_COL} に現れた値: {periods}")

    print(f"\n使用リクエスト数: {client.request_count}")


if __name__ == "__main__":
    main()
