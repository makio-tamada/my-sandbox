#!/usr/bin/env python
"""四本値と財務サマリを日付単位で取得し、data/ にキャッシュする。

銘柄ごとに引くと 4000 銘柄 = 4000 リクエスト = Free プランで 13 時間かかる。
日付単位なら 1 営業日 1 リクエストで全銘柄が返るので、1 年分でも約 245 リクエスト
（5 リクエスト/分なら約 50 分）で済む。

途中で止めても取得済みの日はスキップするので、何度でも再開できる。

    uv run 01_fetch.py --from 2025-04-01 --to 2026-03-31
    uv run 01_fetch.py --from 2025-04-01 --to 2026-03-31 --max-requests 20   # 少しだけ試す
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from src import cache, config
from src.jquants import JQuantsClient


def fetch_range(
    client: JQuantsClient,
    cache_dir: Path,
    kinds: list[str],
    date_from: str,
    date_to: str,
    max_requests: int | None,
) -> None:
    dates = list(cache.business_days(date_from, date_to))
    todo = [(kind, d) for d in dates for kind in kinds if not cache.has(cache_dir, kind, d)]
    done = len(dates) * len(kinds) - len(todo)
    print(f"対象 {len(dates)} 営業日 × {len(kinds)} 種別 / 取得済み {done} / これから {len(todo)}")
    if max_requests is not None:
        todo = todo[:max_requests]
        print(f"--max-requests により {len(todo)} 件に制限")

    started = time.monotonic()
    for i, (kind, date) in enumerate(todo, start=1):
        if kind == cache.BARS:
            records = client.daily_bars_by_date(date)
        else:
            records = client.fin_summary_by_date(date)
        cache.save(cache_dir, kind, date, records)
        elapsed = time.monotonic() - started
        print(f"[{i}/{len(todo)}] {kind} {date}: {len(records):>5} 件  経過 {elapsed / 60:.1f} 分")

    print(
        f"\n完了。使用リクエスト数 {client.request_count} / 経過 {(time.monotonic() - started) / 60:.1f} 分"
    )
    for kind in kinds:
        print(f"  {kind}: {len(cache.cached_dates(cache_dir, kind))} 日分をキャッシュ済み")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="date_from", default=config.DEFAULT.date_from)
    parser.add_argument("--to", dest="date_to", default=config.DEFAULT.date_to)
    parser.add_argument(
        "--kind", choices=[cache.BARS, cache.FINS, "both"], default="both", help="取得する種別"
    )
    parser.add_argument("--max-requests", type=int, default=None, help="今回の実行で使う上限")
    parser.add_argument("--rpm", type=int, default=config.DEFAULT_REQUESTS_PER_MINUTE)
    parser.add_argument("--cache-dir", type=Path, default=config.DEFAULT.cache_dir)
    args = parser.parse_args()

    kinds = [cache.BARS, cache.FINS] if args.kind == "both" else [args.kind]
    client = JQuantsClient(requests_per_minute=args.rpm)
    fetch_range(client, args.cache_dir, kinds, args.date_from, args.date_to, args.max_requests)


if __name__ == "__main__":
    main()
