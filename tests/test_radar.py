"""Gráficos de jogador (radar e comparação), mercado e ordenação dos pontos fortes."""

import pandas as pd
import pytest

from src.charts import MEDIAN_PERCENTILE, NIGHT_THEME, RadarRole, comparison_chart, market_chart, radar_chart
from src.prepare import load_processed
from src.rating import (
    POSITION_WEIGHTS,
    RARE_EVENT_METRICS,
    lowest_player_metrics,
    percentile_profile,
    rank_player_metrics,
    shortlist,
    squad_floor,
)

SPENCE = "Djed Spence"
AJER = "Kristoffer Ajer"


@pytest.fixture(scope="module")
def players() -> pd.DataFrame:
    return load_processed()[0]


def test_rank_excludes_negative_metrics(players: pd.DataFrame) -> None:
    profile = percentile_profile(players, "FB", [AJER])
    ranked = rank_player_metrics(profile, AJER, "FB")
    assert "cards_red" not in ranked["metric"].tolist()
    assert ranked["percentile"].is_monotonic_decreasing


def test_lowest_metrics_leave_rare_events_out(players: pd.DataFrame) -> None:
    profile = percentile_profile(players, "FB", [SPENCE])
    lowest = lowest_player_metrics(profile, SPENCE)
    assert not set(lowest["metric"]) & RARE_EVENT_METRICS
    assert lowest["percentile"].is_monotonic_increasing


def test_radar_plots_the_same_percentiles_as_the_profile(players: pd.DataFrame) -> None:
    profile = percentile_profile(players, "FB", [SPENCE])
    figure = radar_chart(profile, SPENCE, "FB", RadarRole.PICK, theme=NIGHT_THEME)
    median, focus = figure.data

    assert set(median.r) == {MEDIAN_PERCENTILE}
    assert focus.name == SPENCE
    assert focus.r[0] == focus.r[-1]
    assert focus.fill is None
    expected = profile[profile["Player"] == SPENCE].set_index("label")["percentile"]
    for theta, value, row in zip(focus.theta, focus.r, focus.customdata):
        assert expected[row[1]] == value
        assert str(int(value)) in theta


def test_rare_events_show_as_counts_instead_of_percentiles(players: pd.DataFrame) -> None:
    profile = percentile_profile(players, "FB", [SPENCE, AJER])
    radar = radar_chart(profile, SPENCE, "FB", RadarRole.PICK, theme=NIGHT_THEME)
    dots = comparison_chart(profile, SPENCE, AJER, theme=NIGHT_THEME)
    assert not any("Cartões" in theta for theta in radar.data[1].theta)
    assert "Cartões vermelhos" not in list(dots.data[1].y)
    assert "cartões vermelhos na temporada: Spence 1, Ajer 0" in dots.layout.meta["subtitle"]


def test_comparison_keeps_the_fixed_visual_encoding(players: pd.DataFrame) -> None:
    profile = percentile_profile(players, "FB", [SPENCE, AJER])
    figure = comparison_chart(profile, SPENCE, AJER, theme=NIGHT_THEME)
    _, candidate, incumbent = figure.data
    assert (candidate.name, incumbent.name) == (SPENCE, AJER)
    assert (candidate.marker.color, candidate.marker.symbol) == (NIGHT_THEME.pick, "circle")
    assert (incumbent.marker.color, incumbent.marker.symbol) == (NIGHT_THEME.club, "diamond")


@pytest.mark.parametrize("role", list(RadarRole))
def test_two_players_of_the_same_group_get_different_color_and_shape(players: pd.DataFrame, role: RadarRole) -> None:
    profile = percentile_profile(players, "FB", [SPENCE, AJER])
    figure = comparison_chart(profile, SPENCE, AJER, NIGHT_THEME, role, role)
    _, first, second = figure.data
    assert first.marker.color != second.marker.color
    assert first.marker.symbol != second.marker.symbol


def test_market_chart_draws_squad_average_and_expected_prices(players: pd.DataFrame) -> None:
    picks = shortlist(players, "Brentford", "FB", 25.0)
    figure = market_chart(players, picks, "Brentford", "FB", 25.0, theme=NIGHT_THEME)
    floor = squad_floor(players, "Brentford", "FB")
    assert any(shape.y0 == shape.y1 == floor for shape in figure.layout.shapes)
    expected = next(trace for trace in figure.data if trace.name == "Preço esperado do indicado")
    assert list(expected.x) == picks["expected_value_eur_m"].tolist()
    assert (picks["score"] > floor).all()


def test_radar_renders_for_every_player_of_every_position(players: pd.DataFrame) -> None:
    for position in POSITION_WEIGHTS:
        for name in players.loc[players["position_group"] == position, "Player"].unique():
            profile = percentile_profile(players, position, [name])
            figure = radar_chart(profile, name, position, RadarRole.OTHER, theme=NIGHT_THEME)
            assert figure.layout.meta["headline"].startswith(name)
