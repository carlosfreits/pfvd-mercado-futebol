"""Componentes visuais do dashboard e formatadores de números em português."""

from __future__ import annotations

from collections.abc import Callable, Mapping

import pandas as pd
import streamlit as st

from src.charts import ChartTheme
from src.rating import RATE_METRICS

MISSING_LABEL = "sem valor"
DEFAULT_DIGITS = 1
CARDS_PER_ROW = 2
# O st.html remove <svg> inline, então o campo vem de um arquivo em static/.
HERO_HTML = """
<div style="border:1px solid #2a4a38;border-radius:0.6rem;padding:0.9rem 1.25rem;
            background:#0f2a1c url('app/static/campo.svg') right center / auto 100% no-repeat;">
  <div style="color:#c6f135;font-family:'Barlow Condensed',Barlow,sans-serif;font-weight:600;
              font-size:1rem;letter-spacing:0.08em;">MERCADO COM ORÇAMENTO LIMITADO</div>
  <h1 style="margin:0.15rem 0 0;padding:0;color:#eef5ef;line-height:1.1;
             font-family:'Barlow Condensed',Barlow,sans-serif;font-weight:700;
             font-size:clamp(1.7rem,2.6vw,2.4rem);">
    Em que posição reforçar, quem contratar e se o preço compensa
  </h1>
</div>
"""
LEGEND_ROW = '<div style="margin-top:0.25rem;"><span style="color:{color};">{symbol}</span> {label}</div>'


def format_number(value: float | None, digits: int = DEFAULT_DIGITS) -> str:
    """Formata como em português (1.438,5), com sinal de menos e aviso de valor ausente."""
    if pd.isna(value):
        return MISSING_LABEL
    text = f"{float(value):,.{digits}f}"
    return text.replace(",", "\0").replace(".", ",").replace("\0", ".").replace("-", "−")


def format_eur_m(value: float | None) -> str:
    """Formata milhões de euros, sem inventar unidade quando o valor falta."""
    return MISSING_LABEL if pd.isna(value) else f"€{format_number(value)} mi"


def player_facts(player: Mapping[str, object]) -> str:
    """Resume clube, idade e minutos em uma linha."""
    return (
        f"{player['Squad']} · {format_number(player['Age'], 0)} anos · "
        f"{format_number(player['minutes'], 0)} min"
    )


def _number_formatter(digits: int) -> Callable[[float], str]:
    return lambda value: format_number(value, digits)


def styled_table(table: pd.DataFrame, digits: Mapping[str, int] | None = None) -> pd.io.formats.style.Styler:
    """Exibe números com vírgula decimal, mantendo a ordenação numérica das colunas."""
    overrides = digits or {}
    columns = table.select_dtypes("number").columns
    return table.style.format(
        {column: _number_formatter(overrides.get(column, DEFAULT_DIGITS)) for column in columns}
    )


def metric_row(metrics: Mapping[str, object]) -> None:
    """Mostra cartões de métrica que quebram linha em vez de cortar o valor."""
    with st.container(horizontal=True, gap="small"):
        for label, value in metrics.items():
            st.metric(label, value, border=True, width="stretch")


def legend_html(theme: ChartTheme) -> str:
    """Monta a legenda com as mesmas cores dos gráficos."""
    rows = (
        (theme.club, "◆", "Clube analisado"),
        (theme.pick, "●", "Indicados pelas regras"),
        (theme.context, "●", "Outros jogadores"),
        (theme.focus, "■", "Outro jogador da posição"),
    )
    return "".join(LEGEND_ROW.format(color=color, symbol=symbol, label=label) for color, symbol, label in rows)


def player_card(player: Mapping[str, object], symbol: str, role: str) -> None:
    """Mostra um jogador em camadas: identidade, nota e preço.

    As métricas têm a largura do conteúdo e quebram linha, para o valor nunca virar "€2...".
    """
    with st.container(border=True):
        st.markdown(f"{symbol} **{player['Player']}**  \n{role}")
        st.caption(player_facts(player))
        with st.container(horizontal=True, gap="medium"):
            st.metric("Nota", format_number(player["score"]), width="content")
            st.metric("Preço / esperado", format_number(player["price_ratio"], 2), width="content")
        with st.container(horizontal=True, gap="medium"):
            st.metric("Valor", format_eur_m(player["value_eur_m"]), width="content")
            st.metric("Esperado", format_eur_m(player["expected_value_eur_m"]), width="content")


def format_metric_value(metric: str, value: float) -> str:
    """Mostra taxas como porcentagem e os demais valores por 90 minutos."""
    if metric in RATE_METRICS:
        return f"{format_number(value)}%"
    return f"{format_number(value, 2)} por 90 min"


def metric_bars(title: str, metrics: pd.DataFrame) -> None:
    """Lista métricas com barra de percentil e o valor real, para o radar não ficar sozinho."""
    st.markdown(f"**{title}**")
    for row in metrics.to_dict("records"):
        percentile = int(row["percentile"])
        st.progress(
            percentile / 100,
            text=f"{row['label']}: percentil {percentile} ({format_metric_value(row['metric'], row['per_90'])})",
        )


def player_card_grid(players: pd.DataFrame, symbol: str, role: str) -> None:
    """Distribui os cartões em linhas, que viram uma coluna em telas estreitas."""
    records = players.to_dict("records")
    for start in range(0, len(records), CARDS_PER_ROW):
        for column, player in zip(st.columns(CARDS_PER_ROW), records[start : start + CARDS_PER_ROW]):
            with column:
                player_card(player, symbol, role)
