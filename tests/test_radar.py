"""Radar de percentis e ordenação dos pontos fortes."""

import pandas as pd
import pytest

from src.charts import MEDIAN_PERCENTILE, NIGHT_THEME, RadarRole, radar_chart
from src.prepare import load_processed
from src.rating import POSITION_WEIGHTS, lowest_player_metrics, percentile_profile, rank_player_metrics

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


def test_lowest_metrics_keep_negative_alerts(players: pd.DataFrame) -> None:
    profile = percentile_profile(players, "FB", [SPENCE])
    lowest = lowest_player_metrics(profile, SPENCE)
    assert lowest["metric"].iloc[0] == "cards_red"
    assert lowest["percentile"].is_monotonic_increasing


def test_radar_plots_the_same_percentiles_as_the_profile(players: pd.DataFrame) -> None:
    profile = percentile_profile(players, "FB", [SPENCE, AJER])
    figure = radar_chart(profile, SPENCE, "FB", RadarRole.PICK, AJER, RadarRole.CLUB, theme=NIGHT_THEME)
    median, focus, comparison = figure.data

    assert set(median.r) == {MEDIAN_PERCENTILE}
    assert (focus.name, comparison.name) == (SPENCE, AJER)
    assert focus.r[0] == focus.r[-1]
    expected = profile[profile["Player"] == SPENCE].set_index("label")["percentile"]
    for theta, value, row in zip(focus.theta, focus.r, focus.customdata):
        assert expected[row[1]] == value
        assert str(int(value)) in theta


def test_radar_keeps_the_fixed_visual_encoding(players: pd.DataFrame) -> None:
    profile = percentile_profile(players, "FB", [SPENCE, AJER])
    figure = radar_chart(profile, SPENCE, "FB", RadarRole.PICK, AJER, RadarRole.CLUB, theme=NIGHT_THEME)
    _, focus, comparison = figure.data
    assert (focus.marker.color, focus.marker.symbol) == (NIGHT_THEME.pick, "circle")
    assert (comparison.marker.color, comparison.marker.symbol) == (NIGHT_THEME.club, "diamond")


@pytest.mark.parametrize("role", list(RadarRole))
def test_two_players_of_the_same_group_are_filled_with_different_colors(players: pd.DataFrame, role: RadarRole) -> None:
    profile = percentile_profile(players, "FB", [SPENCE, AJER])
    figure = radar_chart(profile, SPENCE, "FB", role, AJER, role, theme=NIGHT_THEME)
    _, focus, comparison = figure.data
    assert focus.fill == comparison.fill == "toself"
    assert focus.fillcolor != comparison.fillcolor
    assert focus.line.color != comparison.line.color
    assert focus.marker.symbol != comparison.marker.symbol


def test_radar_renders_for_every_player_of_every_position(players: pd.DataFrame) -> None:
    for position in POSITION_WEIGHTS:
        for name in players.loc[players["position_group"] == position, "Player"].unique():
            profile = percentile_profile(players, position, [name])
            figure = radar_chart(profile, name, position, RadarRole.OTHER, theme=NIGHT_THEME)
            assert figure.layout.meta["headline"].startswith(name)
