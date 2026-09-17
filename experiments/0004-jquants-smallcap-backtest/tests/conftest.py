"""テスト用の小さな合成データ。API を叩かずにロジックだけを確かめる。"""

from __future__ import annotations

import pandas as pd
import pytest

from src import config


def make_bars(rows: list[dict]) -> pd.DataFrame:
    """(Code, Date, 四本値) のリストから四本値フレームを作る。

    高値・安値を省いた場合は終値から作る（値幅判定を使わないテスト向け）。
    """
    records = []
    for row in rows:
        close = row["close"]
        records.append(
            {
                config.DATE_COL: pd.Timestamp(row["date"]),
                config.CODE_COL: row["code"],
                config.OPEN_COL: row.get("open", close),
                config.HIGH_COL: row.get("high", max(close, row.get("open", close))),
                config.LOW_COL: row.get("low", min(close, row.get("open", close))),
                config.CLOSE_COL: close,
                config.VOLUME_COL: row.get("volume", 100_000.0),
                config.MKTCAP_COL: row.get("mktcap", 10_000.0),
            }
        )
    return pd.DataFrame(records)


def make_fins(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                config.DISC_DATE_COL: r["disc_date"],
                config.CODE_COL: r["code"],
                config.PERIOD_TYPE_COL: r.get("period", "FY"),
                config.EPS_COL: r.get("eps"),
                config.BPS_COL: r.get("bps"),
                config.ROE_COL: r.get("roe"),
                config.EQUITY_COL: r.get("equity"),
            }
            for r in rows
        ]
    )


def linear_bars(code: str, start: str, closes: list[float], **kw) -> list[dict]:
    """終値の列から、営業日連番の足を作る。"""
    dates = pd.bdate_range(start, periods=len(closes))
    return [
        {"code": code, "date": d.strftime("%Y-%m-%d"), "close": c, **kw}
        for d, c in zip(dates, closes, strict=True)
    ]


@pytest.fixture
def passing_fins() -> pd.DataFrame:
    """PER/PBR/ROE の条件をすべて満たす財務。株価 1000 円を前提にした値。"""
    return make_fins(
        [{"disc_date": "2025-01-10", "code": "1111", "eps": 100.0, "bps": 2000.0, "roe": 12.0}]
    )
