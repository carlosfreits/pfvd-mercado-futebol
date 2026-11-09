"""Cliente HTTP da API-Football (v3) com controle de ritmo, repetição e cota."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import requests

BASE_URL = "https://v3.football.api-sports.io"
DEFAULT_REQUESTS_PER_MINUTE = 10
RATE_LIMIT_SAFETY_FACTOR = 1.1
MAX_ATTEMPTS = 5
BASE_BACKOFF_SECONDS = 5.0
RATE_LIMIT_WAIT_SECONDS = 60.0
REQUEST_TIMEOUT_SECONDS = 60

logger = logging.getLogger(__name__)


class ApiFootballError(RuntimeError):
    """Erro definitivo da API (chave inválida, plano sem acesso, resposta inesperada)."""


class QuotaExhaustedError(ApiFootballError):
    """A cota diária acabou; a coleta pode ser retomada depois, a partir do cache."""


def _body_errors(payload: dict[str, Any]) -> dict[str, str]:
    """Normaliza o campo `errors`, que a API devolve como lista vazia ou dicionário."""
    errors = payload.get("errors")
    if not errors:
        return {}
    if isinstance(errors, dict):
        return {str(key): str(value) for key, value in errors.items()}
    return {"error": str(errors)}


class ApiFootballClient:
    """Faz GETs autenticados, respeitando o limite por minuto informado pela API."""

    def __init__(
        self,
        api_key: str,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not api_key:
            raise ValueError("API_FOOTBALL_KEY não definida.")
        self._session = session or requests.Session()
        self._headers = {"x-apisports-key": api_key}
        self._sleep = sleep
        self._clock = clock
        self._min_interval = 60.0 / DEFAULT_REQUESTS_PER_MINUTE
        self._last_request_at: float | None = None
        self.requests_made = 0

    def get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Retorna o JSON do endpoint, repetindo apenas falhas temporárias."""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self._wait_for_slot()
            response = self._send(endpoint, params)
            if response is None:
                self._backoff(attempt, f"falha de rede em {endpoint}")
                continue
            self._update_rate_limit(response)

            if response.status_code == 429:
                self._sleep(self._retry_after(response))
                continue
            if response.status_code >= 500:
                self._backoff(attempt, f"HTTP {response.status_code} em {endpoint}")
                continue
            if response.status_code != 200:
                raise ApiFootballError(f"HTTP {response.status_code} em {endpoint}.")

            payload = self._parse(response, endpoint)
            errors = _body_errors(payload)
            if not errors:
                return payload
            self._raise_or_wait(errors, endpoint)
        raise ApiFootballError(f"{endpoint}: falhou após {MAX_ATTEMPTS} tentativas.")

    def _send(self, endpoint: str, params: dict[str, Any] | None) -> requests.Response | None:
        self._last_request_at = self._clock()
        self.requests_made += 1
        try:
            return self._session.get(
                f"{BASE_URL}/{endpoint.lstrip('/')}",
                headers=self._headers,
                params=params,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            # Só o tipo da exceção: a mensagem pode conter dados da requisição.
            logger.warning("Falha de rede em %s: %s", endpoint, type(exc).__name__)
            return None

    def _wait_for_slot(self) -> None:
        if self._last_request_at is None:
            return
        remaining = self._min_interval - (self._clock() - self._last_request_at)
        if remaining > 0:
            self._sleep(remaining)

    def _update_rate_limit(self, response: requests.Response) -> None:
        limit = response.headers.get("x-ratelimit-limit")
        if limit and limit.isdigit() and int(limit) > 0:
            self._min_interval = 60.0 / int(limit) * RATE_LIMIT_SAFETY_FACTOR

    def _backoff(self, attempt: int, reason: str) -> None:
        delay = BASE_BACKOFF_SECONDS * 2 ** (attempt - 1)
        logger.warning("%s; nova tentativa em %.0fs.", reason, delay)
        self._sleep(delay)

    @staticmethod
    def _retry_after(response: requests.Response) -> float:
        value = response.headers.get("retry-after", "")
        return float(value) if value.isdigit() else RATE_LIMIT_WAIT_SECONDS

    @staticmethod
    def _parse(response: requests.Response, endpoint: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise ApiFootballError(f"{endpoint}: resposta não é JSON.") from exc
        if not isinstance(payload, dict):
            raise ApiFootballError(f"{endpoint}: formato de resposta inesperado.")
        return payload

    def _raise_or_wait(self, errors: dict[str, str], endpoint: str) -> None:
        keys = {key.lower() for key in errors}
        if "ratelimit" in keys:
            self._sleep(RATE_LIMIT_WAIT_SECONDS)
            return
        if "requests" in keys:
            raise QuotaExhaustedError(f"Cota esgotada: {errors}")
        raise ApiFootballError(f"{endpoint}: {errors}")
