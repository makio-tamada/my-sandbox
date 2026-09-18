"""買い候補の抽出。

先読み（look-ahead bias）を避けるため、ある日 t の判定に使ってよいのは
「t 時点で公開されていた情報」だけに限る。具体的には

- 株価は t までの四本値
- 財務は ``DiscDate <= t`` の開示のみ

とし、エントリーは t の翌営業日の寄付とする（バックテスト側の責務）。

PER の分母は年次の EPS でなければ意味が壊れるので、四半期開示（1Q〜3Q）の
累計 EPS は使わず、直近の通期（``CurPerType == "FY"``）開示の EPS を使う。
``eps_source="forecast"`` にすると会社予想 EPS（``FEPS``）を使う「予想 PER」に切り替わる。
一方 BPS は期末時点の残高なので、期種別を問わず直近の開示を使う。

実データで分かった落とし穴（00_explore_schema.py と実際の取得結果より）:

- ``ROE`` は **比率**で返る（0.12 = 12%）。百分率と取り違えると条件が全滅する。
- ``ROE`` は通期開示にしか入らず、通期でも 19/33 しか埋まっていない。``NP / ShEq`` で補う。
- ``BPS`` は 32/115 しか埋まっていない。``ShEq / (ShOutFY - TrShFY)`` で補うと 95/115 になる。
- 数値はすべて文字列（空文字を含む）で返るので、必ず数値化してから使う。
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
    """財務サマリを、銘柄 × 開示日で 1 行にそろえ、欠けている指標を補う。

    同じ日に訂正開示などで複数行が来ることがあるので、最後の 1 行を採用する。
    """
    df = fins.copy()
    df[config.DISC_DATE_COL] = pd.to_datetime(df[config.DISC_DATE_COL])

    numeric_cols = [
        config.EPS_COL,
        config.FORECAST_EPS_COL,
        config.BPS_COL,
        config.ROE_COL,
        config.EQUITY_COL,
        config.SHAREHOLDERS_EQUITY_COL,
        config.NET_PROFIT_COL,
        config.SHARES_OUT_COL,
        config.TREASURY_SHARES_COL,
    ]
    for col in numeric_cols:
        # API は数値も文字列で返し、欠測は空文字。to_numeric で NaN に倒す。
        # 列そのものが無いこともある（プランや開示種別による）ので、その場合は全 NaN にする。
        source = df[col] if col in df.columns else pd.Series(pd.NA, index=df.index)
        df[col] = pd.to_numeric(source, errors="coerce")

    equity = df[config.SHAREHOLDERS_EQUITY_COL]
    shares = df[config.SHARES_OUT_COL] - df[config.TREASURY_SHARES_COL].fillna(0)
    shares = shares.where(shares > 0)

    # BPS は 3 割弱しか開示されないので、自己資本 / 自己株式控除後の株式数で補う。
    df["bps_used"] = df[config.BPS_COL].fillna(equity / shares)

    # ROE は通期にしか入らない。四半期の NP は期初からの累計なので、
    # 通期以外の行で NP / ShEq を計算すると過小になる。通期に限って補う。
    is_fy = df[config.PERIOD_TYPE_COL] == FY_PERIOD
    roe_fallback = (df[config.NET_PROFIT_COL] / equity.where(equity > 0)).where(is_fy)
    df["roe_used"] = df[config.ROE_COL].fillna(roe_fallback)

    df["eps_fy_actual"] = df[config.EPS_COL].where(is_fy)
    df["eps_forecast"] = df[config.FORECAST_EPS_COL]

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

    # ROE と実績 EPS は年次の指標なので通期開示だけを使う
    fy = fin[fin[config.PERIOD_TYPE_COL] == FY_PERIOD]
    df = _asof_join(prepared, fy, ["eps_fy_actual", "roe_used"], "_fy")
    # BPS（期末残高）と会社予想 EPS は期種別を問わず直近の開示を使う
    df = _asof_join(df, fin, ["bps_used", "eps_forecast"], "_last")

    if cfg.eps_source == "forecast":
        eps = df["eps_forecast_last"]
    elif cfg.eps_source == "fy_actual":
        eps = df["eps_fy_actual_fy"]
    else:
        raise ValueError(f"eps_source は 'fy_actual' か 'forecast': {cfg.eps_source!r}")

    bps = df["bps_used_last"]
    close = df[config.CLOSE_COL]

    # 赤字（EPS <= 0）・債務超過（BPS <= 0）は割安とは言えないので除く
    df["eps_used"] = eps
    df["per"] = close.where(eps > 0) / eps.where(eps > 0)
    df["pbr"] = close.where(bps > 0) / bps.where(bps > 0)
    df["roe"] = df["roe_used_fy"]

    df["pass_per"] = df["per"].between(0, cfg.max_per, inclusive="right")
    df["pass_pbr"] = df["pbr"].between(0, cfg.max_pbr, inclusive="right")
    df["pass_roe"] = df["roe"] >= cfg.min_roe
    df["pass_spike"] = df["has_spike"].fillna(False)
    # 時価総額が無い銘柄（ETF・REIT など）はここで落ちる
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
