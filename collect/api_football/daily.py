"""Coleta gratuita da API-Football, partida por partida, dentro da janela do plano Free.

O plano Free bloqueia `season` a partir de 2025, mas libera partidas de ontem a amanhã.
Este script baixa as partidas encerradas dessa janela e acumula os totais dos jogadores.
A cota que sobra busca os elencos (/players/squads), que trazem idade e posição.

Rode uma vez por dia para não perder partidas; passar de 2 dias perde partidas de vez:
    uv run python collect/api_football/daily.py

Depois, atualize a base dos gráficos:
    uv run python -m src.build_seasons

O histórico fica no Drive do projeto: baixe-o antes de coletar (veja CLAUDE.md).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from client import ApiFootballClient, ApiFootballError, QuotaExhaustedError
from dotenv import load_dotenv
from fixture_mapping import FixtureContext, aggregate_appearances, fixture_appearances
from mapping import PLAYER_ID_PREFIX, POSITION_CODES
from run import DATA_DIR, ENV_FILE, _write_csv_atomic, _write_json_atomic, load_config

FINISHED_STATUSES = {"FT", "AET", "PEN"}
DEFAULT_MAX_REQUESTS = 90

logger = logging.getLogger("api_football.daily")


def league_index(config: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {league["api_id"]: league for league in config["leagues"]}


def season_label(league: dict[str, Any], year: int) -> str:
    return f"{year}-{year + 1}" if league["format"] == "split" else str(year)


def window_dates(today: date) -> list[str]:
    """Datas já iniciadas dentro da janela: amanhã ainda não tem partida encerrada."""
    return [(today - timedelta(days=1)).isoformat(), today.isoformat()]


def fixture_file(raw_dir: Path, league: dict[str, Any], fixture: dict[str, Any]) -> Path:
    label = season_label(league, fixture["league"]["season"])
    return raw_dir / f"{league['id']}_{label}" / f"{fixture['fixture']['id']}.json"


def finished_fixtures(
    client: ApiFootballClient, day: str, leagues: dict[int, dict[str, Any]]
) -> list[dict[str, Any]]:
    response = client.get("fixtures", {"date": day}).get("response") or []
    return [
        fixture
        for fixture in response
        if fixture["league"]["id"] in leagues
        and fixture["fixture"]["status"]["short"] in FINISHED_STATUSES
    ]


def download_fixture(
    client: ApiFootballClient, fixture: dict[str, Any], destination: Path
) -> bool:
    """Grava a partida; sem estatísticas, não grava para tentar de novo depois."""
    players = client.get("fixtures/players", {"fixture": fixture["fixture"]["id"]}).get("response") or []
    if not players:
        return False
    teams = fixture["teams"]
    record = {
        "fixture_id": fixture["fixture"]["id"],
        "date": fixture["fixture"]["date"][:10],
        "goals_by_team": {
            str(teams["home"]["id"]): fixture["goals"]["home"],
            str(teams["away"]["id"]): fixture["goals"]["away"],
        },
        "players": players,
    }
    _write_json_atomic(destination, record)
    return True


def collect_window(
    client: ApiFootballClient,
    days: Sequence[str],
    leagues: dict[int, dict[str, Any]],
    raw_dir: Path,
    max_requests: int,
) -> dict[str, int]:
    """Baixa as partidas pendentes, sem ultrapassar o limite de requisições da execução."""
    summary = {"downloaded": 0, "already_cached": 0, "without_stats": 0, "pending": 0}
    for day in days:
        if client.requests_made >= max_requests:
            logger.warning("Limite da execução atingido antes de consultar %s.", day)
            break
        for fixture in finished_fixtures(client, day, leagues):
            league = leagues[fixture["league"]["id"]]
            destination = fixture_file(raw_dir, league, fixture)
            if destination.exists():
                summary["already_cached"] += 1
            elif client.requests_made >= max_requests:
                summary["pending"] += 1
            elif download_fixture(client, fixture, destination):
                summary["downloaded"] += 1
            else:
                summary["without_stats"] += 1
    return summary


def collected_team_ids(raw_dir: Path) -> list[int]:
    """Lista os times que já têm partidas guardadas."""
    team_ids: set[int] = set()
    for path in raw_dir.glob("*/*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        team_ids.update(entry["team"]["id"] for entry in record["players"])
    return sorted(team_ids)


def collect_squads(
    client: ApiFootballClient, raw_dir: Path, squads_dir: Path, max_requests: int
) -> dict[str, int]:
    """Baixa os elencos ainda não guardados, usando a cota que sobrou das partidas."""
    summary = {"downloaded": 0, "pending": 0}
    for team_id in collected_team_ids(raw_dir):
        destination = squads_dir / f"{team_id}.json"
        if destination.exists():
            continue
        if client.requests_made >= max_requests:
            summary["pending"] += 1
            continue
        response = client.get("players/squads", {"team": team_id}).get("response") or []
        if response:
            _write_json_atomic(destination, response[0])
            summary["downloaded"] += 1
    return summary


def load_profiles(squads_dir: Path) -> dict[str, dict[str, Any]]:
    """Lê idade e posição dos elencos guardados, por `player_id`."""
    profiles: dict[str, dict[str, Any]] = {}
    for path in sorted(squads_dir.glob("*.json")):
        squad = json.loads(path.read_text(encoding="utf-8"))
        for player in squad.get("players") or []:
            profiles[f"{PLAYER_ID_PREFIX}{player['id']}"] = {
                "Age": player.get("age"),
                "Pos": POSITION_CODES.get(player.get("position"), ""),
            }
    return profiles


def _load_appearances(folder: Path) -> list[dict[str, Any]]:
    appearances = []
    for path in sorted(folder.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        goals = {int(team): value for team, value in record["goals_by_team"].items()}
        context = FixtureContext(record["fixture_id"], record["date"], goals)
        appearances.extend(fixture_appearances(record["players"], context))
    return appearances


def rebuild_csvs(
    raw_dir: Path,
    output_dir: Path,
    today: date,
    profiles: dict[str, dict[str, Any]] | None = None,
) -> dict[str, tuple[int, int, int]]:
    """Recalcula os CSVs de cada liga/temporada a partir de todas as partidas guardadas."""
    results = {}
    for folder in sorted(path for path in raw_dir.iterdir() if path.is_dir()):
        appearances = _load_appearances(folder)
        if not appearances:
            continue
        outfield, keepers = aggregate_appearances(appearances, today.isoformat(), profiles)
        target = output_dir / folder.name
        target.mkdir(parents=True, exist_ok=True)
        if outfield:
            _write_csv_atomic(outfield, target / "jogadores.csv")
        if keepers:
            _write_csv_atomic(keepers, target / "goleiros.csv")
        results[folder.name] = (len(list(folder.glob("*.json"))), len(outfield), len(keepers))
    return results


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-requests", type=int, default=DEFAULT_MAX_REQUESTS, help="limite desta execução"
    )
    parser.add_argument(
        "--rebuild-only", action="store_true", help="só recalcula os CSVs, sem usar a API"
    )
    parser.add_argument(
        "--first-run", action="store_true", help="começa um histórico novo, sem as partidas do Drive"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args(argv)
    load_dotenv(ENV_FILE)
    today = datetime.now(UTC).date()
    raw_dir = DATA_DIR / "raw" / "fixtures"
    raw_dir.mkdir(parents=True, exist_ok=True)
    squads_dir = DATA_DIR / "raw" / "squads"
    squads_dir.mkdir(parents=True, exist_ok=True)
    status = 0

    if not (args.rebuild_only or args.first_run or any(raw_dir.glob("*/*.json"))):
        logger.error(
            "Nenhuma partida em %s. Baixe o histórico do Drive antes de coletar (veja CLAUDE.md): "
            "sem ele, os CSVs seriam recalculados só com as partidas novas. "
            "Para começar do zero de propósito, use --first-run.",
            raw_dir,
        )
        return 2

    if not args.rebuild_only:
        api_key = os.environ.get("API_FOOTBALL_KEY", "").strip()
        if not api_key:
            logger.error("Defina API_FOOTBALL_KEY em %s.", ENV_FILE)
            return 2
        client = ApiFootballClient(api_key)
        leagues = league_index(load_config())
        try:
            summary = collect_window(client, window_dates(today), leagues, raw_dir, args.max_requests)
            logger.info("Partidas: %s | requisições: %d", summary, client.requests_made)
            if summary["pending"]:
                logger.warning("Faltaram %d partidas: rode de novo dentro da janela.", summary["pending"])
            squads = collect_squads(client, raw_dir, squads_dir, args.max_requests)
            logger.info("Elencos: %s | requisições: %d", squads, client.requests_made)
        except QuotaExhaustedError as exc:
            logger.error("%s Os dados já baixados serão aproveitados.", exc)
            status = 2
        except ApiFootballError as exc:
            logger.error("Falha na API: %s", exc)
            status = 1

    results = rebuild_csvs(raw_dir, DATA_DIR / "player_data", today, load_profiles(squads_dir))
    for name, (matches, outfield, keepers) in results.items():
        logger.info("%-30s %3d partidas | %4d de linha | %3d goleiros", name, matches, outfield, keepers)
    return status


if __name__ == "__main__":
    sys.exit(main())
