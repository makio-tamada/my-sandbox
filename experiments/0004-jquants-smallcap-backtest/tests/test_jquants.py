"""API クライアントのレート制限とページングを、実際には叩かずに確かめる。"""

from __future__ import annotations

import pytest
import requests

from src import config
from src.jquants import JQuantsClient, JQuantsError, RateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds


def test_rate_limiter_allows_burst_up_to_limit():
    clock = FakeClock()
    limiter = RateLimiter(5, sleep=clock.sleep, now=clock.now)
    for _ in range(5):
        limiter.acquire()
    assert clock.slept == []


def test_rate_limiter_sleeps_on_the_sixth_call_within_a_minute():
    """Free プランの 5 リクエスト/分。6 本目は 1 分あくまで待たされる。"""
    clock = FakeClock()
    limiter = RateLimiter(5, sleep=clock.sleep, now=clock.now)
    for _ in range(5):
        limiter.acquire()
    limiter.acquire()
    assert clock.slept == [60.0]


def test_rate_limiter_does_not_sleep_when_the_window_has_passed():
    clock = FakeClock()
    limiter = RateLimiter(5, sleep=clock.sleep, now=clock.now)
    for _ in range(5):
        limiter.acquire()
    clock.t += 61.0
    limiter.acquire()
    assert clock.slept == []


def test_rate_limiter_rejects_zero():
    with pytest.raises(ValueError):
        RateLimiter(0)


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload


class FakeSession(requests.Session):
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[dict] = []

    def get(self, url, headers=None, params=None, timeout=None):  # type: ignore[override]
        self.calls.append({"url": url, "headers": headers, "params": dict(params or {})})
        return self.responses.pop(0)


def make_client(responses: list[FakeResponse], clock: FakeClock | None = None) -> JQuantsClient:
    clock = clock or FakeClock()
    return JQuantsClient(
        api_key="dummy",
        requests_per_minute=100,
        session=FakeSession(responses),
        sleep=clock.sleep,
    )


def test_api_key_is_sent_in_the_x_api_key_header():
    """V2 は refreshToken ではなく x-api-key ヘッダ。"""
    client = make_client([FakeResponse(200, {"data": []})])
    client.listed_master()
    session: FakeSession = client._session  # type: ignore[assignment]
    assert session.calls[0]["headers"] == {"x-api-key": "dummy"}
    assert session.calls[0]["url"] == f"{config.BASE_URL}{config.EP_MASTER}"


def test_pagination_follows_pagination_key():
    responses = [
        FakeResponse(200, {"data": [{"Code": "1111"}], "pagination_key": "p1"}),
        FakeResponse(200, {"data": [{"Code": "2222"}]}),
    ]
    client = make_client(responses)
    records = client.daily_bars_by_date("2025-02-03")
    assert [r["Code"] for r in records] == ["1111", "2222"]
    session: FakeSession = client._session  # type: ignore[assignment]
    assert session.calls[1]["params"]["pagination_key"] == "p1"
    assert client.request_count == 2


def test_429_is_retried_after_waiting():
    clock = FakeClock()
    responses = [FakeResponse(429), FakeResponse(200, {"data": [{"Code": "1111"}]})]
    client = make_client(responses, clock)
    assert client.daily_bars_by_date("2025-02-03") == [{"Code": "1111"}]
    assert clock.slept == [60.0]


def test_429_gives_up_after_max_retries():
    clock = FakeClock()
    client = JQuantsClient(
        api_key="dummy",
        requests_per_minute=100,
        session=FakeSession([FakeResponse(429) for _ in range(3)]),
        max_retries=2,
        sleep=clock.sleep,
    )
    with pytest.raises(JQuantsError, match="429"):
        client.daily_bars_by_date("2025-02-03")


def test_http_error_is_raised_with_context():
    client = make_client([FakeResponse(403, text="Forbidden")])
    with pytest.raises(JQuantsError, match="403"):
        client.listed_master()
