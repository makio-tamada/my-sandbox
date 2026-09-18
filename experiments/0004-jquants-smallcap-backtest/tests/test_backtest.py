"""売買ルールが、値幅どおりに約定を作るかを確かめる。"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd
import pytest
from conftest import make_bars

from src import config
from src.backtest import (
    EXIT_DELISTED,
    EXIT_STOP_LOSS,
    EXIT_TAKE_PROFIT,
    EXIT_TIME_LIMIT,
    PriceSeries,
    run_backtest,
    summarize,
)
from src.config import TradeConfig

CFG = TradeConfig(take_profit=0.15, stop_loss=0.08, max_hold_days=5, max_positions=10)


def bars_from(code: str, start: str, ohlc: Sequence[tuple[float, float, float, float]]):
    dates = pd.bdate_range(start, periods=len(ohlc))
    return make_bars(
        [
            {
                "code": code,
                "date": d.strftime("%Y-%m-%d"),
                "open": o,
                "high": h,
                "low": low,
                "close": c,
            }
            for d, (o, h, low, c) in zip(dates, ohlc, strict=True)
        ]
    )


def signal_on(code: str, date: str) -> pd.DataFrame:
    return pd.DataFrame({config.DATE_COL: [pd.Timestamp(date)], config.CODE_COL: [code]})


def test_entry_is_next_day_open_not_signal_day_close():
    """シグナル日の終値では買わない。翌営業日の寄付で買う。"""
    bars = bars_from("1111", "2025-02-03", [(100, 100, 100, 100)] * 4)
    trades = run_backtest(signal_on("1111", "2025-02-03"), bars, CFG)
    assert trades["entry_date"].iloc[0] == pd.Timestamp("2025-02-04")
    assert trades["entry_price"].iloc[0] == 100


def test_take_profit_fills_at_threshold():
    """高値が +15% に届いたら、その日に利確値で約定する。"""
    bars = bars_from(
        "1111", "2025-02-03", [(100, 100, 100, 100), (100, 101, 99, 100), (100, 120, 99, 118)]
    )
    trades = run_backtest(signal_on("1111", "2025-02-03"), bars, CFG)
    trade = trades.iloc[0]
    assert trade["reason"] == EXIT_TAKE_PROFIT
    assert trade["exit_price"] == pytest.approx(115.0)
    assert trade["return"] == pytest.approx(0.15)


def test_stop_loss_fills_at_threshold():
    bars = bars_from(
        "1111", "2025-02-03", [(100, 100, 100, 100), (100, 101, 99, 100), (100, 101, 80, 85)]
    )
    trades = run_backtest(signal_on("1111", "2025-02-03"), bars, CFG)
    trade = trades.iloc[0]
    assert trade["reason"] == EXIT_STOP_LOSS
    assert trade["exit_price"] == pytest.approx(92.0)


def test_gap_down_fills_at_open_not_at_stop_price():
    """寄付がすでに損切り値を割っていたら、損切り値では逃げられない。"""
    bars = bars_from(
        "1111", "2025-02-03", [(100, 100, 100, 100), (100, 101, 99, 100), (70, 75, 68, 72)]
    )
    trades = run_backtest(signal_on("1111", "2025-02-03"), bars, CFG)
    trade = trades.iloc[0]
    assert trade["reason"] == EXIT_STOP_LOSS
    assert trade["exit_price"] == pytest.approx(70.0)
    assert trade["return"] == pytest.approx(-0.30)


def test_gap_up_fills_at_open():
    bars = bars_from(
        "1111", "2025-02-03", [(100, 100, 100, 100), (100, 101, 99, 100), (130, 135, 128, 132)]
    )
    trades = run_backtest(signal_on("1111", "2025-02-03"), bars, CFG)
    assert trades["exit_price"].iloc[0] == pytest.approx(130.0)
    assert trades["reason"].iloc[0] == EXIT_TAKE_PROFIT


def test_same_day_both_hit_takes_stop_loss_by_default():
    """日足では前後関係が分からない。既定は悲観側（損切り）を採る。"""
    bars = bars_from("1111", "2025-02-03", [(100, 100, 100, 100), (100, 120, 80, 100)])
    trades = run_backtest(signal_on("1111", "2025-02-03"), bars, CFG)
    assert trades["reason"].iloc[0] == EXIT_STOP_LOSS

    optimistic = TradeConfig(**{**CFG.__dict__, "pessimistic_same_day": False})
    trades = run_backtest(signal_on("1111", "2025-02-03"), bars, optimistic)
    assert trades["reason"].iloc[0] == EXIT_TAKE_PROFIT


def test_time_limit_exits_at_close_after_max_hold_days():
    """どちらにも触れないまま保有上限に達したら、その日の終値で手仕舞う。"""
    flat = [(100, 101, 99, 100)] * 10
    bars = bars_from("1111", "2025-02-03", flat)
    cfg = TradeConfig(**{**CFG.__dict__, "max_hold_days": 3})
    trades = run_backtest(signal_on("1111", "2025-02-03"), bars, cfg)
    trade = trades.iloc[0]
    assert trade["reason"] == EXIT_TIME_LIMIT
    assert trade["hold_days"] == 3


def test_data_ends_before_time_limit_is_marked_separately():
    """保有上限に達する前にデータが尽きたら、期限切れとは区別する。"""
    bars = bars_from("1111", "2025-02-03", [(100, 101, 99, 100)] * 3)
    trades = run_backtest(signal_on("1111", "2025-02-03"), bars, CFG)
    assert trades["reason"].iloc[0] == EXIT_DELISTED


def test_no_entry_when_signal_is_on_the_last_bar():
    bars = bars_from("1111", "2025-02-03", [(100, 101, 99, 100)] * 2)
    trades = run_backtest(signal_on("1111", "2025-02-04"), bars, CFG)
    assert trades.empty


def test_does_not_stack_positions_in_the_same_code():
    """保有中の銘柄に重ねて建てない。"""
    bars = bars_from("1111", "2025-02-03", [(100, 101, 99, 100)] * 10)
    signals = pd.DataFrame(
        {
            config.DATE_COL: pd.to_datetime(["2025-02-03", "2025-02-04", "2025-02-05"]),
            config.CODE_COL: ["1111"] * 3,
        }
    )
    trades = run_backtest(signals, bars, TradeConfig(**{**CFG.__dict__, "max_hold_days": 4}))
    assert len(trades) == 1


def test_max_positions_caps_concurrent_holdings():
    bars = pd.concat(
        [
            bars_from(code, "2025-02-03", [(100, 101, 99, 100)] * 10)
            for code in ("1111", "2222", "3333")
        ]
    )
    signals = pd.DataFrame(
        {
            config.DATE_COL: [pd.Timestamp("2025-02-03")] * 3,
            config.CODE_COL: ["1111", "2222", "3333"],
        }
    )
    cfg = TradeConfig(**{**CFG.__dict__, "max_positions": 2, "max_hold_days": 4})
    trades = run_backtest(signals, bars, cfg)
    assert len(trades) == 2
    assert trades["code"].tolist() == ["1111", "2222"]


def test_summarize_reports_win_rate_and_profit_factor():
    bars = pd.concat(
        [
            bars_from("1111", "2025-02-03", [(100, 100, 100, 100), (100, 120, 99, 118)]),
            bars_from("2222", "2025-02-03", [(100, 100, 100, 100), (100, 101, 80, 85)]),
        ]
    )
    signals = pd.DataFrame(
        {
            config.DATE_COL: [pd.Timestamp("2025-02-03")] * 2,
            config.CODE_COL: ["1111", "2222"],
        }
    )
    stats = summarize(run_backtest(signals, bars, CFG), CFG)
    assert stats["取引数"] == 2
    assert stats["勝率"] == 0.5
    # 勝ち +15% / 負け -8% なので PF は 15/8
    assert stats["プロフィットファクタ"] == pytest.approx(15 / 8, rel=1e-3)


def test_summarize_on_empty_trades():
    assert summarize(pd.DataFrame(), CFG) == {"取引数": 0}


def test_price_series_can_be_reused_across_runs():
    """条件を振って何度も回すとき、畳み込み済みの四本値を渡しても結果は変わらない。"""
    bars = bars_from("1111", "2025-02-03", [(100, 100, 100, 100), (100, 120, 99, 118)])
    signals = signal_on("1111", "2025-02-03")
    from_frame = run_backtest(signals, bars, CFG)
    prices = PriceSeries(bars)
    first = run_backtest(signals, prices, CFG)
    second = run_backtest(signals, prices, CFG)
    pd.testing.assert_frame_equal(from_frame, first)
    pd.testing.assert_frame_equal(first, second)
