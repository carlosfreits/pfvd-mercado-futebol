"""Cliente HTTP: repetição, limite de ritmo, cota e proteção da chave."""

import pytest
import requests
from client import ApiFootballClient, ApiFootballError, QuotaExhaustedError

SECRET = "chave-secreta"


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = {"errors": [], "response": []} if payload is None else payload
        self.headers = headers or {}

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self._responses = iter(responses)
        self.calls = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "params": params})
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response


def make_client(responses):
    session = FakeSession(responses)
    sleeps = []
    client = ApiFootballClient(SECRET, session=session, sleep=sleeps.append, clock=lambda: 0.0)
    return client, session, sleeps


def test_sends_key_in_header_and_not_in_params():
    client, session, _ = make_client([FakeResponse()])

    client.get("players", {"league": 71})

    assert session.calls[0]["headers"]["x-apisports-key"] == SECRET
    assert SECRET not in str(session.calls[0]["params"])
    assert session.calls[0]["url"].endswith("/players")


def test_empty_key_is_rejected():
    with pytest.raises(ValueError):
        ApiFootballClient("")


def test_http_429_waits_and_retries():
    client, _, sleeps = make_client(
        [FakeResponse(429, headers={"retry-after": "7"}), FakeResponse(payload={"errors": [], "ok": 1})]
    )

    assert client.get("players")["ok"] == 1
    assert 7.0 in sleeps


def test_rate_limit_in_body_waits_and_retries():
    client, _, sleeps = make_client(
        [
            FakeResponse(payload={"errors": {"rateLimit": "Too many requests"}}),
            FakeResponse(payload={"errors": [], "ok": 1}),
        ]
    )

    assert client.get("players")["ok"] == 1
    assert 60.0 in sleeps


def test_server_error_and_network_failure_are_retried():
    client, session, _ = make_client(
        [FakeResponse(502), requests.ConnectionError("rede"), FakeResponse(payload={"errors": [], "ok": 1})]
    )

    assert client.get("players")["ok"] == 1
    assert len(session.calls) == 3


def test_gives_up_after_maximum_attempts():
    client, session, _ = make_client([FakeResponse(500) for _ in range(5)])

    with pytest.raises(ApiFootballError, match="5 tentativas"):
        client.get("players")
    assert len(session.calls) == 5


def test_daily_quota_stops_with_specific_error():
    client, session, _ = make_client(
        [FakeResponse(payload={"errors": {"requests": "You have reached the limit"}})]
    )

    with pytest.raises(QuotaExhaustedError):
        client.get("players")
    assert len(session.calls) == 1


def test_plan_without_season_access_is_not_retried():
    client, session, _ = make_client(
        [FakeResponse(payload={"errors": {"plan": "Free plans do not have access to this season"}})]
    )

    with pytest.raises(ApiFootballError, match="Free plans"):
        client.get("players")
    assert len(session.calls) == 1


def test_invalid_json_raises_clear_error():
    client, _, _ = make_client([FakeResponse(payload=ValueError("sem json"))])

    with pytest.raises(ApiFootballError, match="não é JSON"):
        client.get("players")


def test_waits_between_requests_using_limit_from_headers():
    client, _, sleeps = make_client(
        [FakeResponse(headers={"x-ratelimit-limit": "300"}), FakeResponse()]
    )

    client.get("status")
    client.get("players")

    assert sleeps == [pytest.approx(0.22)]


def test_error_messages_do_not_expose_the_key():
    client, _, _ = make_client([FakeResponse(403)])

    with pytest.raises(ApiFootballError) as error:
        client.get("players")
    assert SECRET not in str(error.value)
