"""Gráficos do produto. O mesmo código gera as figuras do artigo e as do dashboard.

Codificação fixa em todas as telas: azul e losango para o clube analisado, laranja
e círculo grande para jogadores indicados, cinza para o contexto da liga. Cor e
forma são redundantes, para a identidade não depender só da cor.

O artigo usa `ARTICLE_THEME` (claro) e o dashboard, `NIGHT_THEME` (escuro). Os dois
mantêm os mesmos matizes; só a luminosidade muda para funcionar em cada fundo.
As cores de jogador (clube, indicado, foco e segundo jogador) foram conferidas com
um validador de daltonismo e contraste em todos os pares, nos dois fundos.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from src.rating import (
    POSITION_LABELS,
    RARE_EVENT_METRICS,
    rank_player_metrics,
    squad_floor,
)


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
    focus: str = "#2bab95"
    second_player: str = "#b04c9a"


class RadarRole(Enum):
    """Papel do jogador, que define a cor e a forma em todos os gráficos de jogador."""

    CLUB = "club"
    PICK = "pick"
    OTHER = "other"


ARTICLE_THEME = ChartTheme(
    club="#2a78d6",
    pick="#eb6834",
    # Escuro o bastante para 3:1 com o fundo claro, sem competir com azul e laranja.
    context="#8a887f",
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
MARGIN_BOTTOM = 130
SUBTITLE_LINE_PX = 24
TITLE_PAD_PX = 32
LEGEND_OFFSET_PX = 84
AXIS_TITLE_STANDOFF = 12
BASE_FONT_SIZE = 16
SMALL_FONT_SIZE = 13
TITLE_FONT_SIZE = 22
RADAR_HEIGHT = 640
RADAR_LABEL_WIDTH = 13
RADAR_DOMAIN_X = [0.22, 0.78]
RADAR_DOMAIN_Y = [0.1, 0.86]
RADAR_MARGIN_BOTTOM = 90
RADAR_LEGEND_Y = -0.07
RADAR_RINGS = [25, 50, 75, 100]
MEDIAN_PERCENTILE = 50
DOT_ROW_PX = 56
DOT_MIN_HEIGHT = 440
DOT_EXTRA_PX = 220


def _decimal(value: float, pattern: str = ".1f") -> str:
    """Formata com vírgula decimal e sinal de menos, como no restante do texto."""
    return format(value, pattern).replace(".", ",").replace("-", "−")


def _apply_layout(figure: go.Figure, title: str, subtitle: str, height: int, theme: ChartTheme) -> go.Figure:
    top = MARGIN_TOP + SUBTITLE_LINE_PX * subtitle.count("<br>")
    plot_height = height - top - MARGIN_BOTTOM
    figure.update_layout(
        separators=",.",
        title={
            "text": f"<b>{title}</b><br><span style='font-size:{BASE_FONT_SIZE}px;color:{theme.secondary_ink}'>{subtitle}</span>",
            "x": 0,
            "xanchor": "left",
            "y": 1,
            "yref": "container",
            "yanchor": "top",
            "pad": {"t": TITLE_PAD_PX},
            "font": {"size": TITLE_FONT_SIZE, "color": theme.ink},
        },
        meta={"headline": title, "subtitle": subtitle},
        template="none",
        height=height,
        margin={"l": 8, "r": 24, "t": top, "b": MARGIN_BOTTOM},
        paper_bgcolor=theme.surface,
        plot_bgcolor=theme.surface,
        font={"family": theme.font, "size": BASE_FONT_SIZE, "color": theme.secondary_ink},
        legend={"orientation": "h", "x": 0, "y": -LEGEND_OFFSET_PX / plot_height, "xanchor": "left", "yanchor": "top"},
        hoverlabel={"bgcolor": theme.hover_background, "font": {"color": theme.ink, "family": theme.font}},
    )
    axis_style = {"gridcolor": theme.grid, "linecolor": theme.axis, "zeroline": False, "automargin": True}
    figure.update_xaxes(**axis_style, title_standoff=AXIS_TITLE_STANDOFF)
    figure.update_yaxes(**axis_style)
    return figure


def diagnosis_chart(
    players: pd.DataFrame, diagnosis: pd.DataFrame, club: str, theme: ChartTheme = ARTICLE_THEME
) -> go.Figure:
    """Mostra cada posição do clube sobre a distribuição da liga, da pior para a melhor.

    A diferença para a mediana fica no rótulo de cada linha, junto da posição a que se refere.
    """
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
    ticktext = []
    for label, gap in zip(ordered["label"], ordered["gap"]):
        value = _decimal(gap, "+.1f")
        value = f"<b>{value}</b>" if label == worst["label"] else value
        name = f"<b>{label}</b>" if label == worst["label"] else label
        ticktext.append(f"{name.replace(' / ', ' /<br>')} <span style='color:{theme.ink}'>{value}</span>")
    figure.update_xaxes(title="Nota de desempenho (50 = média da posição)", range=[-2, 102], tickvals=list(range(0, 101, 25)))
    figure.update_yaxes(
        tickmode="array",
        tickvals=list(ordered.index),
        ticktext=ticktext,
        showgrid=False,
        range=[-0.6, len(ordered) - 0.4],
    )
    return _apply_layout(
        figure,
        f"{worst['label']}: a posição mais fraca do {club}",
        f"Notas na Premier League 2024-25, jogadores com 720 minutos ou mais. "
        f"<br>O número ao lado da posição é a diferença do {club} para a mediana.",
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
    """Cruza preço e desempenho no mercado coberto e mostra as três regras de indicação.

    A linha vertical é o orçamento, a horizontal é a nota média do elenco e o traço de cada
    indicado vai do preço atual até o preço esperado pelo modelo.
    """
    group = players[players["position_group"] == position]
    market = group[group["in_market"] & (group["Squad"] != club)]
    others = market[~market["Player"].isin(picks["Player"])]
    squad = group[(group["Squad"] == club) & group["value_eur_m"].notna()]
    floor = squad_floor(players, club, position)
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
    if not picks.empty:
        gaps_x = [value for actual, expected in zip(picks["value_eur_m"], picks["expected_value_eur_m"]) for value in (actual, expected, None)]
        gaps_y = [value for score in picks["score"] for value in (score, score, None)]
        figure.add_scatter(
            x=gaps_x, y=gaps_y, mode="lines", line={"color": theme.pick, "width": 2}, hoverinfo="skip", showlegend=False
        )
        figure.add_scatter(
            x=picks["expected_value_eur_m"],
            y=picks["score"],
            mode="markers",
            name="Preço esperado do indicado",
            marker={"symbol": "circle-open", "color": theme.pick, "size": 13, "line": {"width": 2}},
            customdata=picks[["Player", "expected_value_eur_m"]],
            hovertemplate="%{customdata[0]}<br>Preço esperado: €%{customdata[1]:.1f} mi<extra></extra>",
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
    figure.add_hline(y=floor, line={"color": theme.club, "width": 1})
    figure.add_annotation(
        x=0,
        xref="paper",
        y=floor,
        xanchor="left",
        yanchor="bottom",
        showarrow=False,
        text=f"Média do elenco: {_decimal(floor)}",
        font={"color": theme.secondary_ink, "size": SMALL_FONT_SIZE},
    )
    figure.update_xaxes(
        title="Valor de mercado (€ milhões, escala logarítmica)",
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
        f"Mercado limitado aos {clubs} clubes com dados de valor. O traço vai do preço atual ao preço esperado "
        "<br>pelo modelo (nota, idade e posição).",
        height=560,
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


def _pair_styles(first: RadarRole, second: RadarRole, theme: ChartTheme) -> list[tuple[str, str]]:
    """Dois jogadores do mesmo grupo teriam cor e forma iguais, então o segundo muda as duas."""
    second_style = (theme.second_player, "triangle-up") if first == second else _role_style(second, theme)
    return [_role_style(first, theme), second_style]


def _plotted(profile: pd.DataFrame) -> pd.DataFrame:
    return profile[~profile["metric"].isin(RARE_EVENT_METRICS)]


def _rare_note(profile: pd.DataFrame, names: list[str]) -> str:
    """Resume em contagens os eventos raros que ficam fora dos gráficos de percentil."""
    rare = profile[profile["metric"].isin(RARE_EVENT_METRICS)]
    parts = []
    for label, rows in rare.groupby("label", sort=False):
        totals = rows.set_index("Player")["season_total"]
        counts = ", ".join(f"{name.split()[-1]} {totals[name]:.0f}" for name in names if name in totals)
        parts.append(f"{label.lower()} na temporada: {counts}")
    return "Evento raro, mostrado em contagem: " + "; ".join(parts) + "." if parts else ""


def comparison_chart(
    profile: pd.DataFrame,
    candidate: str,
    incumbent: str,
    theme: ChartTheme = ARTICLE_THEME,
    candidate_role: RadarRole = RadarRole.PICK,
    incumbent_role: RadarRole = RadarRole.CLUB,
) -> go.Figure:
    """Compara dois jogadores em percentis da posição com um ponto por jogador e métrica.

    O traço entre os pontos mostra a diferença. As métricas vão da mais pesada (no topo)
    à menos pesada, e o peso aparece no rótulo.
    """
    plotted = _plotted(profile)
    weights = plotted[plotted["Player"] == candidate].sort_values("weight", ascending=True)
    order = weights["label"].tolist()
    ticktext = [
        f"{label} <span style='font-size:{SMALL_FONT_SIZE}px;color:{theme.secondary_ink}'>peso {_decimal(weight)}</span>"
        for label, weight in zip(weights["label"], weights["weight"])
    ]
    first = plotted[plotted["Player"] == candidate].set_index("label").reindex(order)
    second = plotted[plotted["Player"] == incumbent].set_index("label").reindex(order)

    figure = go.Figure()
    figure.add_scatter(
        x=[value for low, high in zip(first["percentile"], second["percentile"]) for value in (low, high, None)],
        y=[value for label in order for value in (label, label, None)],
        mode="lines",
        line={"color": theme.axis, "width": 3},
        hoverinfo="skip",
        showlegend=False,
    )
    for player, rows, (color, symbol) in zip(
        (candidate, incumbent), (first, second), _pair_styles(candidate_role, incumbent_role, theme)
    ):
        figure.add_scatter(
            x=rows["percentile"],
            y=order,
            mode="markers",
            name=player,
            marker={"color": color, "symbol": symbol, "size": 15, "line": {"width": 2, "color": theme.surface}},
            customdata=rows[["per_90"]],
            hovertemplate=f"{player}<br>%{{y}}: percentil %{{x:.0f}}<br>Valor por 90 min (ou taxa): %{{customdata[0]:.2f}}<extra></extra>",
        )
    figure.add_vline(x=MEDIAN_PERCENTILE, line={"color": theme.median, "width": 1})
    figure.add_annotation(
        x=MEDIAN_PERCENTILE,
        y=1,
        yref="paper",
        yanchor="bottom",
        showarrow=False,
        text="Mediana da posição",
        font={"size": BASE_FONT_SIZE, "color": theme.secondary_ink},
    )
    figure.update_xaxes(title="Percentil na posição (100 = melhor)", range=[-3, 103], tickvals=[0, 25, 50, 75, 100])
    figure.update_yaxes(tickmode="array", tickvals=order, ticktext=ticktext, showgrid=True)
    wins = _metric_wins(plotted, candidate, incumbent)
    subtitle = "Por 90 minutos, da métrica mais pesada à menos pesada. 100 é o melhor, mesmo em métricas negativas."
    note = _rare_note(profile, [candidate, incumbent])
    return _apply_layout(
        figure,
        f"{candidate} supera {incumbent} em {wins} de {len(order)} métricas",
        f"{subtitle}<br>{note}" if note else subtitle,
        height=max(DOT_MIN_HEIGHT, DOT_ROW_PX * len(order) + DOT_EXTRA_PX),
        theme=theme,
    )


def _closed(values: list) -> list:
    """Repete o primeiro ponto para fechar o polígono do radar."""
    return [*values, values[0]]


def radar_chart(
    profile: pd.DataFrame, player: str, position: str, role: RadarRole, theme: ChartTheme = ARTICLE_THEME
) -> go.Figure:
    """Mostra o perfil de um jogador em percentis da posição, sobre a mediana tracejada.

    Só um jogador e sem preenchimento: a área do polígono depende da ordem dos eixos e não
    tem significado. Para comparar dois jogadores, use `comparison_chart`.
    """
    ordered = _plotted(profile)
    ordered = ordered[ordered["Player"] == player].sort_values("weight", ascending=False)
    percentiles = ordered["percentile"].astype(int).tolist()
    axis_labels = [
        f"{'<br>'.join(textwrap.wrap(label, RADAR_LABEL_WIDTH, break_long_words=False))}<br><b>{value}</b>"
        for label, value in zip(ordered["label"], percentiles)
    ]
    color, symbol = _role_style(role, theme)

    figure = go.Figure()
    figure.add_scatterpolar(
        r=_closed([MEDIAN_PERCENTILE] * len(axis_labels)),
        theta=_closed(axis_labels),
        mode="lines",
        name="Mediana da posição",
        line={"color": theme.median, "width": 2, "dash": "dash"},
        hoverinfo="skip",
    )
    figure.add_scatterpolar(
        r=_closed(percentiles),
        theta=_closed(axis_labels),
        mode="lines+markers",
        name=player,
        line={"color": color, "width": 3},
        marker={"color": color, "symbol": symbol, "size": 11, "line": {"width": 2, "color": theme.surface}},
        customdata=_closed([[player, label, value] for label, value in zip(ordered["label"], ordered["per_90"])]),
        hovertemplate="%{customdata[0]}<br>%{customdata[1]}: percentil %{r:.0f}<br>Valor por 90 min (ou taxa): %{customdata[2]:.2f}<extra></extra>",
    )
    figure.update_layout(
        polar={
            "domain": {"x": RADAR_DOMAIN_X, "y": RADAR_DOMAIN_Y},
            "bgcolor": theme.surface,
            # Os anéis marcam 25, 50, 75 e 100; o valor exato está em negrito em cada eixo.
            "radialaxis": {"range": [0, 100], "tickvals": RADAR_RINGS, "showticklabels": False, "gridcolor": theme.grid, "linecolor": theme.axis},
            "angularaxis": {"direction": "clockwise", "rotation": 90, "gridcolor": theme.grid, "linecolor": theme.axis},
        }
    )
    # Só a primeira letra muda, para preservar siglas como xG e PSxG.
    strongest = [
        label[0].lower() + label[1:] for label in rank_player_metrics(profile, player, position)["label"].head(2)
    ]
    subtitle = "Percentis entre os jogadores da posição com 720 minutos ou mais. Anéis a cada 25; 100 é o melhor."
    note = _rare_note(profile, [player])
    _apply_layout(
        figure,
        f"{player}: mais forte em {strongest[0]} e {strongest[1]}",
        f"{subtitle}<br>{note}" if note else subtitle,
        height=RADAR_HEIGHT,
        theme=theme,
    )
    return figure.update_layout(margin={"b": RADAR_MARGIN_BOTTOM}, legend={"y": RADAR_LEGEND_Y})


def _metric_wins(profile: pd.DataFrame, candidate: str, incumbent: str) -> int:
    pivot = profile.pivot(index="metric", columns="Player", values="percentile")
    return int((pivot[candidate] > pivot[incumbent]).sum())
