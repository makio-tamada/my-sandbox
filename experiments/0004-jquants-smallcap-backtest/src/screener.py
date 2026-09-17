"""買い候補の抽出。

先読み（look-ahead bias）を避けるため、ある日 t の判定に使ってよいのは
「t 時点で公開されていた情報」だけに限る。具体的には

- 株価は t までの四本値
- 財務は ``DiscDate <= t`` の開示のみ

とし、エントリーは t の翌営業日の寄付とする（バックテスト側の責務）。

PER の分母は年次の EPS でなければ意味が壊れるので、四半期開示（1Q〜4Q）の
累計 EPS は使わず、直近の通期（``CurPerType == "FY"``）開示の EPS を使う。
一方 BPS は期末時点の残高なので、期種別を問わず直近の開示を使う。
"""

from __future__ import annotations

import pandas as pd

from src import config
from src.config import ScreenConfig

FY_PERIOD = "FY"


def prepare_bars(bars: pd.DataFrame, cfg: ScreenConfig) -> pd.DataFrame:
    """四本値に、スクリーニングで使う派生列を足す。

    ``has_spike`` は「その日までの過去 N 営業日に +threshold 以上の日があったか」。
    当日を含めるので、当日急騰した銘柄もその日から候補になる。
    """
    df = bars.sort_values([config.CODE_COL, config.DATE_COL]).reset_index(drop=True)
    grouped = df.groupby(config.CODE_COL, sort=False)

    df["ret"] = grouped[config.CLOSE_COL].pct_change()
    spike_day = (df["ret"] >= cfg.spike_threshold).astype(float)
    df["has_spike"] = (
        spike_day.groupby(df[config.CODE_COL], sort=False)
        .rolling(cfg.spike_lookback_days, min_periods=1)
        .max()
        .reset_index(level=0, drop=True)
        .astype(bool)
    )
    df["avg_volume"] = (
        grouped[config.VOLUME_COL]
        .rolling(cfg.volume_window_days, min_periods=1)
        .mean()
        .reset_index(level=0, drop=True)
    )
    return df


def prepare_fins(fins: pd.DataFrame) -> pd.DataFrame:
    """財務サマリを、銘柄 × 開示日で 1 行にそろえる。

    同じ日に訂正開示などで複数行が来ることがあるので、最後の 1 行を採用する。
    """
    df = fins.copy()
    df[config.DISC_DATE_COL] = pd.to_datetime(df[config.DISC_DATE_COL])
    for col in (config.EPS_COL, config.BPS_COL, config.ROE_COL, config.EQUITY_COL):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.sort_values([config.CODE_COL, config.DISC_DATE_COL])
    return df.drop_duplicates([config.CODE_COL, config.DISC_DATE_COL], keep="last")


def _asof_join(
    bars: pd.DataFrame, fins: pd.DataFrame, cols: list[str], suffix: str
) -> pd.DataFrame:
    """各 (銘柄, 日付) に、その日までの直近開示を貼り付ける。"""
    right = fins[[config.CODE_COL, config.DISC_DATE_COL, *cols]].dropna(
        subset=[config.DISC_DATE_COL]
    )
    right = right.sort_values(config.DISC_DATE_COL)
    left = bars.sort_values(config.DATE_COL)
    merged = pd.merge_asof(
        left,
        right,
        left_on=config.DATE_COL,
        right_on=config.DISC_DATE_COL,
        by=config.CODE_COL,
        direction="backward",
        allow_exact_matches=True,  # 開示は引け後。エントリーは翌日寄付なので当日開示も使える
    )
    return merged.rename(columns={c: f"{c}{suffix}" for c in [*cols, config.DISC_DATE_COL]})


def build_signals(
    bars: pd.DataFrame, fins: pd.DataFrame, cfg: ScreenConfig | None = None
) -> pd.DataFrame:
    """各 (銘柄, 日付) について PER / PBR / ROE と各条件の通過可否を計算する。"""
    cfg = cfg or ScreenConfig()
    prepared = prepare_bars(bars, cfg)
    fin = prepare_fins(fins)

    # EPS と ROE は年次の指標なので通期開示だけを使う
    fy = fin[fin[config.PERIOD_TYPE_COL] == FY_PERIOD]
    df = _asof_join(prepared, fy, [config.EPS_COL, config.ROE_COL], "_fy")
    # BPS は期末残高なので期種別を問わず直近を使う
    df = _asof_join(df, fin, [config.BPS_COL], "_last")

    eps = df[f"{config.EPS_COL}_fy"]
    bps = df[f"{config.BPS_COL}_last"]
    close = df[config.CLOSE_COL]

    df["per"] = close.where(eps > 0) / eps.where(eps > 0)
    df["pbr"] = close.where(bps > 0) / bps.where(bps > 0)
    df["roe"] = df[f"{config.ROE_COL}_fy"]

    df["pass_per"] = df["per"].between(0, cfg.max_per, inclusive="right")
    df["pass_pbr"] = df["pbr"].between(0, cfg.max_pbr, inclusive="right")
    df["pass_roe"] = df["roe"] >= cfg.min_roe
    df["pass_spike"] = df["has_spike"].fillna(False)
    df["pass_size"] = df[config.MKTCAP_COL] <= cfg.max_market_cap_mn
    df["pass_liquidity"] = df["avg_volume"] >= cfg.min_avg_volume

    pass_cols = [c for c in df.columns if c.startswith("pass_")]
    df["is_candidate"] = df[pass_cols].all(axis=1)
    return df.sort_values([config.DATE_COL, config.CODE_COL]).reset_index(drop=True)


def screen(bars: pd.DataFrame, fins: pd.DataFrame, cfg: ScreenConfig | None = None) -> pd.DataFrame:
    """買い候補だけを (日付, 銘柄) で返す。"""
    signals = build_signals(bars, fins, cfg)
    cols = [config.DATE_COL, config.CODE_COL, config.CLOSE_COL, "per", "pbr", "roe"]
    return signals.loc[signals["is_candidate"], cols].reset_index(drop=True)


def funnel(signals: pd.DataFrame) -> pd.DataFrame:
    """どの条件で何件落ちたかを数える。条件の効き方を見るための欄。"""
    pass_cols = [c for c in signals.columns if c.startswith("pass_")]
    rows = [{"条件": "全 (銘柄, 日) レコード", "残数": len(signals)}]
    mask = pd.Series(True, index=signals.index)
    for col in pass_cols:
        mask &= signals[col].fillna(False)
        rows.append({"条件": col, "残数": int(mask.sum())})
    return pd.DataFrame(rows)
