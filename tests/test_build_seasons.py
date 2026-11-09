"""Base única de temporadas e o gráfico de exemplo; usa o dataset aberto versionado."""

from pathlib import Path

import pandas as pd
import pytest

from src.build_seasons import (
    API_SOURCE,
    FBREF_SOURCE,
    OPEN_SOURCE,
    _read_source,
    build_seasons,
    load_fbref_history,
    load_open_dataset,
)
from src.charts import market_value_by_league_chart


def empty_dir(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.mkdir()
    return path


def write_api_season(base: Path, folder: str = "MLS_2026") -> None:
    target = base / "player_data" / folder
    target.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "Player": "A",
                "Squad": "Time",
                "Pos": "FW",
                "player_id": "af_1",
                "Age": None,
                "minutes": 90,
                "games": 1,
                "goals": 1,
                "assists": None,
                "is_partial": True,
            }
        ]
    ).to_csv(target / "jogadores.csv", index=False)


def test_real_open_dataset_matches_external_top_scorers() -> None:
    players = load_open_dataset().set_index("Player")

    assert players.loc["Erling Haaland", "goals"] == 27
    assert players.loc["Harry Kane", "goals"] == 36
    assert players.loc["Kylian Mbappé", "goals"] == 25


def test_real_open_dataset_has_values_and_complete_season_flag() -> None:
    players = load_open_dataset()

    assert players["value_eur_m"].notna().mean() > 0.9
    assert not players["is_partial"].any()
    assert set(players["data_source"]) == {OPEN_SOURCE}
    assert players["league"].nunique() == 7


def test_open_dataset_merge_does_not_create_rows() -> None:
    players = load_open_dataset()

    assert not players.duplicated(["league", "season", "player_id", "Squad"]).any()


def test_api_season_keeps_partial_flag_and_missing_values_empty(tmp_path: Path) -> None:
    write_api_season(tmp_path)

    row = _read_source(tmp_path, API_SOURCE).iloc[0]

    assert (row["league"], row["season"]) == ("MLS", "2026")
    assert row["is_partial"]
    assert row["goals"] == 1
    assert pd.isna(row["assists"])
    assert pd.isna(row["Age"])
    assert pd.isna(row["value_eur_m"])


def test_build_works_with_only_the_open_dataset(tmp_path: Path) -> None:
    seasons = build_seasons(api_dir=empty_dir(tmp_path, "api"), raw_dir=empty_dir(tmp_path, "raw"))

    assert set(seasons["data_source"]) == {OPEN_SOURCE}
    assert len(seasons) == len(load_open_dataset())
    assert not seasons.duplicated(["league", "season", "player_id", "Squad"]).any()


def test_build_adds_api_data_when_available(tmp_path: Path) -> None:
    api = empty_dir(tmp_path, "api")
    write_api_season(api)

    seasons = build_seasons(api_dir=api, raw_dir=empty_dir(tmp_path, "raw"))

    assert set(seasons["data_source"]) == {OPEN_SOURCE, API_SOURCE}


def write_fbref_files(folder: Path) -> None:
    identity = {"Player": "G", "Squad": "Time", "Pos": "GK", "Age": "30-100", "league": "MLS", "season": 2025}
    pd.DataFrame([{**identity, "minutes": "1,080", "games": 12, "goals": 0}]).to_csv(
        folder / "2025_outfield.csv", index=False
    )
    pd.DataFrame([{**identity, "gk_minutes": "1,080", "gk_games": 12}]).to_csv(
        folder / "2025_keepers.csv", index=False
    )


def test_history_parses_fbref_formats_and_marks_midseason_files(tmp_path: Path) -> None:
    write_fbref_files(tmp_path)

    history = load_fbref_history(tmp_path)

    assert set(history["data_source"]) == {FBREF_SOURCE}
    assert history["minutes"].tolist() == [1080, 1080]
    assert history["Age"].tolist() == [30, 30]
    assert history["is_partial"].all()


def test_same_player_in_two_fbref_files_counts_once(tmp_path: Path) -> None:
    history = empty_dir(tmp_path, "history")
    write_fbref_files(history)

    seasons = build_seasons(
        api_dir=empty_dir(tmp_path, "api"), raw_dir=empty_dir(tmp_path, "raw"), fbref_dir=history
    )

    assert len(seasons[seasons["data_source"] == FBREF_SOURCE]) == 1


def test_missing_history_folder_fails_clearly(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="FBref"):
        load_fbref_history(tmp_path)


def chart_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "league": ["Liga_A", "Liga_A", "Liga_A", "Liga_B"],
            "season": ["2025-2026"] * 4,
            "player_id": ["1", "1", "2", "3"],
            "minutes": [100, 900, 500, 900],
            "value_eur_m": [10.0, 10.0, 5.0, 20.0],
        }
    )


def test_chart_counts_a_transferred_player_once() -> None:
    figure = market_value_by_league_chart(chart_rows(), "2025-2026")

    totals = dict(zip(figure.data[0].y, figure.data[0].x, strict=True))
    assert totals == {"Liga A": 15.0, "Liga B": 20.0}


def test_chart_title_states_the_largest_league() -> None:
    figure = market_value_by_league_chart(chart_rows(), "2025-2026")

    assert "Liga B" in figure.layout.meta["headline"]


def test_chart_refuses_season_without_market_values() -> None:
    with pytest.raises(ValueError, match="valor de mercado"):
        market_value_by_league_chart(chart_rows().assign(value_eur_m=None), "2025-2026")
