"""取得したデータのローカルキャッシュ。

Free プランは 5 リクエスト/分なので、1 年分の日次データを集めるだけで 1 時間近くかかる。
途中で止めても取り直さずに済むよう、日付ごとに 1 ファイルで保存し、
すでにあるファイルはスキップする（空の日も空ファイルを置いて「取得済み」を記録する）。

``data/`` は .gitignore 済みなのでコミットされない。
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pandas as pd

from src import config

BARS = "bars"
FINS = "fins"


def _path(cache_dir: Path, kind: str, date: str) -> Path:
    return cache_dir / kind / f"{date.replace('-', '')}.parquet"


def has(cache_dir: Path, kind: str, date: str) -> bool:
    return _path(cache_dir, kind, date).exists()


def save(cache_dir: Path, kind: str, date: str, records: list[dict]) -> None:
    path = _path(cache_dir, kind, date)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(records).to_parquet(path, index=False)


def load(cache_dir: Path, kind: str) -> pd.DataFrame:
    """その種別のキャッシュを 1 枚の DataFrame にまとめて返す。"""
    directory = cache_dir / kind
    files = sorted(directory.glob("*.parquet")) if directory.exists() else []
    frames = [pd.read_parquet(f) for f in files]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def cached_dates(cache_dir: Path, kind: str) -> list[str]:
    directory = cache_dir / kind
    if not directory.exists():
        return []
    return sorted(p.stem for p in directory.glob("*.parquet"))


def normalize_bars(raw: pd.DataFrame) -> pd.DataFrame:
    """API のレスポンスを、スクリーナーが前提とする型にそろえる。"""
    if raw.empty:
        return raw
    df = raw.copy()
    df[config.DATE_COL] = pd.to_datetime(df[config.DATE_COL])
    df[config.CODE_COL] = df[config.CODE_COL].astype(str)
    numeric = [
        config.OPEN_COL,
        config.HIGH_COL,
        config.LOW_COL,
        config.CLOSE_COL,
        config.VOLUME_COL,
        config.MKTCAP_COL,
    ]
    for col in numeric:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    # 売買停止日などは四本値が欠ける。値幅判定ができないので落とす。
    required = [config.OPEN_COL, config.HIGH_COL, config.LOW_COL, config.CLOSE_COL]
    present = [c for c in required if c in df.columns]
    return df.dropna(subset=present).reset_index(drop=True)


def normalize_fins(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return raw
    df = raw.copy()
    df[config.CODE_COL] = df[config.CODE_COL].astype(str)
    return df


def business_days(date_from: str, date_to: str) -> Iterable[str]:
    """土日を除いた日付を YYYY-MM-DD で返す。祝日は API が空で返すのでそのまま投げる。"""
    days = pd.bdate_range(date_from, date_to)
    return [d.strftime("%Y-%m-%d") for d in days]
