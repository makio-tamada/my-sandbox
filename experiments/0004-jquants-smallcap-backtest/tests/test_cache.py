"""キャッシュの往復と正規化を確かめる。"""

from __future__ import annotations

import pandas as pd

from src import cache, config


def test_save_and_load_roundtrip(tmp_path):
    cache.save(tmp_path, cache.BARS, "2025-02-03", [{"Code": "1111", "AdjC": 100.0}])
    cache.save(tmp_path, cache.BARS, "2025-02-04", [{"Code": "1111", "AdjC": 101.0}])
    loaded = cache.load(tmp_path, cache.BARS)
    assert len(loaded) == 2
    assert cache.cached_dates(tmp_path, cache.BARS) == ["20250203", "20250204"]


def test_empty_day_is_recorded_as_fetched(tmp_path):
    """開示のない日も空ファイルを置き、再取得しない。"""
    cache.save(tmp_path, cache.FINS, "2025-02-03", [])
    assert cache.has(tmp_path, cache.FINS, "2025-02-03")
    assert cache.load(tmp_path, cache.FINS).empty


def test_load_missing_directory_returns_empty(tmp_path):
    assert cache.load(tmp_path, cache.BARS).empty


def test_normalize_bars_drops_rows_without_ohlc():
    """売買停止日は四本値が欠ける。値幅判定ができないので落とす。"""
    raw = pd.DataFrame(
        [
            {
                config.DATE_COL: "2025-02-03",
                config.CODE_COL: 1111,
                config.OPEN_COL: 100,
                config.HIGH_COL: 101,
                config.LOW_COL: 99,
                config.CLOSE_COL: 100,
            },
            {
                config.DATE_COL: "2025-02-04",
                config.CODE_COL: 1111,
                config.OPEN_COL: None,
                config.HIGH_COL: None,
                config.LOW_COL: None,
                config.CLOSE_COL: None,
            },
        ]
    )
    out = cache.normalize_bars(raw)
    assert len(out) == 1
    assert out[config.CODE_COL].iloc[0] == "1111"
    assert out[config.DATE_COL].iloc[0] == pd.Timestamp("2025-02-03")


def test_business_days_excludes_weekends():
    days = list(cache.business_days("2025-02-01", "2025-02-05"))
    assert days == ["2025-02-03", "2025-02-04", "2025-02-05"]
