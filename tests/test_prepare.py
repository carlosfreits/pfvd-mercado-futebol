"""Testes do pipeline de dados e da nota."""

import math

import pandas as pd
import pytest

from src.prepare import RAW_DIR, build_dataset, match_players, normalize_name, parse_value
from src.rating import (
    MIN_MINUTES,
    POSITION_WEIGHTS,
    PriceModel,
    add_expected_price,
    add_scores,
    listed_positions,
    percentile_profile,
    shortlist,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("€35.00m", 35.0), ("€500k", 0.5), ("€1.50m", 1.5), ("€50k", 0.05)],
)
def test_parse_value_converts_units_to_millions(raw: str, expected: float) -> None:
    assert parse_value(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", ["€300", "€1.50", "", None, float("nan"), "n/d"])
def test_parse_value_rejects_missing_or_unitless_values(raw: object) -> None:
    assert math.isnan(parse_value(raw))


def test_normalize_name_removes_accents_and_punctuation() -> None:
    assert normalize_name("Fábio  O'Shea-Muñoz") == "fabio o shea munoz"


@pytest.mark.parametrize(
    ("general", "detailed", "expected"),
    [
        ("DF", "DF-MF (DM-FB, right)", ["DM", "FB"]),
        ("DF", "DF (FB, left)", ["FB"]),
        ("FW,MF", "FW-MF (AM-WM)", ["AM", "WM"]),
        ("MF", "MF", ["CM"]),
        ("FW", "FW", ["AM"]),
        ("GK", "GK", ["GK"]),
    ],
)
def test_listed_positions_keeps_every_detailed_position(general: str, detailed: str, expected: list[str]) -> None:
    assert listed_positions(general, detailed) == expected


def test_add_scores_creates_one_row_per_listed_position() -> None:
    players = _players(position="DF (CB)")
    players.loc[0, "position"] = "DF (CB-FB)"
    for metric in POSITION_WEIGHTS["FB"]:
        if metric not in players:
            players[metric] = 1.0
    scored = add_scores(players)
    assert sorted(scored.loc[scored["Player"] == "P0", "position_group"]) == ["CB", "FB"]


def _market(rows: list[tuple[int, str, int, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ID": tm_id,
                "Name": name,
                "name_key": normalize_name(name),
                "birth_year": year,
                "value_eur_m": value,
                "tm_club": "Clube",
                "Value last updated": "May 30, 2025",
            }
            for tm_id, name, year, value in rows
        ]
    )


def test_match_requires_same_birth_year() -> None:
    fbref = pd.DataFrame({"Player": ["João Silva"], "Born": [2000.0], "minutes": [1000.0]})
    matched = match_players(fbref, _market([(1, "Joao Silva", 1999, 5.0), (2, "Outro Nome", 2000, 1.0)]))
    assert matched["value_eur_m"].isna().all()


def test_match_gives_value_only_to_longest_stint() -> None:
    fbref = pd.DataFrame(
        {"Player": ["João Silva", "João Silva"], "Born": [2000.0, 2000.0], "minutes": [800.0, 2000.0]}
    )
    matched = match_players(fbref, _market([(1, "Joao Silva", 2000, 5.0)]))
    assert matched["value_eur_m"].notna().tolist() == [False, True]


def _players(count: int = 12, position: str = "DF (CB)") -> pd.DataFrame:
    metrics = {metric: [float(i) for i in range(count)] for metric in POSITION_WEIGHTS["CB"]}
    return pd.DataFrame(
        {
            "Player": [f"P{i}" for i in range(count)],
            "Squad": ["Clube"] * count,
            "Pos": ["DF"] * count,
            "position": [position] * count,
            "minutes": [MIN_MINUTES * 2.0] * count,
            **metrics,
        }
    )


def test_add_scores_filters_minutes_and_keeps_scale() -> None:
    players = _players()
    players.loc[0, "minutes"] = MIN_MINUTES - 1
    scored = add_scores(players)
    assert "P0" not in set(scored["Player"])
    assert scored["score"].between(0, 100).all()


def test_add_scores_does_not_mutate_input() -> None:
    players = _players()
    columns = list(players.columns)
    add_scores(players)
    assert list(players.columns) == columns


def test_score_uses_per_90_rates_not_totals() -> None:
    players = _players()
    doubled = players.assign(
        minutes=players["minutes"] * 2,
        **{m: players[m] * 2 for m in POSITION_WEIGHTS["CB"] if m != "aerials_won_pct"},
        aerials_won_pct=players["aerials_won_pct"],
    )
    pd.testing.assert_series_equal(add_scores(players)["score"], add_scores(doubled)["score"])


def _price_model(error_factor: float = 2.0) -> PriceModel:
    return PriceModel(
        score_coef=0.0,
        age_coef=0.0,
        age_squared_coef=0.0,
        position_intercepts={"FB": 1.0},
        r_squared=0.5,
        r_squared_age_only=0.4,
        typical_error_factor=error_factor,
        n_rows=2,
    )


def test_undervalued_only_when_discount_exceeds_model_error() -> None:
    players = pd.DataFrame(
        {"score": [60.0, 60.0], "Age": [25.0, 25.0], "position_group": ["FB", "FB"], "value_eur_m": [4.0, 6.0]}
    )
    result = add_expected_price(players, _price_model(error_factor=2.0))
    assert result["expected_value_eur_m"].tolist() == [10.0, 10.0]
    assert result["undervalued"].tolist() == [True, False]


def test_shortlist_applies_every_decision_rule() -> None:
    base = {"position_group": "FB", "minutes": 1000.0, "in_market": True, "undervalued": True}
    players = pd.DataFrame(
        [
            {**base, "Player": "Titular", "Squad": "Caso", "score": 40.0, "value_eur_m": 5.0},
            {**base, "Player": "Indicado", "Squad": "X", "score": 60.0, "value_eur_m": 10.0},
            {**base, "Player": "Caro", "Squad": "X", "score": 70.0, "value_eur_m": 50.0},
            {**base, "Player": "Pior", "Squad": "X", "score": 30.0, "value_eur_m": 5.0},
            {**base, "Player": "PrecoJusto", "Squad": "X", "score": 60.0, "value_eur_m": 5.0, "undervalued": False},
            {**base, "Player": "ForaMercado", "Squad": "Y", "score": 60.0, "value_eur_m": 5.0, "in_market": False},
        ]
    )
    assert shortlist(players, "Caso", "FB", budget_eur_m=20.0)["Player"].tolist() == ["Indicado"]


def test_percentile_profile_rewards_low_values_on_negative_metrics() -> None:
    profile = percentile_profile(add_scores(_players()), "CB", ["P11"])
    by_metric = profile.set_index("metric")["percentile"]
    assert by_metric["clearances"] == 100
    assert by_metric["errors"] < by_metric["clearances"]


@pytest.fixture(scope="module")
def dataset() -> tuple[pd.DataFrame, dict[str, object]]:
    if not (RAW_DIR / "fbref_jogadores.csv").exists():
        pytest.skip("Os dados brutos não são distribuídos com o repositório.")
    return build_dataset()


def test_real_dataset_has_no_duplicate_market_ids(dataset: tuple[pd.DataFrame, dict[str, object]]) -> None:
    players, _ = dataset
    ids = players.drop_duplicates(["Player", "Squad"])["tm_id"].dropna()
    assert ids.is_unique


def test_real_dataset_respects_minutes_and_score_range(dataset: tuple[pd.DataFrame, dict[str, object]]) -> None:
    players, _ = dataset
    assert (players["minutes"] >= MIN_MINUTES).all()
    assert players["score"].between(0, 100).all()
    assert not players.duplicated(["Player", "Squad", "position_group"]).any()


def test_real_dataset_case_club_is_in_market(dataset: tuple[pd.DataFrame, dict[str, object]]) -> None:
    _, report = dataset
    assert report["case_club"] in report["covered_clubs"]
