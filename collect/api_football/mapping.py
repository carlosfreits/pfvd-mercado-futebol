"""Conversão pura do JSON de /players para as colunas usadas pelo projeto.

Valor nulo na API continua nulo aqui: a ausência de uma métrica nunca vira 0.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

DATA_SOURCE = "api_football"
PLAYER_ID_PREFIX = "af_"
POSITION_CODES = {
    "Goalkeeper": "GK",
    "Defender": "DF",
    "Midfielder": "MF",
    "Attacker": "FW",
}


@dataclass(frozen=True)
class SeasonContext:
    """Identifica a coleta à qual as linhas pertencem."""

    league_id: int
    is_partial: bool
    collected_at: str


def _section(stats: dict[str, Any], name: str) -> dict[str, Any]:
    return stats.get(name) or {}


def _number(value: Any) -> float | None:
    """Converte números vindos como texto; nulo ou inválido vira None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _per90(value: float | None, minutes_90s: float | None) -> float | None:
    if value is None or not minutes_90s:
        return None
    return round(value / minutes_90s, 2)


def _pct(part: float | None, total: float | None) -> float | None:
    if part is None or not total:
        return None
    return round(part / total * 100, 1)


def _add(*values: float | None) -> float | None:
    """Soma ignorando nulos; só retorna None se todos forem nulos."""
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def _subtract(value: float | None, other: float | None) -> float | None:
    if value is None:
        return None
    return value - (other or 0)


def _identity(player: dict[str, Any], stats: dict[str, Any], position: str) -> dict[str, Any]:
    birth_date = str(_section(player, "birth").get("date") or "")
    height = str(player.get("height") or "").replace(" ", "")
    weight = str(player.get("weight") or "").replace(" ", "")
    return {
        "Player": player.get("name"),
        "first_name": player.get("firstname"),
        "last_name": player.get("lastname"),
        "Nation": player.get("nationality"),
        "Pos": position,
        "position": position,
        "Squad": _section(stats, "team").get("name"),
        "team_id": _section(stats, "team").get("id"),
        "Age": player.get("age"),
        "Born": birth_date[:4] or None,
        "height": height or None,
        "weight": weight or None,
        "player_id": f"{PLAYER_ID_PREFIX}{player.get('id')}",
    }


def _playing_time(stats: dict[str, Any]) -> dict[str, Any]:
    games = _section(stats, "games")
    minutes = _number(games.get("minutes"))
    # A API escreve "appearences"; a grafia correta fica como alternativa.
    appearances = games.get("appearences", games.get("appearances"))
    return {
        "games": _number(appearances),
        "games_starts": _number(games.get("lineups")),
        "games_subs": _number(_section(stats, "substitutes").get("in")),
        "minutes": minutes,
        "minutes_90s": round(minutes / 90, 2) if minutes else None,
        "api_rating": _number(games.get("rating")),
    }


def _attack(stats: dict[str, Any], minutes_90s: float | None) -> dict[str, Any]:
    goals_section = _section(stats, "goals")
    shots_section = _section(stats, "shots")
    goals = _number(goals_section.get("total"))
    assists = _number(goals_section.get("assists"))
    shots = _number(shots_section.get("total"))
    on_target = _number(shots_section.get("on"))
    return {
        "goals": goals,
        "assists": assists,
        "goals_assists": _add(goals, assists),
        "shots": shots,
        "shots_on_target": on_target,
        "shots_on_target_pct": _pct(on_target, shots),
        "goals_per90": _per90(goals, minutes_90s),
        "assists_per90": _per90(assists, minutes_90s),
        "goals_assists_per90": _per90(_add(goals, assists), minutes_90s),
        "shots_per90": _per90(shots, minutes_90s),
        "shots_on_target_per90": _per90(on_target, minutes_90s),
    }


def _penalties(stats: dict[str, Any], goals: float | None) -> dict[str, Any]:
    penalty = _section(stats, "penalty")
    scored = _number(penalty.get("scored"))
    missed = _number(penalty.get("missed"))
    # A API escreve "commited"; a grafia correta fica como alternativa.
    conceded = penalty.get("commited", penalty.get("committed"))
    return {
        "pens_made": scored,
        "pens_att": _add(scored, missed),
        "pens_won": _number(penalty.get("won")),
        "pens_conceded": _number(conceded),
        "goals_pens": _subtract(goals, scored),
    }


def _passing(stats: dict[str, Any]) -> dict[str, Any]:
    passes = _section(stats, "passes")
    return {
        "passes": _number(passes.get("total")),
        "assisted_shots": _number(passes.get("key")),
        # Sem confirmação de que é percentual: não alimenta o rating.
        "passes_accuracy_raw": _number(passes.get("accuracy")),
    }


def _defending(stats: dict[str, Any]) -> dict[str, Any]:
    tackles = _section(stats, "tackles")
    duels = _section(stats, "duels")
    fouls = _section(stats, "fouls")
    cards = _section(stats, "cards")
    return {
        "tackles": _number(tackles.get("total")),
        "interceptions": _number(tackles.get("interceptions")),
        "blocks": _number(tackles.get("blocks")),
        "duels_total": _number(duels.get("total")),
        "duels_won": _number(duels.get("won")),
        "fouls": _number(fouls.get("committed")),
        "fouled": _number(fouls.get("drawn")),
        "cards_yellow": _number(cards.get("yellow")),
        "cards_yellow_red": _number(cards.get("yellowred")),
        "cards_red": _number(cards.get("red")),
    }


def _dribbling(stats: dict[str, Any]) -> dict[str, Any]:
    dribbles = _section(stats, "dribbles")
    attempts = _number(dribbles.get("attempts"))
    success = _number(dribbles.get("success"))
    return {
        "take_ons": attempts,
        "take_ons_won": success,
        "take_ons_won_pct": _pct(success, attempts),
        "dribbled_past": _number(dribbles.get("past")),
    }


def _goalkeeping(row: dict[str, Any], stats: dict[str, Any]) -> dict[str, Any]:
    goals = _section(stats, "goals")
    saves = _number(goals.get("saves"))
    conceded = _number(goals.get("conceded"))
    minutes_90s = row["minutes_90s"]
    return {
        "gk_games": row["games"],
        "gk_games_starts": row["games_starts"],
        "gk_minutes": row["minutes"],
        "gk_saves": saves,
        "gk_goals_against": conceded,
        "gk_goals_against_per90": _per90(conceded, minutes_90s),
        "gk_save_pct": _pct(saves, _add(saves, conceded)),
        "gk_pens_saved": _number(_section(stats, "penalty").get("saved")),
    }


def map_statistics(
    player: dict[str, Any], stats: dict[str, Any], context: SeasonContext
) -> dict[str, Any]:
    """Gera a linha de um jogador em um time, no formato dos CSVs do projeto."""
    games = _section(stats, "games")
    position = POSITION_CODES.get(str(games.get("position")), "")
    playing_time = _playing_time(stats)
    attack = _attack(stats, playing_time["minutes_90s"])
    row = {
        **_identity(player, stats, position),
        **playing_time,
        **attack,
        **_penalties(stats, attack["goals"]),
        **_passing(stats),
        **_defending(stats),
        **_dribbling(stats),
        "data_source": DATA_SOURCE,
        "is_partial": context.is_partial,
        "collected_at": context.collected_at,
    }
    return {**row, **_goalkeeping(row, stats)} if position == "GK" else row


def _keep_most_minutes(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mantém uma linha por jogador e time, preferindo a de mais minutos."""
    best: dict[tuple[Any, Any], dict[str, Any]] = {}
    for row in rows:
        key = (row["player_id"], row["team_id"])
        current = best.get(key)
        if current is None or (row["minutes"] or 0) > (current["minutes"] or 0):
            best[key] = row
    return list(best.values())


def map_players(
    items: Iterable[dict[str, Any]], context: SeasonContext
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Separa as respostas de /players em (jogadores de linha, goleiros).

    Só entram estatísticas da liga pedida e de quem jogou. Um jogador transferido
    dentro da liga gera uma linha por time.
    """
    rows = [
        map_statistics(item.get("player") or {}, stats, context)
        for item in items
        for stats in item.get("statistics") or []
        if _section(stats, "league").get("id") == context.league_id
        and (_number(_section(stats, "games").get("minutes")) or 0) > 0
    ]
    unique_rows = _keep_most_minutes(rows)
    outfield = [row for row in unique_rows if row["Pos"] != "GK"]
    keepers = [row for row in unique_rows if row["Pos"] == "GK"]
    return outfield, keepers
