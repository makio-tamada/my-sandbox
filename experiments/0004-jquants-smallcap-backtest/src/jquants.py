"""J-Quants API V2 のクライアント。

V1 からの変更点で引っかかりやすいところ:

- 認証が「メール/パスワード -> refreshToken -> idToken」から **API キー 1 本**に変わった。
  ダッシュボードで発行したキーを ``x-api-key`` ヘッダに載せるだけでよい。
- エンドポイント名が変わった（``/v1/prices/daily_quotes`` -> ``/v2/equities/bars/daily`` など）。
- レスポンスは ``{"data": [...], "pagination_key": "..."}`` の封筒に入る。
- 株価のフィールドが短縮形になった（``Close`` -> ``C``、``AdjustmentClose`` -> ``AdjC``）。
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from typing import Any

import requests
from dotenv import load_dotenv

from src import config


class JQuantsError(RuntimeError):
    """API 呼び出しが回復不能な形で失敗したときに送出する。"""


class RateLimiter:
    """1 分あたりのリクエスト数を守るための単純なスロットル。

    Free プランは 5 リクエスト/分しかないので、待つこと自体が処理時間の主成分になる。
    直近 1 分間の呼び出し時刻を覚えておき、上限に達していたら最古の呼び出しが
    1 分を過ぎるまで眠る。
    """

    def __init__(self, requests_per_minute: int, sleep=time.sleep, now=time.monotonic) -> None:
        if requests_per_minute <= 0:
            raise ValueError("requests_per_minute は 1 以上にする")
        self._limit = requests_per_minute
        self._sleep = sleep
        self._now = now
        self._calls: list[float] = []

    def acquire(self) -> None:
        window_start = self._now() - 60.0
        self._calls = [t for t in self._calls if t > window_start]
        if len(self._calls) >= self._limit:
            wait = 60.0 - (self._now() - self._calls[0])
            if wait > 0:
                self._sleep(wait)
            cutoff = self._now() - 60.0
            self._calls = [t for t in self._calls if t > cutoff]
        self._calls.append(self._now())


def load_api_key() -> str:
    """リポジトリ直下の .env から API キーを読む。値そのものは決して出力しない。"""
    load_dotenv(_repo_root() / ".env")
    key = os.environ.get(config.API_KEY_ENV, "").strip()
    if not key:
        raise JQuantsError(
            f"{config.API_KEY_ENV} が未設定です。"
            " リポジトリ直下の .env に J-Quants のダッシュボードで発行した API キーを入れてください。"
        )
    return key


def _repo_root():
    from pathlib import Path

    # src/jquants.py -> src -> 0004-... -> experiments -> リポジトリ直下
    return Path(__file__).resolve().parents[3]


class JQuantsClient:
    """レート制限とページングを内側に隠した薄いラッパ。"""

    def __init__(
        self,
        api_key: str | None = None,
        requests_per_minute: int = config.DEFAULT_REQUESTS_PER_MINUTE,
        session: requests.Session | None = None,
        max_retries: int = 3,
        sleep=time.sleep,
    ) -> None:
        self._api_key = api_key or load_api_key()
        self._limiter = RateLimiter(requests_per_minute, sleep=sleep)
        self._session = session or requests.Session()
        self._max_retries = max_retries
        self._sleep = sleep
        self.request_count = 0

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{config.BASE_URL}{path}"
        headers = {"x-api-key": self._api_key}
        for attempt in range(self._max_retries + 1):
            self._limiter.acquire()
            self.request_count += 1
            response = self._session.get(url, headers=headers, params=params, timeout=60)
            if response.status_code == 429:
                # 429 を踏んだら素直に待つ。踏み続けると 5 分ブロックされる。
                if attempt == self._max_retries:
                    raise JQuantsError(f"429 が続いたため中断: {path} {params}")
                self._sleep(60.0 * (attempt + 1))
                continue
            if response.status_code >= 400:
                raise JQuantsError(f"{response.status_code} {path} {params}: {response.text[:300]}")
            return response.json()
        raise JQuantsError(f"リトライ上限に達した: {path}")

    def paginate(self, path: str, params: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """``data`` 配列のレコードを、ページングを追いながら 1 件ずつ返す。"""
        page_params = dict(params)
        while True:
            payload = self._get(path, page_params)
            yield from payload.get("data", [])
            key = payload.get("pagination_key")
            if not key:
                return
            page_params["pagination_key"] = key

    # --- 個別エンドポイント -------------------------------------------------

    def listed_master(self, date: str | None = None) -> list[dict[str, Any]]:
        """上場銘柄一覧。1 リクエストで全銘柄が返る。"""
        params: dict[str, Any] = {}
        if date:
            params["date"] = date
        return list(self.paginate(config.EP_MASTER, params))

    def daily_bars_by_date(self, date: str) -> list[dict[str, Any]]:
        """ある 1 日の全銘柄の四本値。

        銘柄ごとに引くと Free プランでは日が暮れるので、日付単位でまとめて取る。
        """
        return list(self.paginate(config.EP_BARS_DAILY, {"date": date}))

    def daily_bars_by_code(self, code: str, date_from: str, date_to: str) -> list[dict[str, Any]]:
        return list(
            self.paginate(config.EP_BARS_DAILY, {"code": code, "from": date_from, "to": date_to})
        )

    def fin_summary_by_date(self, date: str) -> list[dict[str, Any]]:
        """ある 1 日に開示された財務サマリ。開示がない日は空で返る。"""
        return list(self.paginate(config.EP_FIN_SUMMARY, {"date": date}))

    def fin_summary_by_code(self, code: str) -> list[dict[str, Any]]:
        return list(self.paginate(config.EP_FIN_SUMMARY, {"code": code}))
