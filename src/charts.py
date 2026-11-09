"""Gráficos do produto. O mesmo código gera as figuras do artigo e as do dashboard.

Codificação fixa em todas as telas: azul e losango para o clube analisado, laranja
e círculo grande para jogadores indicados, cinza para o contexto da liga. Cor e
forma são redundantes, para a identidade não depender só da cor.

O artigo usa `ARTICLE_THEME` (claro) e o dashboard, `NIGHT_THEME` (escuro). Os dois
mantêm os mesmos matizes; só a luminosidade muda para funcionar em cada fundo.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from src.rating import POSITION_LABELS, rank_player_metrics


@dataclass(frozen=True)
class ChartTheme:
    """Cores e fonte de um gráfico, sem alterar a codificação nem os dados."""

    club: str
    pick: str
    context: str
    median: str
    ink: str
    secondary_ink: str
    grid: str
    axis: str
    surface: str
    hover_background: str
    font: str
    focus: str = "#c6f135"
    second_player: str = "#d65fb0"


class RadarRole(Enum):
    """Papel do jogador no radar, que define a cor e a forma, como nos outros gráficos."""

    CLUB = "club"
    PICK = "pick"
    OTHER = "other"


ARTICLE_THEME = ChartTheme(
    club="#2a78d6",
    pick="#eb6834",
    context="#b5b3ab",
    median="#52514e",
    ink="#0b0b0b",
    secondary_ink="#52514e",
    grid="#e1e0d9",
    axis="#c3c2b7",
    surface="#fcfcfb",
    hover_background="#ffffff",
    font='system-ui, -apple-system, "Segoe UI", sans-serif',
)
NIGHT_THEME = ChartTheme(
    club="#4b93ea",
    pick="#e96630",
    context="#8fa398",
    median="#eef5ef",
    ink="#eef5ef",
    secondary_ink="#c3d1c8",
    grid="#1d3a2b",
    axis="#3d5c4b",
    surface="#0b1f17",
    hover_background="#12301f",
    font="Barlow, system-ui, sans-serif",
)

VALUE_TICKS = [1, 2, 5, 10, 20, 50, 100, 200]
JITTER_SEED = 7
JITTER_WIDTH = 0.22
FIGURE_WIDTH = 960
MARGIN_TOP = 120
MARGIN_BOTTOM = 150
LEGEND_OFFSET_PX = 104
BASE_FONT_SIZE = 16
TITLE_FONT_SIZE = 22
RADAR_HEIGHT = 640
RADAR_LABEL_WIDTH = 13
RADAR_DOMAIN_X = [0.22, 0.78]
RADAR_DOMAIN_Y = [0.1, 0.86]
RADAR_MARGIN_BOTTOM = 90
RADAR_LEGEND_Y = -0.07
RADAR_FILL_ALPHA = 0.25
RADAR_TICKS = [25, 50, 75, 100]
MEDIAN_PERCENTILE = 50


def _decimal(value: float, pattern: str = ".1f") -> str:
    """Formata com vírgula decimal e sinal de menos, como no restante do texto."""
    return format(value, pattern).replace(".", ",").replace("-", "−")


def _apply_layout(figure: go.Figure, title: str, subtitle: str, height: int, theme: ChartTheme) -> go.Figure:
    plot_height = height - MARGIN_TOP - MARGIN_BOTTOM
    figure.update_layout(
        separators=",.",
        title={
            "text": f"<b>{title}</b><br><span style='font-size:{BASE_FONT_SIZE}px;color:{theme.secondary_ink}'>{subtitle}</span>",
            "x": 0,
            "xanchor": "left",
            "font": {"size": TITLE_FONT_SIZE, "color": theme.ink},
        },
        meta={"headline": title, "subtitle": subtitle},
        template="none",
        height=height,
        margin={"l": 8, "r": 24, "t": MARGIN_TOP, "b": MARGIN_BOTTOM},
        paper_bgcolor=theme.surface,
        plot_bgcolor=theme.surface,
        font={"family": theme.font, "size": BASE_FONT_SIZE, "color": theme.secondary_ink},
        legend={"orientation": "h", "x": 0, "y": -LEGEND_OFFSET_PX / plot_height, "xanchor": "left", "yanchor": "top"},
        hoverlabel={"bgcolor": theme.hover_background, "font": {"color": theme.ink, "family": theme.font}},
    )
    axis_style = {"gridcolor": theme.grid, "linecolor": theme.axis, "zeroline": False, "automargin": True}
    figure.update_xaxes(**axis_style)
    figure.update_yaxes(**axis_style)
    return figure


def diagnosis_chart(
    players: pd.DataFrame, diagnosis: pd.DataFrame, club: str, theme: ChartTheme = ARTICLE_THEME
) -> go.Figure:
    """Mostra cada posição do clube sobre a distribuição da liga, da pior para a melhor."""
    ordered = diagnosis.sort_values("gap", ascending=False).reset_index(drop=True)
    rows = {position: index for index, position in enumerate(ordered["position_group"])}
    subset = players[players["position_group"].isin(rows)]
    is_club = subset["Squad"] == club
    jitter = np.random.default_rng(JITTER_SEED).uniform(-JITTER_WIDTH, JITTER_WIDTH, len(subset))
    subset_rows = subset["position_group"].map(rows).to_numpy() + jitter

    figure = go.Figure()
    league = subset[~is_club]
    figure.add_scatter(
        x=league["score"],
        y=subset_rows[~is_club.to_numpy()],
        mode="markers",
        name="Outros jogadores da liga",
        marker={"color": theme.context, "size": 8, "opacity": 0.65},
        customdata=league[["Player", "Squad"]],
        hovertemplate="%{customdata[0]} (%{customdata[1]})<br>Nota %{x:.1f}<extra></extra>",
    )
    figure.add_scatter(
        x=ordered["league_median"],
        y=ordered.index,
        mode="markers",
        name="Mediana da liga",
        marker={"symbol": "line-ns", "color": theme.median, "size": 26, "line": {"width": 3, "color": theme.median}},
        hovertemplate="Mediana da liga: %{x:.1f}<extra></extra>",
    )
    squad = subset[is_club]
    figure.add_scatter(
        x=squad["score"],
        y=subset_rows[is_club.to_numpy()],
        mode="markers",
        name=club,
        marker={"symbol": "diamond", "color": theme.club, "size": 13, "line": {"width": 2, "color": theme.surface}},
        customdata=squad[["Player", "minutes"]],
        hovertemplate="%{customdata[0]}<br>Nota %{x:.1f} em %{customdata[1]:.0f} min<extra></extra>",
    )
    worst = ordered.iloc[-1]
    figure.add_annotation(
        x=102,
        y=1,
        yref="paper",
        xanchor="right",
        yanchor="bottom",
        showarrow=False,
        text=f"{worst['label']}: <b>{_decimal(worst['gap'], '+.1f')}</b> em relação à mediana",
        font={"color": theme.ink, "size": BASE_FONT_SIZE},
    )
    figure.update_xaxes(title="Nota de desempenho<br>(50 = média da posição)", range=[-2, 102], tickvals=list(range(0, 101, 25)))
    figure.update_yaxes(
        tickmode="array",
        tickvals=list(ordered.index),
        ticktext=[label.replace(" / ", " /<br>") for label in ordered["label"]],
        showgrid=False,
        range=[-0.6, len(ordered) - 0.4],
    )
    return _apply_layout(
        figure,
        f"{worst['label']}: a posição mais fraca do {club}",
        "Notas por posição na Premier League 2024-25. Jogadores com 720 minutos ou mais.",
        height=540,
        theme=theme,
    )


def market_chart(
    players: pd.DataFrame,
    picks: pd.DataFrame,
    club: str,
    position: str,
    budget_eur_m: float,
    theme: ChartTheme = ARTICLE_THEME,
) -> go.Figure:
    """Cruza preço e desempenho no mercado coberto, destacando as indicações."""
    group = players[players["position_group"] == position]
    market = group[group["in_market"] & (group["Squad"] != club)]
    others = market[~market["Player"].isin(picks["Player"])]
    squad = group[(group["Squad"] == club) & group["value_eur_m"].notna()]
    hover = "%{customdata[0]} (%{customdata[1]}), %{customdata[2]:.0f} anos<br>Nota %{y:.1f}<br>€%{x:.1f} mi; esperado €%{customdata[3]:.1f} mi<extra></extra>"
    columns = ["Player", "Squad", "Age", "expected_value_eur_m"]

    figure = go.Figure()
    figure.add_scatter(
        x=others["value_eur_m"],
        y=others["score"],
        mode="markers",
        name="Outros jogadores do mercado",
        marker={"color": theme.context, "size": 10, "opacity": 0.85},
        customdata=others[columns],
        hovertemplate=hover,
    )
    figure.add_scatter(
        x=squad["value_eur_m"],
        y=squad["score"],
        mode="markers",
        name=f"Elenco do {club} (com valor)",
        marker={"symbol": "diamond", "color": theme.club, "size": 14, "line": {"width": 2, "color": theme.surface}},
        customdata=squad[columns],
        hovertemplate=hover,
    )
    figure.add_scatter(
        x=picks["value_eur_m"],
        y=picks["score"],
        mode="markers+text",
        name="Indicados pelas regras",
        text=picks["Player"],
        textposition=["top center" if index % 2 == 0 else "bottom center" for index in range(len(picks))],
        textfont={"color": theme.ink, "size": BASE_FONT_SIZE},
        marker={"color": theme.pick, "size": 15, "line": {"width": 2, "color": theme.surface}},
        customdata=picks[columns],
        hovertemplate=hover,
    )
    figure.add_vline(x=budget_eur_m, line={"color": theme.median, "width": 1})
    figure.add_annotation(
        x=np.log10(budget_eur_m),
        y=1,
        yref="paper",
        yanchor="bottom",
        showarrow=False,
        text=f"Orçamento: €{budget_eur_m:.0f} mi",
        font={"color": theme.secondary_ink, "size": BASE_FONT_SIZE},
    )
    figure.update_xaxes(
        title="Valor de mercado (€ milhões,<br>escala logarítmica)",
        type="log",
        tickvals=VALUE_TICKS,
        ticktext=[str(tick) for tick in VALUE_TICKS],
    )
    figure.update_yaxes(title="Nota de desempenho", range=[0, 105])
    label = POSITION_LABELS[position].lower()
    count = len(picks)
    noun = "opção" if count == 1 else "opções"
    headline = f"{count} {noun} para {label}: nota acima do elenco e preço abaixo do esperado"
    if count == 0:
        headline = f"Nenhuma opção para {label} atende às regras com este orçamento"
    clubs = players.loc[players["in_market"], "Squad"].nunique()
    return _apply_layout(
        figure,
        headline,
        f"Mercado limitado aos {clubs} clubes com dados de valor. O preço esperado considera nota, idade e posição.",
        height=540,
        theme=theme,
    )


def market_value_by_league_chart(
    seasons: pd.DataFrame, season: str, theme: ChartTheme = ARTICLE_THEME
) -> go.Figure:
    """Exemplo sobre `data/processed/seasons.csv`: soma do valor de mercado por liga."""
    rows = seasons[(seasons["season"] == season) & seasons["value_eur_m"].notna()]
    if rows.empty:
        raise ValueError(f"A temporada {season} não tem valor de mercado.")
    # O valor é do jogador, não da passagem: quem trocou de clube conta uma vez, onde mais jogou.
    players = rows.sort_values("minutes", ascending=False).drop_duplicates("player_id")
    totals = players.groupby("league")["value_eur_m"].sum().sort_values()
    labels = [league.replace("_", " ") for league in totals.index]
    figure = go.Figure(
        go.Bar(
            x=totals.tolist(),
            y=labels,
            orientation="h",
            marker={"color": theme.context, "cornerradius": 4},
            text=[f"€ {_decimal(total / 1000)} bi" for total in totals],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{y}: € %{x:,.0f} milhões<extra></extra>",
        )
    )
    figure.update_layout(showlegend=False)
    # Folga à direita para o rótulo da maior barra não encostar na borda.
    figure.update_xaxes(title="Soma dos valores de mercado (milhões de euros)", range=[0, totals.max() * 1.15])
    figure.update_yaxes(showgrid=False)
    return _apply_layout(
        figure,
        f"{labels[-1]} tem o maior valor de mercado em {season}",
        "Jogadores que atuaram na temporada, cada um contado uma vez. Valor é estimativa, não custo real.",
        height=max(460, 60 * len(labels) + 270),
        theme=theme,
    )


def comparison_chart(
    profile: pd.DataFrame, candidate: str, incumbent: str, theme: ChartTheme = ARTICLE_THEME
) -> go.Figure:
    """Compara dois jogadores em percentis da posição, da métrica mais pesada à menos pesada."""
    order = (
        profile[profile["Player"] == candidate].sort_values("weight", ascending=True)["label"].tolist()
    )
    figure = go.Figure()
    for player, color in ((incumbent, theme.club), (candidate, theme.pick)):
        rows = profile[profile["Player"] == player].set_index("label").reindex(order)
        figure.add_bar(
            x=rows["percentile"],
            y=order,
            orientation="h",
            name=player,
            marker={"color": color, "cornerradius": 4, "line": {"width": 2, "color": theme.surface}},
            customdata=rows[["per_90"]],
            hovertemplate=f"{player}<br>%{{y}}: percentil %{{x:.0f}}<br>Valor por 90 min (ou taxa): %{{customdata[0]:.2f}}<extra></extra>",
        )
    figure.add_vline(x=50, line={"color": theme.median, "width": 1})
    figure.add_annotation(
        x=50, y=1, yref="paper", yanchor="bottom", showarrow=False, text="Mediana da posição", font={"size": BASE_FONT_SIZE, "color": theme.secondary_ink}
    )
    figure.update_layout(barmode="group", bargap=0.3, bargroupgap=0.05)
    figure.update_xaxes(title="Percentil na posição<br>(100 = melhor)", range=[0, 100], tickvals=[0, 25, 50, 75, 100])
    figure.update_yaxes(showgrid=False)
    wins = _metric_wins(profile, candidate, incumbent)
    return _apply_layout(
        figure,
        f"{candidate} supera {incumbent} em {wins} de {len(order)} métricas",
        "Por 90 minutos, da métrica mais pesada à menos pesada. 100 é o melhor, mesmo em métricas negativas.",
        height=max(460, 70 * len(order) + 170),
        theme=theme,
    )


def _role_style(role: RadarRole, theme: ChartTheme) -> tuple[str, str]:
    """Mantém azul e losango para o clube e laranja e círculo para os indicados."""
    styles = {
        RadarRole.CLUB: (theme.club, "diamond"),
        RadarRole.PICK: (theme.pick, "circle"),
        RadarRole.OTHER: (theme.focus, "square"),
    }
    return styles[role]


def _translucent(hex_color: str, alpha: float) -> str:
    red, green, blue = (int(hex_color[index : index + 2], 16) for index in (1, 3, 5))
    return f"rgba({red},{green},{blue},{alpha})"


def _closed(values: list) -> list:
    """Repete o primeiro ponto para fechar o polígono do radar."""
    return [*values, values[0]]


def radar_chart(
    profile: pd.DataFrame,
    player: str,
    position: str,
    role: RadarRole,
    comparison: str | None = None,
    comparison_role: RadarRole = RadarRole.CLUB,
    theme: ChartTheme = ARTICLE_THEME,
) -> go.Figure:
    """Mostra o perfil do jogador em percentis da posição, sobre a mediana tracejada."""
    ordered = profile[profile["Player"] == player].sort_values("weight", ascending=False)
    metrics = ordered["metric"].tolist()
    percentiles = ordered["percentile"].astype(int).tolist()
    axis_labels = [
        f"{'<br>'.join(textwrap.wrap(label, RADAR_LABEL_WIDTH, break_long_words=False))}<br><b>{value}</b>"
        for label, value in zip(ordered["label"], percentiles)
    ]
    hover = "%{customdata[0]}<br>%{customdata[1]}: percentil %{r:.0f}<br>Valor por 90 min (ou taxa): %{customdata[2]:.2f}<extra></extra>"

    figure = go.Figure()
    figure.add_scatterpolar(
        r=_closed([MEDIAN_PERCENTILE] * len(metrics)),
        theta=_closed(axis_labels),
        mode="lines",
        name="Mediana da posição",
        line={"color": theme.median, "width": 2, "dash": "dash"},
        hoverinfo="skip",
    )
    series = [(player, _role_style(role, theme))]
    if comparison is not None:
        # Dois jogadores do mesmo grupo teriam cor e forma iguais, então o segundo muda as duas.
        second_style = (theme.second_player, "triangle-up") if comparison_role == role else _role_style(comparison_role, theme)
        series.append((comparison, second_style))
    for name, (color, symbol) in series:
        rows = profile[profile["Player"] == name].set_index("metric").reindex(metrics)
        figure.add_scatterpolar(
            r=_closed(rows["percentile"].tolist()),
            theta=_closed(axis_labels),
            mode="lines+markers",
            name=name,
            fill="toself",
            fillcolor=_translucent(color, RADAR_FILL_ALPHA),
            line={"color": color, "width": 3},
            marker={"color": color, "symbol": symbol, "size": 11, "line": {"width": 2, "color": theme.surface}},
            customdata=_closed([[name, label, value] for label, value in zip(rows["label"], rows["per_90"])]),
            hovertemplate=hover,
        )
    figure.update_layout(
        polar={
            "domain": {"x": RADAR_DOMAIN_X, "y": RADAR_DOMAIN_Y},
            "bgcolor": theme.surface,
            "radialaxis": {
                "range": [0, 100],
                "tickvals": RADAR_TICKS,
                "gridcolor": theme.grid,
                "linecolor": theme.axis,
                "angle": 90 - 180 / len(metrics),
                "tickangle": 0,
            },
            "angularaxis": {"direction": "clockwise", "rotation": 90, "gridcolor": theme.grid, "linecolor": theme.axis},
        }
    )
    # Só a primeira letra muda, para preservar siglas como xG e PSxG.
    strongest = [
        label[0].lower() + label[1:] for label in rank_player_metrics(profile, player, position)["label"].head(2)
    ]
    _apply_layout(
        figure,
        f"{player}: mais forte em {strongest[0]} e {strongest[1]}",
        "Percentis entre os jogadores da posição com 720 minutos ou mais. 100 é o melhor, mesmo em métricas negativas.",
        height=RADAR_HEIGHT,
        theme=theme,
    )
    return figure.update_layout(margin={"b": RADAR_MARGIN_BOTTOM}, legend={"y": RADAR_LEGEND_Y})


def _metric_wins(profile: pd.DataFrame, candidate: str, incumbent: str) -> int:
    pivot = profile.pivot(index="metric", columns="Player", values="percentile")
    return int((pivot[candidate] > pivot[incumbent]).sum())
