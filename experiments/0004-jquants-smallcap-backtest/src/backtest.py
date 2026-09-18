"""値幅ルール（利確 / 損切り / 保有上限）のバックテスト。

約定の置き方:

- シグナル日 t の**翌営業日の寄付**で買う。t の終値で判定して t の終値で買うと先読みになる。
- 手仕舞いは日中の高値・安値で判定する。ただし寄付がすでに閾値を超えていたら寄付値で約定させる
  （ギャップを無視して閾値ちょうどで約定させると、成績が実態より良く出る）。
- 同じ日に高値が利確・安値が損切りの両方に触れた場合、どちらが先かは日足では分からない。
  既定では損切りを先に見る（悲観側）。

手数料・スリッページ・売買代金に対する建玉の大きさは考慮していない。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src import config
from src.config import TradeConfig

EXIT_TAKE_PROFIT = "利確"
EXIT_STOP_LOSS = "損切り"
EXIT_TIME_LIMIT = "期限切れ"
EXIT_DELISTED = "データ終端"


@dataclass
class _Bar:
    date: pd.Timestamp
    open: float
    high: float
    low: float
    close: float


class PriceSeries:
    """四本値を銘柄ごとの配列に畳んだもの。

    条件を振って何度もバックテストを回すとき、この変換が実行時間の大半を占める。
    一度作って使い回せるようにクラスにしてある。
    """

    def __init__(self, bars: pd.DataFrame) -> None:
        df = bars.sort_values([config.CODE_COL, config.DATE_COL])
        self.by_code: dict[str, list[_Bar]] = {}
        for code, group in df.groupby(config.CODE_COL, sort=False):
            self.by_code[str(code)] = [
                _Bar(d, o, h, low, c)
                for d, o, h, low, c in zip(
                    group[config.DATE_COL],
                    group[config.OPEN_COL],
                    group[config.HIGH_COL],
                    group[config.LOW_COL],
                    group[config.CLOSE_COL],
                    strict=True,
                )
            ]
        self.index_of: dict[str, dict[pd.Timestamp, int]] = {
            code: {bar.date: i for i, bar in enumerate(bar_list)}
            for code, bar_list in self.by_code.items()
        }


def _resolve_exit(entry_price: float, bar: _Bar, cfg: TradeConfig) -> tuple[float, str] | None:
    """1 本の足で手仕舞い条件に触れたかを判定し、(約定値, 理由) を返す。"""
    tp_price = entry_price * (1.0 + cfg.take_profit)
    sl_price = entry_price * (1.0 - cfg.stop_loss)

    hit_sl = bar.low <= sl_price
    hit_tp = bar.high >= tp_price

    if hit_sl and hit_tp:
        if cfg.pessimistic_same_day:
            return (min(bar.open, sl_price), EXIT_STOP_LOSS)
        return (max(bar.open, tp_price), EXIT_TAKE_PROFIT)
    if hit_sl:
        # 寄付がすでに損切り値を下回っていたら、その寄付値でしか逃げられない
        return (min(bar.open, sl_price), EXIT_STOP_LOSS)
    if hit_tp:
        return (max(bar.open, tp_price), EXIT_TAKE_PROFIT)
    return None


def run_backtest(
    candidates: pd.DataFrame,
    bars: pd.DataFrame | PriceSeries,
    cfg: TradeConfig | None = None,
) -> pd.DataFrame:
    """候補リストを順に建玉にしていき、約定した取引の一覧を返す。

    candidates は ``screen()`` の戻り値（Date, Code を含む）を想定する。
    bars には四本値そのものでも、畳み込み済みの ``PriceSeries`` でも渡せる。
    """
    cfg = cfg or TradeConfig()
    prices = bars if isinstance(bars, PriceSeries) else PriceSeries(bars)
    series, index_of = prices.by_code, prices.index_of

    trades: list[dict] = []
    # code -> 手仕舞い日。保有中の銘柄を重ねて買わないための記録
    open_until: dict[str, pd.Timestamp] = {}
    # 同時保有数の上限を守るため、建玉ごとの (建玉日, 手仕舞い日) を持つ
    open_spans: list[tuple[pd.Timestamp, pd.Timestamp]] = []

    ordered = candidates.sort_values([config.DATE_COL, config.CODE_COL])
    for row in ordered.itertuples():
        code = str(getattr(row, config.CODE_COL))
        signal_date = getattr(row, config.DATE_COL)
        bar_list = series.get(code)
        if not bar_list:
            continue
        signal_idx = index_of[code].get(signal_date)
        if signal_idx is None or signal_idx + 1 >= len(bar_list):
            continue  # 翌営業日の足がない = 買えない

        entry_bar = bar_list[signal_idx + 1]
        if code in open_until and entry_bar.date <= open_until[code]:
            continue  # すでに保有中
        concurrent = sum(1 for start, end in open_spans if start <= entry_bar.date <= end)
        if concurrent >= cfg.max_positions:
            continue
        entry_price = entry_bar.open
        if not np.isfinite(entry_price) or entry_price <= 0:
            continue

        limit_idx = signal_idx + 1 + cfg.max_hold_days
        last_idx = min(limit_idx, len(bar_list) - 1)
        exit_price = entry_bar.close
        exit_date = entry_bar.date
        for i in range(signal_idx + 1, last_idx + 1):
            bar = bar_list[i]
            resolved = _resolve_exit(entry_price, bar, cfg)
            if resolved is not None:
                exit_price, reason = resolved
                exit_date = bar.date
                break
            exit_price, exit_date = bar.close, bar.date
        else:
            # 一度も閾値に触れなかった。保有上限に達したのか、データが尽きたのか。
            reason = EXIT_TIME_LIMIT if last_idx == limit_idx else EXIT_DELISTED

        ret = exit_price / entry_price - 1.0
        trades.append(
            {
                "signal_date": signal_date,
                "code": code,
                "entry_date": entry_bar.date,
                "entry_price": entry_price,
                "exit_date": exit_date,
                "exit_price": exit_price,
                "reason": reason,
                "hold_days": index_of[code][exit_date] - (signal_idx + 1),
                "return": ret,
                "pnl": ret * cfg.position_size,
            }
        )
        open_until[code] = exit_date
        open_spans.append((entry_bar.date, exit_date))

    return pd.DataFrame(trades)


def summarize(trades: pd.DataFrame, cfg: TradeConfig | None = None) -> dict:
    """取引一覧を、レポートに貼れる粒度の指標にまとめる。"""
    cfg = cfg or TradeConfig()
    if trades.empty:
        return {"取引数": 0}

    rets = trades["return"]
    wins = trades[rets > 0]
    losses = trades[rets <= 0]
    gross_win = wins["pnl"].sum()
    gross_loss = -losses["pnl"].sum()
    equity = trades.sort_values("exit_date")["pnl"].cumsum()
    drawdown = (equity.cummax() - equity).max()

    return {
        "取引数": int(len(trades)),
        "勝率": round(float(len(wins) / len(trades)), 4),
        "平均リターン": round(float(rets.mean()), 4),
        "中央値リターン": round(float(rets.median()), 4),
        "合計損益(円)": round(float(trades["pnl"].sum()), 0),
        "プロフィットファクタ": (
            round(float(gross_win / gross_loss), 3) if gross_loss > 0 else None
        ),
        "最大ドローダウン(円)": round(float(drawdown), 0) if len(equity) else 0.0,
        "平均保有日数": round(float(trades["hold_days"].mean()), 1),
        "決済理由": trades["reason"].value_counts().to_dict(),
    }
