"""Dashboard: uma decisão de contratação em três telas e o perfil dos jogadores em radar.

Uso: `uv run streamlit run app.py`
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.charts import NIGHT_THEME, RadarRole, comparison_chart, diagnosis_chart, market_chart, radar_chart
from src.export_figures import CASE_BUDGET_EUR_M, incumbent_for
from src.prepare import CASE_CLUB, LEAGUE_LABEL, load_processed
from src.rating import (
    MIN_MINUTES,
    POSITION_LABELS,
    diagnose_club,
    lowest_player_metrics,
    percentile_profile,
    rank_player_metrics,
    shortlist,
)
from src.ui import (
    HERO_HTML,
    format_number,
    legend_html,
    metric_bars,
    metric_row,
    player_card,
    player_card_grid,
    styled_table,
)

EMBLEM_PATH = Path(__file__).parent / "assets" / "emblema.svg"
BUDGET_MIN = 5
BUDGET_MAX = 100
BUDGET_STEP = 5
CHART_TOP_MARGIN = 28
CHART_RIGHT_MARGIN = 32
CLUB_SYMBOL = ":blue[◆]"
PICK_SYMBOL = ":orange[●]"
FOCUS_SYMBOL = ":green[■]"
NO_COMPARISON = "Só a mediana da posição"
HIGHLIGHT_COUNT = 3
TABLE_COLUMNS = {
    "Player": "Jogador",
    "Squad": "Clube",
    "Age": "Idade",
    "minutes": "Minutos",
    "score": "Nota",
    "value_eur_m": "Valor (€ mi)",
    "expected_value_eur_m": "Esperado (€ mi)",
    "price_ratio": "Preço / esperado",
}
TABLE_DIGITS = {"Idade": 0, "Minutos": 0, "Jogadores": 0, "Preço / esperado": 2}
PERCENTILE_DIGITS = 0


@st.cache_data
def load_data() -> tuple[pd.DataFrame, dict[str, object]]:
    return load_processed()


def show_chart(figure: go.Figure, key: str) -> None:
    """Mostra o título fora do Plotly, que não quebra linha em telas estreitas.

    A quebra no meio da frase só serve à figura exportada; no Markdown vira espaço.
    """
    with st.container(border=True):
        st.subheader(figure.layout.meta["headline"])
        st.markdown(figure.layout.meta["subtitle"].replace(" <br>", " ").replace("<br>", "  \n"))
        figure.update_layout(title=None, margin={"t": CHART_TOP_MARGIN, "r": CHART_RIGHT_MARGIN})
        st.plotly_chart(figure, width="stretch", theme=None, key=key)


def show_diagnosis(players: pd.DataFrame, diagnosis: pd.DataFrame, club: str) -> None:
    worst = diagnosis.iloc[0]
    metric_row(
        {
            "Posição mais fraca": worst["label"],
            f"Nota do {club}": format_number(worst["club_score"]),
            "Mediana da liga": format_number(worst["league_median"]),
        }
    )
    show_chart(diagnosis_chart(players, diagnosis, club, theme=NIGHT_THEME), "diagnosis")
    st.caption(
        f"A nota da posição é a média ponderada por minutos e usa {worst['club_players']} jogador(es) nesta posição."
    )
    with st.expander("Ver como tabela", icon=":material/table_chart:"):
        table = diagnosis.rename(
            columns={
                "label": "Posição",
                "club_score": "Clube",
                "league_median": "Mediana da liga",
                "gap": "Diferença",
                "club_players": "Jogadores",
            }
        ).drop(columns="position_group")
        st.dataframe(styled_table(table, TABLE_DIGITS), hide_index=True, width="stretch")


def show_market(
    players: pd.DataFrame,
    picks: pd.DataFrame,
    club: str,
    position: str,
    budget: float,
    report: dict[str, object],
) -> None:
    metric_row(
        {
            "Indicados": len(picks),
            "Orçamento": f"€{budget:.0f} mi",
            "Clubes no mercado": f"{len(report['covered_clubs'])} de {report['clubs_total']}",
        }
    )
    show_chart(market_chart(players, picks, club, position, budget, theme=NIGHT_THEME), "market")
    st.caption(
        "Indicado é quem tem nota acima da média do elenco, cabe no orçamento e custa menos que o "
        "preço esperado por uma diferença maior que o erro típico do modelo."
    )
    if picks.empty:
        st.info("Nenhum jogador atende às regras. Aumente o orçamento ou escolha outra posição.")
    else:
        st.subheader("Indicados pelas regras")
        player_card_grid(picks, PICK_SYMBOL, "Indicado")
        st.info(
            "Ponto de partida para o scouting, não recomendação final. "
            "O valor é uma estimativa do Transfermarkt, não o custo real.",
            icon=":material/travel_explore:",
        )
    with st.expander("Ver como tabela", icon=":material/table_chart:"):
        market = players[(players["position_group"] == position) & players["in_market"]]
        table = market.sort_values("score", ascending=False)[list(TABLE_COLUMNS)].rename(columns=TABLE_COLUMNS)
        st.dataframe(styled_table(table, TABLE_DIGITS), hide_index=True, width="stretch")


def show_decision(players: pd.DataFrame, picks: pd.DataFrame, club: str, position: str) -> None:
    if picks.empty:
        st.info("Nenhum jogador atende às regras. Aumente o orçamento ou escolha outra posição.")
        return
    candidate = st.selectbox("Candidato", picks["Player"].tolist())
    incumbent = incumbent_for(players, club, position)
    profile = percentile_profile(players, position, [candidate, incumbent])
    group = players[players["position_group"] == position].set_index("Player", drop=False)

    candidate_column, incumbent_column = st.columns(2)
    with candidate_column:
        player_card(group.loc[candidate].to_dict(), PICK_SYMBOL, "Candidato")
    with incumbent_column:
        player_card(group.loc[incumbent].to_dict(), CLUB_SYMBOL, f"Titular do {club}: mais minutos na posição")

    show_chart(comparison_chart(profile, candidate, incumbent, theme=NIGHT_THEME), "decision")
    with st.expander("Ver como tabela", icon=":material/table_chart:"):
        summary = group.loc[[candidate, incumbent], list(TABLE_COLUMNS)].rename(columns=TABLE_COLUMNS)
        st.dataframe(styled_table(summary, TABLE_DIGITS), hide_index=True, width="stretch")
        percentiles = profile.pivot(index="label", columns="Player", values="percentile").rename_axis(
            "Métrica (percentil)"
        )
        digits = {column: PERCENTILE_DIGITS for column in percentiles.columns}
        st.dataframe(styled_table(percentiles, digits), width="stretch")


def _player_role(player: pd.Series, picks: pd.DataFrame, club: str) -> RadarRole:
    if player["Squad"] == club:
        return RadarRole.CLUB
    return RadarRole.PICK if player["Player"] in set(picks["Player"]) else RadarRole.OTHER


def _card_identity(role: RadarRole, club: str) -> tuple[str, str]:
    identities = {
        RadarRole.CLUB: (CLUB_SYMBOL, f"Jogador do {club}"),
        RadarRole.PICK: (PICK_SYMBOL, "Indicado pelas regras"),
        RadarRole.OTHER: (FOCUS_SYMBOL, "Outro jogador da posição"),
    }
    return identities[role]


def show_players(players: pd.DataFrame, picks: pd.DataFrame, club: str, position: str) -> None:
    group = (
        players[players["position_group"] == position]
        .sort_values("score", ascending=False)
        .drop_duplicates("Player")
        .set_index("Player", drop=False)
    )
    names = group["Player"].tolist()
    default = picks["Player"].iloc[0] if not picks.empty else names[0]
    incumbent = incumbent_for(players, club, position)
    describe = lambda name: name if name == NO_COMPARISON else f"{name} ({group.loc[name, 'Squad']})"

    player_column, comparison_column = st.columns(2)
    name = player_column.selectbox("Jogador", names, index=names.index(default), format_func=describe)
    options = [NO_COMPARISON, *(other for other in names if other != name)]
    comparison_index = options.index(incumbent) if incumbent in options else 0
    chosen = comparison_column.selectbox("Comparar com", options, index=comparison_index, format_func=describe)
    comparison = None if chosen == NO_COMPARISON else chosen

    selected = [name] if comparison is None else [name, comparison]
    profile = percentile_profile(players, position, selected)
    role = _player_role(group.loc[name], picks, club)
    comparison_role = _player_role(group.loc[comparison], picks, club) if comparison else RadarRole.CLUB

    show_chart(radar_chart(profile, name, position, role, theme=NIGHT_THEME), "radar")
    st.caption(
        "O número em cada eixo é o percentil do jogador. Leia eixo por eixo: a forma do radar muda com a "
        "ordem dos eixos. Eventos raros, como cartões vermelhos, aparecem em contagem no subtítulo."
    )
    if comparison is not None:
        show_chart(comparison_chart(profile, name, comparison, NIGHT_THEME, role, comparison_role), "players")

    card_column, strengths_column = st.columns(2)
    symbol, label = _card_identity(role, club)
    with card_column:
        player_card(group.loc[name].to_dict(), symbol, label)
    with strengths_column:
        with st.container(border=True):
            metric_bars("Pontos fortes", rank_player_metrics(profile, name, position).head(HIGHLIGHT_COUNT))
            metric_bars("Menores percentis", lowest_player_metrics(profile, name).head(HIGHLIGHT_COUNT))

    with st.expander("Ver como tabela", icon=":material/table_chart:"):
        table = profile.pivot(index="label", columns="Player", values="percentile").rename_axis("Métrica (percentil)")
        digits = {column: PERCENTILE_DIGITS for column in table.columns}
        st.dataframe(styled_table(table, digits), width="stretch")


def show_limits(report: dict[str, object]) -> None:
    model = report["price_model"]
    with st.expander("Limitações e fontes", icon=":material/info:"):
        st.markdown(
            f"""
- **Cobertura:** há valores para {len(report["covered_clubs"])} dos {report["clubs_total"]} clubes; \
o mercado tem {report["market_players"]} jogadores.
- **Preço esperado:** o modelo explica {model["r_squared"]:.0%} da variação do valor, e a idade sozinha \
explica {model["r_squared_age_only"]:.0%}. O erro típico é de {str(round(model["typical_error_factor"], 2)).replace(".", ",")} vezes.
- **Nota:** mede produção estatística, e não contexto tático. Defensores de times dominantes podem ficar subavaliados.
- **Preço:** valor de mercado é uma estimativa do Transfermarkt, e não o custo real da transferência.
- **Indicação:** é um ponto de partida para o scouting, e não uma recomendação final.
- **Fontes:** FBref e Transfermarkt, a partir da base do projeto Esportes-2025 (Diretoria de Esportes da TAIL).
"""
        )


def show_header(report: dict[str, object]) -> None:
    st.html(HERO_HTML)
    st.markdown(
        f":green-badge[:material/sports_soccer: {LEAGUE_LABEL}] "
        f":gray-badge[:material/timer: {MIN_MINUTES} minutos ou mais] "
        f":orange-badge[:material/warning: Valores em {len(report['covered_clubs'])} de {report['clubs_total']} clubes]"
    )


def show_scenario(players: pd.DataFrame, clubs: list[str]) -> tuple[str, pd.DataFrame, str, float]:
    """Desenha os filtros na barra lateral e devolve o cenário escolhido."""
    with st.sidebar:
        st.subheader("Cenário", anchor=False)
        club = st.selectbox("Clube", clubs, index=clubs.index(CASE_CLUB))
        diagnosis = diagnose_club(players, club)
        position = st.selectbox(
            "Posição (começa pela mais fraca)",
            diagnosis["position_group"].tolist(),
            format_func=lambda code: POSITION_LABELS[code],
        )
        budget = float(
            st.slider("Orçamento (€ milhões)", BUDGET_MIN, BUDGET_MAX, int(CASE_BUDGET_EUR_M), BUDGET_STEP)
        )
        st.divider()
        st.markdown("**Como ler**")
        st.html(legend_html(NIGHT_THEME))
        st.divider()
        st.caption("Produto de visualização da disciplina GDCOC0096 (UFPB).")
    return club, diagnosis, position, budget


def main() -> None:
    st.set_page_config(page_title="Mercado com orçamento limitado", page_icon=":material/sports_soccer:", layout="wide")
    st.logo(str(EMBLEM_PATH), size="large")
    players, report = load_data()
    clubs = sorted(report["covered_clubs"])

    club, diagnosis, position, budget = show_scenario(players, clubs)
    picks = shortlist(players, club, position, budget)
    show_header(report)

    first, second, third, fourth = st.tabs(
        [
            ":material/stadium: 1. Diagnóstico",
            ":material/query_stats: 2. Mercado",
            ":material/compare_arrows: 3. Decisão",
            ":material/person_search: 4. Jogadores",
        ]
    )
    with first:
        show_diagnosis(players, diagnosis, club)
    with second:
        show_market(players, picks, club, position, budget, report)
    with third:
        show_decision(players, picks, club, position)
    with fourth:
        show_players(players, picks, club, position)
    show_limits(report)


if __name__ == "__main__":
    main()
