"""スクリーニング条件が、想定どおりに通し／落としをするかを確かめる。"""

from __future__ import annotations

import pandas as pd
import pytest
from conftest import linear_bars, make_bars, make_fins

from src import config
from src.config import ScreenConfig
from src.screener import build_signals, funnel, prepare_bars, screen

CFG = ScreenConfig(spike_lookback_days=10, volume_window_days=5, min_avg_volume=1.0)


def flat_bars(code="1111", start="2025-02-03", n=12, close=1000.0, **kw):
    return linear_bars(code, start, [close] * n, **kw)


def test_spike_flag_detects_10_percent_day():
    """前日比 +10% を一度でも出したら、その日以降は急騰実績ありになる。"""
    bars = make_bars(linear_bars("1111", "2025-02-03", [100.0, 100.0, 111.0, 111.0]))
    prepared = prepare_bars(bars, CFG)
    assert list(prepared["has_spike"]) == [False, False, True, True]


def test_spike_flag_expires_after_lookback():
    """急騰が参照窓から外れたら実績なしに戻る。"""
    closes = [100.0, 111.0] + [111.0] * 8
    bars = make_bars(linear_bars("1111", "2025-02-03", closes))
    prepared = prepare_bars(bars, ScreenConfig(spike_lookback_days=3, volume_window_days=3))
    assert prepared["has_spike"].tolist()[1:4] == [True, True, True]
    assert prepared["has_spike"].iloc[5] is False or not prepared["has_spike"].iloc[5]


def test_9_9_percent_is_not_a_spike():
    """閾値ちょうど未満は急騰と見なさない。"""
    bars = make_bars(linear_bars("1111", "2025-02-03", [100.0, 109.9]))
    assert not prepare_bars(bars, CFG)["has_spike"].iloc[1]


def test_candidate_passes_all_conditions(passing_fins):
    bars = make_bars(
        linear_bars("1111", "2025-02-03", [900.0, 1000.0] + [1000.0] * 8, mktcap=10_000.0)
    )
    candidates = screen(bars, passing_fins, CFG)
    assert not candidates.empty
    assert candidates[config.CODE_COL].unique().tolist() == ["1111"]


@pytest.mark.parametrize(
    ("field", "value", "failing"),
    [
        ("eps", 50.0, "pass_per"),  # PER = 1000/50 = 20 > 15
        ("bps", 900.0, "pass_pbr"),  # PBR = 1000/900 = 1.11 > 1.0
        ("roe", 8.0, "pass_roe"),  # ROE 8% < 10%
    ],
)
def test_each_condition_rejects(field, value, failing):
    fin = {"disc_date": "2025-01-10", "code": "1111", "eps": 100.0, "bps": 2000.0, "roe": 12.0}
    fin[field] = value
    bars = make_bars(linear_bars("1111", "2025-02-03", [900.0, 1000.0] + [1000.0] * 8))
    signals = build_signals(bars, make_fins([fin]), CFG)
    assert not signals[failing].iloc[-1]
    assert not signals["is_candidate"].any()


def test_negative_eps_is_rejected():
    """赤字銘柄の PER は負になる。割安として拾ってはいけない。"""
    fins = make_fins(
        [{"disc_date": "2025-01-10", "code": "1111", "eps": -100.0, "bps": 2000.0, "roe": 12.0}]
    )
    bars = make_bars(linear_bars("1111", "2025-02-03", [900.0, 1000.0] + [1000.0] * 8))
    signals = build_signals(bars, fins, CFG)
    assert not signals["pass_per"].any()


def test_market_cap_filter_excludes_large_cap(passing_fins):
    bars = make_bars(
        linear_bars("1111", "2025-02-03", [900.0, 1000.0] + [1000.0] * 8, mktcap=999_999.0)
    )
    signals = build_signals(bars, passing_fins, ScreenConfig(**{**CFG.__dict__}))
    assert not signals["pass_size"].any()


def test_financials_are_not_used_before_disclosure():
    """開示日より前の日に、その開示の数字を使ってはいけない（先読み防止）。"""
    fins = make_fins(
        [{"disc_date": "2025-02-10", "code": "1111", "eps": 100.0, "bps": 2000.0, "roe": 12.0}]
    )
    bars = make_bars(linear_bars("1111", "2025-02-03", [900.0, 1000.0] + [1000.0] * 8))
    signals = build_signals(bars, fins, CFG)
    before = signals[signals[config.DATE_COL] < pd.Timestamp("2025-02-10")]
    after = signals[signals[config.DATE_COL] >= pd.Timestamp("2025-02-10")]
    assert before["per"].isna().all()
    assert after["per"].notna().all()


def test_quarterly_eps_is_not_used_for_per():
    """四半期の累計 EPS を年次として使うと PER が過小に出る。FY だけを使う。"""
    fins = make_fins(
        [
            {
                "disc_date": "2025-01-10",
                "code": "1111",
                "period": "1Q",
                "eps": 100.0,
                "bps": 2000.0,
                "roe": 12.0,
            }
        ]
    )
    bars = make_bars(linear_bars("1111", "2025-02-03", [900.0, 1000.0] + [1000.0] * 8))
    signals = build_signals(bars, fins, CFG)
    assert signals["per"].isna().all()
    # BPS は期種別を問わず使うので、PBR は算出される
    assert signals["pbr"].notna().any()


def test_funnel_is_monotonically_decreasing(passing_fins):
    bars = make_bars(flat_bars(n=12))
    signals = build_signals(bars, passing_fins, CFG)
    counts = funnel(signals)["残数"].tolist()
    assert counts == sorted(counts, reverse=True)
