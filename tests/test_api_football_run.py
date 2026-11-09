"""Resolução de ligas, paginação, retomada pelo cache e gravação dos CSVs."""

from datetime import date

import pandas as pd
import pytest
import run
from client import ApiFootballError, QuotaExhaustedError

TODAY = date(2026, 11, 9)
CONFIG = {
    "split_seasons": ["2025-2026", "2026-2027"],
    "calendar_seasons": ["2026"],
    "leagues": [
        {"id": "Serie_A_TIM", "country": "Italy", "api_names": ["Serie A"], "format": "split"},
        {"id": "Brasileirao_A", "country": "Brazil", "api_names": ["Serie A"], "format": "calendar"},
    ],
}
TARGET = run.SeasonTarget("Brasileirao_A", "2026", 2026, 71, True, None)


def season(year, end, players=True):
    return {"year": year, "end": end, "coverage": {"players": players}}


def league_entry(league_id, name, country, seasons, league_type="League"):
    return {
        "league": {"id": league_id, "name": name, "type": league_type},
        "country": {"name": country},
        "seasons": seasons,
    }


def player_item(player_id, position="Attacker"):
    return {
        "player": {"id": player_id, "name": f"Jogador {player_id}", "birth": {}},
        "statistics": [
            {
                "team": {"id": 1, "name": "Time"},
                "league": {"id": 71},
                "games": {"minutes": 900, "appearences": 10, "position": position},
            }
        ],
    }


class FakeClient:
    """Serve páginas predefinidas e pode falhar em uma delas."""

    def __init__(self, pages, fail_on_page=None, error=None):
        self.pages = pages
        self.fail_on_page = fail_on_page
        self.error = error or QuotaExhaustedError("Cota esgotada")
        self.requested = []

    def get(self, endpoint, params=None):
        page = params["page"]
        if page == self.fail_on_page:
            raise self.error
        self.requested.append(page)
        return {"paging": {"current": page, "total": len(self.pages)}, "response": self.pages[page - 1]}


def two_pages():
    return [[player_item(1), player_item(2, "Goalkeeper")], [player_item(3, "Defender")]]


def test_resolves_same_league_name_by_country_and_detects_partial_season():
    catalog = [
        league_entry(135, "Serie A", "Italy", [season(2025, "2026-05-24"), season(2026, "2027-05-30")]),
        league_entry(71, "Serie A", "Brazil", [season(2026, "2026-12-06")]),
        league_entry(999, "Serie A", "Brazil", [season(2026, "2026-12-06")], league_type="Cup"),
    ]

    targets = run.resolve_targets(CONFIG, catalog, TODAY)

    summary = {(t.league, t.label): (t.league_id, t.api_year, t.is_partial, t.problem) for t in targets}
    assert summary[("Serie_A_TIM", "2025-2026")] == (135, 2025, False, None)
    assert summary[("Serie_A_TIM", "2026-2027")] == (135, 2026, True, None)
    assert summary[("Brasileirao_A", "2026")] == (71, 2026, True, None)


def test_reports_missing_league_season_and_coverage():
    catalog = [
        league_entry(135, "Serie A", "Italy", [season(2025, "2026-05-24", players=False)]),
    ]

    targets = {(t.league, t.label): t for t in run.resolve_targets(CONFIG, catalog, TODAY)}

    assert "sem cobertura" in targets[("Serie_A_TIM", "2025-2026")].problem
    assert "não existe" in targets[("Serie_A_TIM", "2026-2027")].problem
    assert "não identificada" in targets[("Brasileirao_A", "2026")].problem


def test_collects_all_pages_and_splits_csvs(tmp_path):
    client = FakeClient(two_pages())

    counts = run.collect_target(client, TARGET, tmp_path, False, TODAY)

    folder = tmp_path / "player_data" / "Brasileirao_A_2026"
    assert counts == (2, 1)
    assert client.requested == [1, 2]
    assert set(pd.read_csv(folder / "jogadores.csv")["player_id"]) == {"af_1", "af_3"}
    assert list(pd.read_csv(folder / "goleiros.csv")["player_id"]) == ["af_2"]


def test_interrupted_collection_writes_no_csv_and_resumes_without_repeating_requests(tmp_path):
    failing = FakeClient(two_pages(), fail_on_page=2)
    with pytest.raises(QuotaExhaustedError):
        run.collect_target(failing, TARGET, tmp_path, False, TODAY)
    assert not (tmp_path / "player_data").exists()

    resumed = FakeClient(two_pages())
    run.collect_target(resumed, TARGET, tmp_path, False, TODAY)

    assert resumed.requested == [2]
    assert (tmp_path / "player_data" / "Brasileirao_A_2026" / "jogadores.csv").exists()


def test_complete_rerun_spends_no_requests(tmp_path):
    run.collect_target(FakeClient(two_pages()), TARGET, tmp_path, False, TODAY)

    again = FakeClient(two_pages())
    run.collect_target(again, TARGET, tmp_path, False, TODAY)

    assert again.requested == []


def test_refresh_downloads_partial_season_again_but_keeps_finished_one(tmp_path):
    finished = run.SeasonTarget("Serie_A_TIM", "2025-2026", 2025, 71, False, None)
    run.collect_target(FakeClient(two_pages()), TARGET, tmp_path, False, TODAY)
    run.collect_target(FakeClient(two_pages()), finished, tmp_path, False, TODAY)

    partial_client = FakeClient(two_pages())
    finished_client = FakeClient(two_pages())
    run.collect_target(partial_client, TARGET, tmp_path, True, TODAY)
    run.collect_target(finished_client, finished, tmp_path, True, TODAY)

    assert partial_client.requested == [1, 2]
    assert finished_client.requested == []


def test_empty_response_does_not_overwrite_existing_csv(tmp_path):
    run.collect_target(FakeClient(two_pages()), TARGET, tmp_path, False, TODAY)
    csv_file = tmp_path / "player_data" / "Brasileirao_A_2026" / "jogadores.csv"
    before = csv_file.read_bytes()

    with pytest.raises(ApiFootballError):
        run.collect_target(FakeClient([[]]), TARGET, tmp_path, True, TODAY)

    assert csv_file.read_bytes() == before


def test_quota_stops_all_remaining_targets(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "DATA_DIR", tmp_path)
    client = FakeClient(two_pages(), fail_on_page=1)
    second = run.SeasonTarget("Serie_A_TIM", "2025-2026", 2025, 71, False, None)

    status = run.collect_all(client, [TARGET, second], False, TODAY)

    assert status == 2


def test_other_failure_continues_and_returns_error_status(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "DATA_DIR", tmp_path)
    client = FakeClient(two_pages(), fail_on_page=1, error=ApiFootballError("plano"))

    assert run.collect_all(client, [TARGET], False, TODAY) == 1


def test_main_without_key_fails_with_clear_status(monkeypatch):
    monkeypatch.delenv("API_FOOTBALL_KEY", raising=False)
    monkeypatch.setattr(run, "ENV_FILE", run.SCRAPER_DIR / "nao_existe.env")

    assert run.main(["--check"]) == 2


def test_real_config_covers_twelve_leagues_and_twenty_combinations():
    config = run.load_config()

    combinations = [
        (league["id"], label) for league in config["leagues"] for label in run.seasons_for(league, config)
    ]
    assert len(config["leagues"]) == 12
    assert len(combinations) == 20
