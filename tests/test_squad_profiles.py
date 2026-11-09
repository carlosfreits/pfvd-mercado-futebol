"""Elencos da API-Football: idade e posição dos jogadores, sem gastar cota à toa."""

import json

import daily
from fixture_mapping import FixtureContext, aggregate_appearances, fixture_appearances

SQUAD = {"team": {"id": 1}, "players": [{"id": 10, "name": "P10", "age": 27, "position": "Defender"}]}


class SquadClient:
    def __init__(self, response=None):
        self.response = [SQUAD] if response is None else response
        self.requests_made = 0
        self.teams = []

    def get(self, endpoint, params):
        assert endpoint == "players/squads"
        self.requests_made += 1
        self.teams.append(params["team"])
        return {"response": self.response}


def save_fixture(raw_dir, team_ids):
    folder = raw_dir / "MLS_2026"
    folder.mkdir(parents=True)
    players = [{"team": {"id": team_id, "name": str(team_id)}, "players": []} for team_id in team_ids]
    (folder / "1.json").write_text(json.dumps({"players": players}), encoding="utf-8")


def appearance(position="D"):
    stats = {
        "games": {"minutes": 90, "position": position, "rating": "7.0"},
        "goals": {},
        "passes": {},
    }
    entry = {"team": {"id": 1, "name": "A"}, "players": [{"player": {"id": 10, "name": "P10"}, "statistics": [stats]}]}
    return fixture_appearances([entry], FixtureContext(1, "2026-11-08", {1: 0, 2: 0}))


def test_downloads_each_team_once(tmp_path):
    raw_dir, squads_dir = tmp_path / "fixtures", tmp_path / "squads"
    squads_dir.mkdir()
    save_fixture(raw_dir, [1, 2])

    first = SquadClient()
    daily.collect_squads(first, raw_dir, squads_dir, 90)
    second = SquadClient()
    daily.collect_squads(second, raw_dir, squads_dir, 90)

    assert first.teams == [1, 2]
    assert second.teams == []


def test_request_limit_leaves_squads_pending(tmp_path):
    raw_dir, squads_dir = tmp_path / "fixtures", tmp_path / "squads"
    squads_dir.mkdir()
    save_fixture(raw_dir, [1, 2, 3])
    client = SquadClient()

    summary = daily.collect_squads(client, raw_dir, squads_dir, 2)

    assert summary == {"downloaded": 2, "pending": 1}


def test_empty_squad_is_retried_later(tmp_path):
    raw_dir, squads_dir = tmp_path / "fixtures", tmp_path / "squads"
    squads_dir.mkdir()
    save_fixture(raw_dir, [1])

    daily.collect_squads(SquadClient(response=[]), raw_dir, squads_dir, 90)

    assert not (squads_dir / "1.json").exists()


def test_profile_fills_age_and_only_a_missing_position(tmp_path):
    (tmp_path / "1.json").write_text(json.dumps(SQUAD), encoding="utf-8")
    profiles = daily.load_profiles(tmp_path)

    blank, _ = aggregate_appearances(appearance(position=None), "x", profiles)
    known, _ = aggregate_appearances(appearance(position="M"), "x", profiles)

    assert blank[0]["Age"] == 27
    assert blank[0]["Pos"] == "DF"
    assert known[0]["Pos"] == "MF"


def test_player_outside_squads_keeps_age_empty():
    outfield, _ = aggregate_appearances(appearance(), "x", {})

    assert outfield[0]["Age"] is None
