"""検証のパラメータ。閾値はここだけを触れば変えられるようにしておく。

J-Quants API V2 のフィールド名は V1 から短縮形に変わっている（Close -> C など）。
実データのカラム名は 00_explore_schema.py で確認したうえでここに定義する。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# --- J-Quants API V2 -------------------------------------------------------

BASE_URL = "https://api.jquants.com/v2"
API_KEY_ENV = "JQUANTS_API_KEY"

# Free プランのレート制限は 5 リクエスト/分。超過すると 429 が返り、
# 繰り返すと 5 分程度アクセスがブロックされる。
DEFAULT_REQUESTS_PER_MINUTE = 5

EP_MASTER = "/equities/master"
EP_BARS_DAILY = "/equities/bars/daily"
EP_FIN_SUMMARY = "/fins/summary"

# --- カラム名（V2 の実フィールド名）---------------------------------------
# /equities/bars/daily
DATE_COL = "Date"
CODE_COL = "Code"
CLOSE_COL = "AdjC"  # 分割調整済み終値。未調整は "C"
OPEN_COL = "AdjO"
HIGH_COL = "AdjH"
LOW_COL = "AdjL"
VOLUME_COL = "AdjVo"
MKTCAP_COL = "MktCap"  # 時価総額（百万円）

# /fins/summary
DISC_DATE_COL = "DiscDate"  # 開示日。この日以降でないと使ってはいけない
PERIOD_TYPE_COL = "CurPerType"  # 1Q / 2Q / 3Q / 4Q / 5Q / FY
EPS_COL = "EPS"  # 1 株当たり当期純利益（四半期は期初からの累計）
FORECAST_EPS_COL = "FEPS"  # 会社予想 EPS（通期）。日本の「予想 PER」の分母
BPS_COL = "BPS"  # 1 株当たり純資産
EQUITY_COL = "Eq"  # 純資産
SHAREHOLDERS_EQUITY_COL = "ShEq"  # 自己資本
NET_PROFIT_COL = "NP"  # 当期純利益
SHARES_OUT_COL = "ShOutFY"  # 期末発行済株式数（自己株式を含む）
TREASURY_SHARES_COL = "TrShFY"  # 期末自己株式数
# ROE は **比率** で返る（0.12 = 12%）。百分率と取り違えると全銘柄が条件から落ちる。
# しかも通期開示にしか入らず、通期でも 6 割程度しか埋まらないので NP / ShEq で補う。
ROE_COL = "ROE"


@dataclass(frozen=True)
class ScreenConfig:
    """買い候補の抽出条件。"""

    max_per: float = 15.0
    max_pbr: float = 1.0
    # ROE の閾値。API に合わせて **比率**で持つ（0.10 = 10%）
    min_roe: float = 0.10
    # PER の分母に何を使うか。"fy_actual" = 直近通期の実績 EPS（実績 PER）、
    # "forecast" = 会社予想 EPS（予想 PER。日本の慣行だが会社の見通しに依存する）
    eps_source: str = "fy_actual"
    # 「過去に 1 日で +10% 以上」の判定
    spike_threshold: float = 0.10
    spike_lookback_days: int = 250
    # 小型株の定義。Issue に定義がないので時価総額で切る（百万円）
    max_market_cap_mn: float = 50_000.0
    # 流動性フィルタ。売買代金が細すぎる銘柄を除く（株数）
    min_avg_volume: float = 10_000.0
    volume_window_days: int = 20


@dataclass(frozen=True)
class TradeConfig:
    """売買ルール。"""

    take_profit: float = 0.15  # +15% で利確
    stop_loss: float = 0.08  # -8% で損切り
    max_hold_days: int = 90  # 保有上限（暦日ではなく営業日）
    max_positions: int = 10  # 同時保有数の上限
    position_size: float = 1_000_000.0  # 1 建玉あたりの投下資金（円）
    # 同じ日に高値が利確・安値が損切りの両方に触れた場合、損切りを先に見る
    pessimistic_same_day: bool = True


@dataclass(frozen=True)
class Config:
    screen: ScreenConfig = field(default_factory=ScreenConfig)
    trade: TradeConfig = field(default_factory=TradeConfig)
    requests_per_minute: int = DEFAULT_REQUESTS_PER_MINUTE
    # 取得対象期間。Free プランは直近 2 年・財務は 12 週遅れ配信
    date_from: str = "2024-04-01"
    date_to: str = "2026-03-31"
    # out-of-sample 検証の分割点。この日より前を in-sample とする
    oos_split: str = "2025-10-01"
    # 動作確認用に銘柄数を絞る。None なら全銘柄
    universe_limit: int | None = 50
    cache_dir: Path = Path("data")


DEFAULT = Config()
