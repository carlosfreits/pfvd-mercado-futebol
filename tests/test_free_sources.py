"""Coleta gratuita por partida (formato real de /fixtures/players) e dataset aberto."""

from datetime import date

import daily
import import_dataset as tm
import numpy as np
import pandas as pd
import pytest
from client import QuotaExhaustedError
from fixture_mapping import FixtureContext, aggregate_appearances, fixture_appearances
from src.prepare import parse_value

TODAY = date(2026, 11, 9)
LEAGUES = {71: {"id": "Brasileirao_A", "format": "calendar"}, 39: {"id": "Premier_League", "format": "split"}}


def player(player_id, position="M", minutes=90, goals=0, accuracy="24", saves=None, conceded=None, rating="7.0"):
    return {
        "player": {"id": player_id, "name": f"P{player_id}"},
        "statistics": [
            {
                "games": {"minutes": minutes, "position": position, "rating": rating, "substitute": False},
                "offsides": None,
                "shots": {"total": 2, "on": 1},
                "goals": {"total": goals, "conceded": conceded, "assists": None, "saves": saves},
                "passes": {"total": 32, "key": 1, "accuracy": accuracy},
                "tackles": {"total": None, "blocks": 0, "interceptions": 1},
                "duels": {"total": 4, "won": 2},
                "dribbles": {"attempts": 4, "success": 1, "past": None},
                "fouls": {"drawn": 1, "committed": 1},
                "cards": {"yellow": 0, "red": 0},
                "penalty": {"won": None, "commited": None, "scored": 0, "missed": None, "saved": None},
            }
        ],
    }


def team(team_id, players):
    return {"team": {"id": team_id, "name": f"Time {team_id}"}, "players": players}


def context(fixture_id=1, day="2026-11-08", goals=None):
    return FixtureContext(fixture_id, day, goals or {1: 2, 2: 1})


def test_passes_accuracy_is_treated_as_completed_passes():
    outfield, _ = aggregate_appearances(fixture_appearances([team(1, [player(10)])], context()), "x")

    assert outfield[0]["passes_completed"] == 24
    assert outfield[0]["passes_pct"] == 75.0


def test_players_who_did_not_play_are_ignored():
    rows = fixture_appearances([team(1, [player(10, minutes=None), player(11, minutes=0)])], context())

    assert rows == []


def test_sums_fixtures_keeps_nulls_missing_and_counts_games():
    first = fixture_appearances([team(1, [player(10, goals=1, rating="6.0")])], context(1, "2026-11-08"))
    second = fixture_appearances([team(1, [player(10, goals=None, rating="8.0")])], context(2, "2026-11-09"))

    outfield, keepers = aggregate_appearances(first + second, "2026-11-09")

    row = outfield[0]
    assert keepers == []
    assert row["games"] == 2
    assert row["minutes"] == 180
    assert row["minutes_90s"] == 2
    assert row["goals"] == 1
    assert row["goals_per90"] == 0.5
    assert row["tackles"] is None
    assert row["assists"] is None
    assert row["api_rating"] == 7.0
    assert (row["first_match"], row["last_match"]) == ("2026-11-08", "2026-11-09")
    assert row["data_source"] == "api_football"
    assert row["is_partial"] is True
    assert row["player_id"] == "af_10"
    assert "games_starts" not in row


def test_same_fixture_is_not_counted_twice():
    rows = fixture_appearances([team(1, [player(10)])], context())

    outfield, _ = aggregate_appearances(rows + rows, "x")

    assert outfield[0]["minutes"] == 90
    assert outfield[0]["games"] == 1


def test_transfer_generates_one_row_per_team_in_aggregate():
    first = fixture_appearances([team(1, [player(10)])], context(1))
    second = fixture_appearances([team(2, [player(10)])], context(2))

    outfield, _ = aggregate_appearances(first + second, "x")

    assert sorted(row["Squad"] for row in outfield) == ["Time 1", "Time 2"]


def test_goalkeeper_uses_scoreline_when_conceded_is_null_and_main_keeper_only():
    keepers_team = team(1, [player(90, "G", 80, saves=3), player(91, "G", 10, saves=0)])

    _, keepers = aggregate_appearances(fixture_appearances([keepers_team], context(goals={1: 2, 2: 1})), "x")

    by_id = {row["player_id"]: row for row in keepers}
    assert by_id["af_90"]["gk_goals_against"] == 1
    assert by_id["af_90"]["gk_save_pct"] == 75
    assert by_id["af_90"]["gk_minutes"] == 80
    assert by_id["af_91"]["gk_goals_against"] is None


def test_null_position_uses_position_from_other_games():
    first = fixture_appearances([team(1, [player(10, position=None)])], context(1))
    second = fixture_appearances([team(1, [player(10, position="D", minutes=10)])], context(2))

    outfield, _ = aggregate_appearances(first + second, "x")

    assert outfield[0]["Pos"] == "DF"


def test_player_without_any_position_stays_blank_as_outfield():
    rows = fixture_appearances([team(1, [player(10, position=None)])], context())

    outfield, keepers = aggregate_appearances(rows, "x")

    assert keepers == []
    assert outfield[0]["Pos"] == ""


def test_goalkeeper_prefers_conceded_when_api_sends_it():
    keepers_team = team(1, [player(90, "G", saves=3, conceded=3)])

    _, keepers = aggregate_appearances(fixture_appearances([keepers_team], context(goals={1: 0, 2: 9})), "x")

    assert keepers[0]["gk_goals_against"] == 3


def test_season_labels_follow_league_format():
    assert daily.season_label(LEAGUES[71], 2026) == "2026"
    assert daily.season_label(LEAGUES[39], 2026) == "2026-2027"


def test_window_only_uses_days_already_started():
    assert daily.window_dates(TODAY) == ["2026-11-08", "2026-11-09"]


def api_fixture(fixture_id, league_id=71, status="FT"):
    return {
        "fixture": {"id": fixture_id, "date": "2026-11-08T20:00:00+00:00", "status": {"short": status}},
        "league": {"id": league_id, "season": 2026},
        "teams": {"home": {"id": 1}, "away": {"id": 2}},
        "goals": {"home": 2, "away": 1},
    }


class FakeClient:
    def __init__(self, fixtures, players=None, quota_after=None):
        self.fixtures = fixtures
        self.players = players if players is not None else [team(1, [player(10), player(90, "G", saves=2)])]
        self.quota_after = quota_after
        self.requests_made = 0
        self.player_requests = []

    def get(self, endpoint, params=None):
        if self.quota_after is not None and self.requests_made >= self.quota_after:
            raise QuotaExhaustedError("Cota esgotada")
        self.requests_made += 1
        if endpoint == "fixtures":
            return {"response": self.fixtures if params["date"] == "2026-11-08" else []}
        self.player_requests.append(params["fixture"])
        return {"response": self.players}


def test_collects_only_finished_games_of_project_leagues(tmp_path):
    client = FakeClient([api_fixture(1), api_fixture(2, status="NS"), api_fixture(3, league_id=999)])

    summary = daily.collect_window(client, ["2026-11-08", "2026-11-09"], LEAGUES, tmp_path, 90)

    assert summary["downloaded"] == 1
    assert client.player_requests == [1]
    assert (tmp_path / "Brasileirao_A_2026" / "1.json").exists()


def test_cached_fixture_spends_no_request_on_new_run(tmp_path):
    daily.collect_window(FakeClient([api_fixture(1)]), ["2026-11-08"], LEAGUES, tmp_path, 90)

    client = FakeClient([api_fixture(1)])
    summary = daily.collect_window(client, ["2026-11-08"], LEAGUES, tmp_path, 90)

    assert client.player_requests == []
    assert summary["already_cached"] == 1


def test_fixture_without_stats_is_retried_later(tmp_path):
    summary = daily.collect_window(FakeClient([api_fixture(1)], players=[]), ["2026-11-08"], LEAGUES, tmp_path, 90)

    assert summary["without_stats"] == 1
    assert not (tmp_path / "Brasileirao_A_2026" / "1.json").exists()


def test_request_limit_leaves_games_pending(tmp_path):
    client = FakeClient([api_fixture(1), api_fixture(2), api_fixture(3)])

    summary = daily.collect_window(client, ["2026-11-08"], LEAGUES, tmp_path, max_requests=2)

    assert client.requests_made == 2
    assert summary["downloaded"] == 1
    assert summary["pending"] == 2


def test_quota_error_keeps_games_already_downloaded(tmp_path):
    client = FakeClient([api_fixture(1), api_fixture(2)], quota_after=2)

    with pytest.raises(QuotaExhaustedError):
        daily.collect_window(client, ["2026-11-08"], LEAGUES, tmp_path, 90)

    assert (tmp_path / "Brasileirao_A_2026" / "1.json").exists()
    results = daily.rebuild_csvs(tmp_path, tmp_path / "out", TODAY)
    assert results["Brasileirao_A_2026"][0] == 1


def test_rebuild_accumulates_all_saved_games(tmp_path):
    daily.collect_window(FakeClient([api_fixture(1), api_fixture(2)]), ["2026-11-08"], LEAGUES, tmp_path, 90)

    results = daily.rebuild_csvs(tmp_path, tmp_path / "out", TODAY)

    outfield = pd.read_csv(tmp_path / "out" / "Brasileirao_A_2026" / "jogadores.csv")
    keepers = pd.read_csv(tmp_path / "out" / "Brasileirao_A_2026" / "goleiros.csv")
    assert results["Brasileirao_A_2026"] == (2, 1, 1)
    assert outfield["minutes"].tolist() == [180]
    assert keepers["gk_saves"].tolist() == [4]


def test_real_config_has_api_id_for_every_league():
    config = daily.load_config()

    assert len(daily.league_index(config)) == 12


def tm_tables():
    appearances = pd.DataFrame(
        {
            "game_id": [1, 2, 1, 1, 3],
            "player_id": [10, 10, 20, 30, 10],
            "player_club_id": [100, 100, 200, 100, 100],
            "goals": [1, 2, 0, 0, 9],
            "assists": [0, 1, 0, 0, 9],
            "yellow_cards": [1, 0, 0, 0, 0],
            "red_cards": [0, 0, 0, 0, 0],
            "minutes_played": [90, 45, 90, 0, 90],
        }
    )
    games = pd.DataFrame(
        {"game_id": [1, 2, 3], "competition_id": ["GB1", "GB1", "ES1"], "season": [2025, 2025, 2025]}
    )
    players = pd.DataFrame(
        {
            "player_id": [10, 20, 30],
            "name": ["Atacante", "Goleiro", "Sem minutos"],
            "position": ["Attack", "Goalkeeper", "Defender"],
            "sub_position": ["Left Winger", "Goalkeeper", "Centre-Back"],
            "date_of_birth": ["2000-01-15", "1990-05-01", "1999-01-01"],
            "height_in_cm": [180.0, np.nan, 190.0],
            "country_of_citizenship": ["Brazil", "Spain", "Italy"],
            "market_value_in_eur": [1_500_000.0, 900_000.0, np.nan],
        }
    )
    clubs = pd.DataFrame({"club_id": [100, 200], "name": ["Clube A", "Clube B"]})
    return appearances, games, players, clubs


def tm_rows():
    appearances, games, players, clubs = tm_tables()
    totals = tm.season_appearances(appearances, games, "GB1")
    return tm.build_rows(totals, players, clubs, TODAY)


def test_dataset_sums_only_league_season_and_players_with_minutes():
    rows = tm_rows().set_index("Player")

    assert sorted(rows.index) == ["Atacante", "Goleiro"]
    assert rows.loc["Atacante", "goals"] == 3
    assert rows.loc["Atacante", "minutes"] == 135
    assert rows.loc["Atacante", "games"] == 2
    assert rows.loc["Atacante", "goals_per90"] == 2


def test_dataset_maps_positions_identity_and_market_value():
    rows = tm_rows().set_index("Player")

    assert rows.loc["Atacante", "position"] == "FW (WM)"
    assert rows.loc["Atacante", "Pos"] == "FW"
    assert rows.loc["Goleiro", "Pos"] == "GK"
    assert rows.loc["Atacante", "Age"] == 26
    assert rows.loc["Atacante", "height"] == "180cm"
    assert rows.loc["Atacante", "player_id"] == "tm_10"
    assert rows.loc["Atacante", "market_value"] == "€1.50m"
    assert rows.loc["Goleiro", "market_value"] == "€900k"
    assert not rows["is_partial"].any()


def test_keeper_rows_have_columns_used_by_rating():
    keepers = tm.keeper_rows(tm_rows())

    assert keepers["Player"].tolist() == ["Goleiro"]
    assert keepers["gk_minutes"].tolist() == [90]


def test_market_value_format_is_read_by_the_project_parser():
    assert parse_value(tm.format_market_value(1_500_000)) == 1.5
    assert parse_value(tm.format_market_value(900_000)) == 0.9
    assert tm.format_market_value(float("nan")) is None


@pytest.fixture
def isolated_daily(tmp_path, monkeypatch):
    monkeypatch.setattr(daily, "DATA_DIR", tmp_path)
    monkeypatch.setattr(daily, "load_dotenv", lambda *_: None)
    monkeypatch.setenv("API_FOOTBALL_KEY", "")
    return tmp_path


def test_refuses_to_collect_without_history(isolated_daily, caplog):
    status = daily.main([])

    assert status == 2
    assert "Drive" in caplog.text


def test_first_run_flag_skips_the_history_check(isolated_daily, caplog):
    status = daily.main(["--first-run"])

    assert status == 2
    assert "Defina API_FOOTBALL_KEY" in caplog.text
    assert "Drive" not in caplog.text


def test_saved_fixture_passes_the_history_check(isolated_daily, caplog):
    folder = isolated_daily / "raw" / "fixtures" / "MLS_2026"
    folder.mkdir(parents=True)
    (folder / "1.json").write_text(
        '{"fixture_id": 1, "date": "2026-11-08", "goals_by_team": {}, "players": []}', encoding="utf-8"
    )

    status = daily.main([])

    assert status == 2
    assert "Defina API_FOOTBALL_KEY" in caplog.text
