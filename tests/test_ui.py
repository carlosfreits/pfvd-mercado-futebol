"""Formatadores usados nos cartões e nas tabelas do dashboard."""

import math

import pandas as pd

from src.ui import MISSING_LABEL, format_eur_m, format_number, player_facts, styled_table


def test_format_number_uses_portuguese_separators_and_real_minus() -> None:
    assert format_number(1438.5) == "1.438,5"
    assert format_number(-14.2) == "−14,2"
    assert format_number(0.484, 2) == "0,48"


def test_missing_values_never_show_as_nan() -> None:
    assert format_number(math.nan) == MISSING_LABEL
    assert format_number(None) == MISSING_LABEL
    assert format_eur_m(math.nan) == MISSING_LABEL


def test_format_eur_m_adds_currency_and_unit() -> None:
    assert format_eur_m(20.0) == "€20,0 mi"


def test_player_facts_summarizes_club_age_and_minutes() -> None:
    player = {"Squad": "Brentford", "Age": 26.0, "minutes": 1438.0}
    assert player_facts(player) == "Brentford · 26 anos · 1.438 min"


def test_styled_table_formats_display_and_keeps_numeric_data() -> None:
    table = pd.DataFrame({"Jogador": ["A", "B"], "Nota": [68.34, math.nan], "Minutos": [1438.0, 900.0]})
    styled = styled_table(table, {"Minutos": 0})
    html = styled.to_html()
    assert "68,3" in html
    assert "1.438" in html
    assert MISSING_LABEL in html
    assert styled.data["Nota"].iloc[0] == 68.34
