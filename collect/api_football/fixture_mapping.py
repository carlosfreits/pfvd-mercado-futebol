"""Soma as estatísticas de /fixtures/players em uma linha por jogador e time.

Particularidades observadas nas respostas reais do endpoint:
- `passes.accuracy` é a quantidade de passes certos, não um percentual;
- `games.substitute` não distingue reservas, então titularidades não são calculadas;
- `goals.conceded` pode vir nulo para goleiros, então o placar serve de alternativa.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from mapping import (
    DATA_SOURCE,
    PLAYER_ID_PREFIX,
    POSITION_CODES,
    _add,
    _number,
    _pct,
    _per90,
    _subtract,
)

POSITION_LETTERS = {
    "G": POSITION_CODES["Goalkeeper"],
    "D": POSITION_CODES["Defender"],
    "M": POSITION_CODES["Midfielder"],
    "F": POSITION_CODES["Attacker"],
}
SUMMED_FIELDS = {
    "minutes": ("games", "minutes"),
    "goals": ("goals", "total"),
    "assists": ("goals", "assists"),
    "shots": ("shots", "total"),
    "shots_on_target": ("shots", "on"),
    "passes": ("passes", "total"),
    "passes_completed": ("passes", "accuracy"),
    "assisted_shots": ("passes", "key"),
    "tackles": ("tackles", "total"),
    "interceptions": ("tackles", "interceptions"),
    "blocks": ("tackles", "blocks"),
    "duels_total": ("duels", "total"),
    "duels_won": ("duels", "won"),
    "take_ons": ("dribbles", "attempts"),
    "take_ons_won": ("dribbles", "success"),
    "dribbled_past": ("dribbles", "past"),
    "fouls": ("fouls", "committed"),
    "fouled": ("fouls", "drawn"),
    "cards_yellow": ("cards", "yellow"),
    "cards_red": ("cards", "red"),
    "pens_made": ("penalty", "scored"),
    "pens_missed": ("penalty", "missed"),
    "pens_won": ("penalty", "won"),
    "pens_conceded": ("penalty", "commited"),
    "offsides": ("offsides", None),
    "gk_saves": ("goals", "saves"),
    "gk_pens_saved": ("penalty", "saved"),
}


@dataclass(frozen=True)
class FixtureContext:
    """Dados da partida necessários para interpretar as estatísticas dos jogadores."""

    fixture_id: int
    date: str
    goals_by_team: dict[int, int]


def _field(stats: dict[str, Any], section: str, name: str | None) -> float | None:
    value = stats.get(section)
    if name is None:
        return _number(value)
    return _number((value or {}).get(name))


def _opponent_goals(team_id: int, context: FixtureContext) -> float | None:
    others = [goals for team, goals in context.goals_by_team.items() if team != team_id]
    return float(others[0]) if len(others) == 1 and others[0] is not None else None


def _team_appearances(team_entry: dict[str, Any], context: FixtureContext) -> list[dict[str, Any]]:
    team = team_entry.get("team") or {}
    rows = []
    for item in team_entry.get("players") or []:
        stats = (item.get("statistics") or [{}])[0]
        games = stats.get("games") or {}
        minutes = _number(games.get("minutes"))
        if not minutes:
            continue
        player = item.get("player") or {}
        values = {
            column: _field(stats, section, name)
            for column, (section, name) in SUMMED_FIELDS.items()
        }
        rows.append(
            {
                **values,
                "player_id": f"{PLAYER_ID_PREFIX}{player.get('id')}",
                "Player": player.get("name"),
                "Squad": team.get("name"),
                "team_id": team.get("id"),
                "Pos": POSITION_LETTERS.get(str(games.get("position")), ""),
                "rating_value": _number(games.get("rating")),
                "gk_conceded": _number((stats.get("goals") or {}).get("conceded")),
                "fixture_id": context.fixture_id,
                "date": context.date,
            }
        )
    return rows


def _assign_goals_against(rows: list[dict[str, Any]], team_id: int, context: FixtureContext) -> None:
    """Sem `conceded`, credita o placar ao goleiro com mais minutos na partida."""
    keepers = [row for row in rows if row["Pos"] == "GK"]
    if not keepers:
        return
    main_keeper = max(keepers, key=lambda row: row["minutes"])
    for keeper in keepers:
        if keeper["gk_conceded"] is None and keeper is main_keeper:
            keeper["gk_conceded"] = _opponent_goals(team_id, context)


def fixture_appearances(players: Iterable[dict[str, Any]], context: FixtureContext) -> list[dict[str, Any]]:
    """Converte a resposta de /fixtures/players em uma linha por jogador que atuou."""
    appearances = []
    for team_entry in players:
        rows = _team_appearances(team_entry, context)
        _assign_goals_against(rows, (team_entry.get("team") or {}).get("id"), context)
        appearances.extend(rows)
    return appearances


def _main_position(rows: list[dict[str, Any]]) -> str:
    """A API às vezes envia posição nula: vale a informada nas outras partidas do jogador."""
    minutes_by_position: dict[str, float] = {}
    for row in rows:
        if row["Pos"]:
            minutes_by_position[row["Pos"]] = minutes_by_position.get(row["Pos"], 0) + row["minutes"]
    return max(minutes_by_position, key=minutes_by_position.get, default="")


def _sum_column(rows: list[dict[str, Any]], column: str) -> float | None:
    return _add(*(row[column] for row in rows))


def _derived_metrics(totals: dict[str, Any]) -> dict[str, Any]:
    minutes_90s = round(totals["minutes"] / 90, 2)
    goals_assists = _add(totals["goals"], totals["assists"])
    return {
        "minutes_90s": minutes_90s,
        "goals_assists": goals_assists,
        "goals_pens": _subtract(totals["goals"], totals["pens_made"]),
        "pens_att": _add(totals["pens_made"], totals["pens_missed"]),
        "passes_pct": _pct(totals["passes_completed"], totals["passes"]),
        "shots_on_target_pct": _pct(totals["shots_on_target"], totals["shots"]),
        "take_ons_won_pct": _pct(totals["take_ons_won"], totals["take_ons"]),
        "goals_per90": _per90(totals["goals"], minutes_90s),
        "assists_per90": _per90(totals["assists"], minutes_90s),
        "goals_assists_per90": _per90(goals_assists, minutes_90s),
        "shots_per90": _per90(totals["shots"], minutes_90s),
        "shots_on_target_per90": _per90(totals["shots_on_target"], minutes_90s),
    }


def _keeper_metrics(totals: dict[str, Any], rows: list[dict[str, Any]], minutes_90s: float) -> dict[str, Any]:
    conceded = _sum_column(rows, "gk_conceded")
    saves = totals["gk_saves"]
    return {
        "gk_games": len(rows),
        "gk_minutes": totals["minutes"],
        "gk_goals_against": conceded,
        "gk_goals_against_per90": _per90(conceded, minutes_90s),
        "gk_save_pct": _pct(saves, _add(saves, conceded)),
    }


def _season_row(
    rows: list[dict[str, Any]], collected_at: str, profile: dict[str, Any]
) -> dict[str, Any]:
    totals = {column: _sum_column(rows, column) for column in SUMMED_FIELDS}
    ratings = [row["rating_value"] for row in rows if row["rating_value"] is not None]
    position = _main_position(rows) or profile.get("Pos", "")
    derived = _derived_metrics(totals)
    dates = sorted(row["date"] for row in rows)
    latest = max(rows, key=lambda row: row["date"])
    row = {
        "Player": latest["Player"],
        "Nation": None,
        "Pos": position,
        "position": position,
        "Squad": latest["Squad"],
        "team_id": latest["team_id"],
        "Age": profile.get("Age"),
        "Born": None,
        "player_id": latest["player_id"],
        "games": len(rows),
        **{column: value for column, value in totals.items() if not column.startswith("gk_")},
        **derived,
        "api_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
        "first_match": dates[0],
        "last_match": dates[-1],
        "data_source": DATA_SOURCE,
        "is_partial": True,
        "collected_at": collected_at,
    }
    if position != "GK":
        return row
    keeper = _keeper_metrics(totals, rows, derived["minutes_90s"])
    return {**row, **keeper, "gk_saves": totals["gk_saves"], "gk_pens_saved": totals["gk_pens_saved"]}


def aggregate_appearances(
    appearances: Iterable[dict[str, Any]],
    collected_at: str,
    profiles: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Soma as partidas em (jogadores de linha, goleiros), uma linha por jogador e time."""
    grouped: dict[tuple[Any, Any], dict[int, dict[str, Any]]] = {}
    for row in appearances:
        key = (row["player_id"], row["team_id"])
        grouped.setdefault(key, {})[row["fixture_id"]] = row
    known = profiles or {}
    rows = [
        _season_row(list(by_fixture.values()), collected_at, known.get(player_id, {}))
        for (player_id, _), by_fixture in grouped.items()
    ]
    outfield = [row for row in rows if row["Pos"] != "GK"]
    keepers = [row for row in rows if row["Pos"] == "GK"]
    return outfield, keepers
