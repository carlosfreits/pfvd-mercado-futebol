"""Coleta estatísticas de jogadores na API-Football e grava os CSVs do projeto.

Exige plano pago: o Free bloqueia temporadas a partir de 2025 (use daily.py).

Uso (a partir da raiz do repositório):
    python collect/api_football/run.py --check
    python collect/api_football/run.py --league Brasileirao_A --season 2026
    python collect/api_football/run.py
    python collect/api_football/run.py --refresh   # atualiza temporadas parciais

A chave vem de API_FOOTBALL_KEY (variável de ambiente ou .env na raiz).
As páginas baixadas ficam em cache, então uma coleta interrompida retoma sem gastar cota de novo.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from client import ApiFootballClient, ApiFootballError, QuotaExhaustedError
from dotenv import load_dotenv
from mapping import SeasonContext, map_players

SCRAPER_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRAPER_DIR.parents[2]
DATA_DIR = REPO_ROOT / "data" / "raw" / "api_football"
ENV_FILE = REPO_ROOT / ".env"

logger = logging.getLogger("api_football")


@dataclass(frozen=True)
class SeasonTarget:
    """Uma combinação de liga e temporada resolvida contra o catálogo da API."""

    league: str
    label: str
    api_year: int
    league_id: int | None
    is_partial: bool
    problem: str | None


def load_config() -> dict[str, Any]:
    return json.loads((SCRAPER_DIR / "config.json").read_text(encoding="utf-8"))


def seasons_for(league: dict[str, Any], config: dict[str, Any]) -> list[str]:
    key = "split_seasons" if league["format"] == "split" else "calendar_seasons"
    return list(config[key])


def _find_league(league: dict[str, Any], catalog: list[dict[str, Any]]) -> dict[str, Any] | None:
    names = {name.lower() for name in league["api_names"]}
    matches = [
        entry
        for entry in catalog
        if (entry.get("country") or {}).get("name") == league["country"]
        and (entry.get("league") or {}).get("type") == "League"
        and str((entry.get("league") or {}).get("name", "")).lower() in names
    ]
    return matches[0] if len(matches) == 1 else None


def _season_problem(season: dict[str, Any] | None, year: int) -> str | None:
    if season is None:
        return f"temporada {year} não existe na API"
    coverage = season.get("coverage") or {}
    has_player_stats = coverage.get("players") or (coverage.get("fixtures") or {}).get(
        "statistics_players"
    )
    return None if has_player_stats else "sem cobertura de estatísticas de jogadores"


def resolve_targets(
    config: dict[str, Any], catalog: list[dict[str, Any]], today: date
) -> list[SeasonTarget]:
    """Cruza a configuração com /leagues; nada de ID de liga fixado no código."""
    targets = []
    for league in config["leagues"]:
        entry = _find_league(league, catalog)
        for label in seasons_for(league, config):
            year = int(label[:4])
            if entry is None:
                problem = f"liga não identificada de forma única: {league['api_names']}"
                targets.append(SeasonTarget(league["id"], label, year, None, False, problem))
                continue
            season = next((s for s in entry.get("seasons") or [] if s.get("year") == year), None)
            end = str((season or {}).get("end") or "")
            targets.append(
                SeasonTarget(
                    league=league["id"],
                    label=label,
                    api_year=year,
                    league_id=entry["league"]["id"],
                    is_partial=(not end) or date.fromisoformat(end) >= today,
                    problem=_season_problem(season, year),
                )
            )
    return targets


def select_targets(
    targets: Sequence[SeasonTarget], league: str | None, season: str | None
) -> list[SeasonTarget]:
    return [
        target
        for target in targets
        if (league is None or target.league == league)
        and (season is None or target.label == season)
    ]


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def fetch_page(
    client: ApiFootballClient, target: SeasonTarget, page: int, raw_dir: Path
) -> dict[str, Any]:
    """Retorna a página do cache; sem cache, baixa e grava."""
    cache_file = raw_dir / f"page_{page:03d}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))
    params = {"league": target.league_id, "season": target.api_year, "page": page}
    payload = client.get("players", params)
    _write_json_atomic(cache_file, payload)
    return payload


def fetch_all_items(
    client: ApiFootballClient, target: SeasonTarget, raw_dir: Path
) -> list[dict[str, Any]]:
    first = fetch_page(client, target, 1, raw_dir)
    total_pages = int((first.get("paging") or {}).get("total") or 1)
    items = list(first.get("response") or [])
    for page in range(2, total_pages + 1):
        items.extend(fetch_page(client, target, page, raw_dir).get("response") or [])
    return items


def _write_csv_atomic(rows: list[dict[str, Any]], path: Path) -> None:
    temporary = path.with_suffix(".tmp")
    pd.DataFrame(rows).to_csv(temporary, index=False, encoding="utf-8")
    temporary.replace(path)


def collect_target(
    client: ApiFootballClient,
    target: SeasonTarget,
    data_dir: Path,
    refresh: bool,
    today: date,
) -> tuple[int, int]:
    """Coleta uma liga/temporada e grava os CSVs só depois de ter todas as páginas."""
    folder = f"{target.league}_{target.label}"
    raw_dir = data_dir / "raw" / folder
    if refresh and target.is_partial and raw_dir.exists():
        shutil.rmtree(raw_dir)
    items = fetch_all_items(client, target, raw_dir)
    context = SeasonContext(target.league_id, target.is_partial, today.isoformat())
    outfield, keepers = map_players(items, context)
    if not outfield or not keepers:
        raise ApiFootballError(f"{folder}: a API não retornou jogadores suficientes.")
    output_dir = data_dir / "player_data" / folder
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv_atomic(outfield, output_dir / "jogadores.csv")
    _write_csv_atomic(keepers, output_dir / "goleiros.csv")
    return len(outfield), len(keepers)


def report_status(client: ApiFootballClient) -> None:
    response = client.get("status").get("response") or {}
    subscription = response.get("subscription") or {}
    requests_info = response.get("requests") or {}
    logger.info(
        "Plano: %s | ativo: %s | hoje: %s de %s requisições",
        subscription.get("plan"),
        subscription.get("active"),
        requests_info.get("current"),
        requests_info.get("limit_day"),
    )


def report_targets(targets: Sequence[SeasonTarget]) -> None:
    for target in targets:
        state = target.problem or ("parcial" if target.is_partial else "completa")
        logger.info(
            "%-20s %-10s id=%-6s ano_api=%s  %s",
            target.league,
            target.label,
            target.league_id,
            target.api_year,
            state,
        )


def collect_all(
    client: ApiFootballClient, targets: Sequence[SeasonTarget], refresh: bool, today: date
) -> int:
    """Coleta os alvos; cota esgotada interrompe a execução, sem perder o cache."""
    failures = 0
    for target in targets:
        logger.info("Coletando %s %s...", target.league, target.label)
        try:
            outfield, keepers = collect_target(client, target, DATA_DIR, refresh, today)
            logger.info(
                "  %d jogadores de linha, %d goleiros (%d requisições até agora)",
                outfield,
                keepers,
                client.requests_made,
            )
        except QuotaExhaustedError as exc:
            logger.error("%s Rode o mesmo comando depois para retomar.", exc)
            return 2
        except ApiFootballError as exc:
            logger.error("Falhou: %s", exc)
            failures += 1
    return 1 if failures else 0


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="só verifica cota e cobertura")
    parser.add_argument("--league", help="ex.: Brasileirao_A")
    parser.add_argument("--season", help="ex.: 2026 ou 2025-2026")
    parser.add_argument(
        "--refresh", action="store_true", help="baixa de novo as temporadas parciais"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args(argv)
    load_dotenv(ENV_FILE)
    api_key = os.environ.get("API_FOOTBALL_KEY", "").strip()
    if not api_key:
        logger.error("Defina API_FOOTBALL_KEY em %s.", ENV_FILE)
        return 2

    today = date.today()
    client = ApiFootballClient(api_key)
    try:
        report_status(client)
        catalog = client.get("leagues").get("response") or []
    except ApiFootballError as exc:
        logger.error("Não foi possível consultar a API: %s", exc)
        return 2

    targets = select_targets(resolve_targets(load_config(), catalog, today), args.league, args.season)
    if not targets:
        logger.error("Nenhuma liga/temporada corresponde aos filtros.")
        return 2
    report_targets(targets)
    if any(target.problem for target in targets):
        logger.error("Há ligas sem cobertura: a coleta não foi iniciada.")
        return 1
    if args.check:
        return 0
    status = collect_all(client, targets, args.refresh, today)
    logger.info("Requisições usadas nesta execução: %d", client.requests_made)
    return status


if __name__ == "__main__":
    sys.exit(main())
