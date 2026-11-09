"""Mapeamento do JSON de /players (formato sintético, baseado na documentação da API)."""

from mapping import SeasonContext, map_players

LEAGUE_ID = 71
CONTEXT = SeasonContext(league_id=LEAGUE_ID, is_partial=True, collected_at="2026-11-09")


def make_statistics(**overrides):
    stats = {
        "team": {"id": 1, "name": "Time A"},
        "league": {"id": LEAGUE_ID, "season": 2026},
        "games": {
            "appearences": 10,
            "lineups": 9,
            "minutes": 900,
            "position": "Attacker",
            "rating": "7.25",
        },
        "substitutes": {"in": 1, "out": 2, "bench": 3},
        "shots": {"total": 20, "on": 10},
        "goals": {"total": 5, "conceded": 0, "assists": 2, "saves": None},
        "passes": {"total": 200, "key": 15, "accuracy": 30},
        "tackles": {"total": None, "blocks": 1, "interceptions": 3},
        "duels": {"total": 50, "won": 25},
        "dribbles": {"attempts": 10, "success": 4, "past": None},
        "fouls": {"drawn": 8, "committed": 6},
        "cards": {"yellow": 2, "yellowred": 0, "red": 0},
        "penalty": {"won": 1, "commited": 0, "scored": 1, "missed": 1, "saved": None},
    }
    return {**stats, **overrides}


def make_item(player_id=10, statistics=None):
    return {
        "player": {
            "id": player_id,
            "name": "F. Silva",
            "firstname": "Fulano",
            "lastname": "Silva",
            "age": 25,
            "birth": {"date": "2001-03-04"},
            "nationality": "Brazil",
            "height": "180 cm",
            "weight": "75 kg",
        },
        "statistics": statistics if statistics is not None else [make_statistics()],
    }


def test_maps_outfield_player_to_project_columns():
    outfield, keepers = map_players([make_item()], CONTEXT)

    row = outfield[0]
    assert keepers == []
    assert row["Player"] == "F. Silva"
    assert row["Pos"] == "FW"
    assert row["Squad"] == "Time A"
    assert row["Born"] == "2001"
    assert row["height"] == "180cm"
    assert row["player_id"] == "af_10"
    assert row["games"] == 10
    assert row["minutes"] == 900
    assert row["minutes_90s"] == 10
    assert row["goals_assists"] == 7
    assert row["goals_per90"] == 0.5
    assert row["goals_pens"] == 4
    assert row["pens_att"] == 2
    assert row["pens_conceded"] == 0
    assert row["assisted_shots"] == 15
    assert row["take_ons_won_pct"] == 40
    assert row["shots_on_target_pct"] == 50
    assert row["data_source"] == "api_football"
    assert row["is_partial"] is True


def test_null_metric_stays_missing_instead_of_zero():
    outfield, _ = map_players([make_item()], CONTEXT)

    assert outfield[0]["tackles"] is None
    assert outfield[0]["dribbled_past"] is None


def test_metrics_absent_from_source_are_not_invented():
    outfield, _ = map_players([make_item()], CONTEXT)

    for column in ("xg", "sca", "progressive_passes", "aerials_won", "passes_pct"):
        assert column not in outfield[0]


def test_goalkeeper_goes_to_keepers_with_gk_columns():
    games = {"appearences": 10, "lineups": 10, "minutes": 900, "position": "Goalkeeper"}
    goals = {"total": 0, "conceded": 10, "assists": 0, "saves": 30}
    item = make_item(statistics=[make_statistics(games=games, goals=goals)])

    outfield, keepers = map_players([item], CONTEXT)

    assert outfield == []
    assert keepers[0]["Pos"] == "GK"
    assert keepers[0]["gk_minutes"] == 900
    assert keepers[0]["gk_saves"] == 30
    assert keepers[0]["gk_goals_against"] == 10
    assert keepers[0]["gk_save_pct"] == 75
    assert keepers[0]["gk_goals_against_per90"] == 1


def test_transfer_inside_league_creates_one_row_per_team():
    other_team = make_statistics(team={"id": 2, "name": "Time B"})

    outfield, _ = map_players([make_item(statistics=[make_statistics(), other_team])], CONTEXT)

    assert sorted(row["Squad"] for row in outfield) == ["Time A", "Time B"]


def test_ignores_other_competitions_and_players_without_minutes():
    cup = make_statistics(league={"id": 999, "season": 2026})
    no_minutes = make_statistics(games={"appearences": 0, "minutes": None, "position": "Defender"})

    outfield, keepers = map_players(
        [make_item(statistics=[cup]), make_item(player_id=11, statistics=[no_minutes])], CONTEXT
    )

    assert outfield == []
    assert keepers == []


def test_duplicate_player_and_team_keeps_row_with_most_minutes():
    fewer = make_statistics(games={"appearences": 1, "minutes": 90, "position": "Attacker"})

    outfield, _ = map_players([make_item(statistics=[fewer, make_statistics()])], CONTEXT)

    assert len(outfield) == 1
    assert outfield[0]["minutes"] == 900


def test_zero_minutes_rate_does_not_divide_by_zero_and_text_numbers_convert():
    item = make_item(statistics=[make_statistics(shots={"total": "abc", "on": "3"})])

    outfield, _ = map_players([item], CONTEXT)

    assert outfield[0]["shots"] is None
    assert outfield[0]["shots_on_target"] == 3
    assert outfield[0]["shots_on_target_pct"] is None
