"""Nota de desempenho e índice de custo-benefício.

Adaptado de `FootballRating` (Esportes-2025, Diretoria de Esportes da TAIL), que
define os pesos por posição e a escala 50 + 20 por desvio-padrão. Diferenças
deliberadas em relação ao original:

- métricas de volume são convertidas para "por 90 minutos", para a nota não
  premiar apenas quem jogou mais;
- a nota vale por posição: um jogador com duas posições listadas tem duas notas,
  sem média entre elas, porque o FBref lista as posições em ordem alfabética e
  não informa qual é a principal;
- notas são calculadas por passagem em um clube, evitando misturar duas passagens.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

MIN_MINUTES = 720
BASE_SCORE = 50.0
POINTS_PER_STD = 20.0

POSITION_WEIGHTS: dict[str, dict[str, float]] = {
    "GK": {
        "gk_clean_sheets": 3.0,
        "gk_saves": 2.8,
        "gk_save_pct": 2.5,
        "gk_passes_completed_launched": 1.5,
        "gk_passes_pct_launched": 1.8,
        "gk_goals_against": -2.5,
        "gk_psxg_net": 2.0,
        "gk_crosses_stopped_pct": 1.8,
    },
    "CB": {
        "tackles_won": 2.2,
        "interceptions": 2.2,
        "clearances": 2.5,
        "aerials_won_pct": 2.0,
        "blocks": 2.0,
        "progressive_passes": 1.8,
        "errors": -2.0,
        "own_goals": -1.8,
    },
    "FB": {
        "tackles_won": 2.0,
        "interceptions": 1.8,
        "crosses_into_penalty_area": 2.4,
        "assists": 2.2,
        "progressive_carries": 2.0,
        "take_ons_won": 1.8,
        "cards_red": -1.4,
    },
    "DM": {
        "tackles_won": 2.5,
        "interceptions": 2.5,
        "ball_recoveries": 2.0,
        "passes_pct": 2.2,
        "progressive_passes": 1.8,
        "fouls": -0.6,
        "dispossessed": -0.8,
    },
    "CM": {
        "progressive_passes": 2.2,
        "passes_into_final_third": 2.0,
        "assists": 2.0,
        "goals": 1.8,
        "progressive_carries": 1.8,
        "tackles": 1.6,
        "dispossessed": -1.0,
    },
    "AM": {
        "goals": 2.4,
        "assists": 2.6,
        "xg": 2.0,
        "xg_assist": 2.2,
        "shots_on_target": 2.0,
        "carries_into_penalty_area": 2.2,
        "take_ons_won": 1.8,
        "dispossessed": -1.2,
    },
    "WM": {
        "assists": 2.2,
        "crosses_into_penalty_area": 2.4,
        "xg_assist": 2.0,
        "take_ons_won": 2.2,
        "progressive_carries": 2.0,
        "goals": 1.8,
        "dispossessed": -1.2,
    },
}

RATE_METRICS = frozenset(
    {"aerials_won_pct", "passes_pct", "gk_save_pct", "gk_passes_pct_launched", "gk_crosses_stopped_pct"}
)
# Eventos que quase ninguém tem na temporada. Em percentil, um único cartão derruba o
# jogador para perto de zero, então os gráficos mostram a contagem em vez do percentil.
RARE_EVENT_METRICS = frozenset({"cards_red", "own_goals", "errors"})
GENERAL_POSITION_FALLBACK = {"DF": "CB", "MF": "CM", "FW": "AM"}
REFERENCE_AGE = 25.0

POSITION_LABELS = {
    "GK": "Goleiro",
    "CB": "Zagueiro",
    "FB": "Lateral",
    "DM": "Volante",
    "CM": "Meio-campista",
    "AM": "Meia-atacante / atacante",
    "WM": "Ponta",
}

METRIC_LABELS = {
    "gk_clean_sheets": "Jogos sem sofrer gol",
    "gk_saves": "Defesas",
    "gk_save_pct": "% de defesas",
    "gk_passes_completed_launched": "Lançamentos certos",
    "gk_passes_pct_launched": "% de lançamentos certos",
    "gk_goals_against": "Gols sofridos",
    "gk_psxg_net": "Gols evitados (PSxG)",
    "gk_crosses_stopped_pct": "% de cruzamentos cortados",
    "tackles_won": "Desarmes certos",
    "interceptions": "Interceptações",
    "clearances": "Cortes",
    "aerials_won_pct": "% de duelos aéreos",
    "blocks": "Bloqueios",
    "progressive_passes": "Passes progressivos",
    "errors": "Erros que geram finalização",
    "own_goals": "Gols contra",
    "crosses_into_penalty_area": "Cruzamentos na área",
    "assists": "Assistências",
    "progressive_carries": "Conduções progressivas",
    "take_ons_won": "Dribles certos",
    "cards_red": "Cartões vermelhos",
    "ball_recoveries": "Bolas recuperadas",
    "passes_pct": "% de passes certos",
    "fouls": "Faltas cometidas",
    "dispossessed": "Perdas de posse",
    "passes_into_final_third": "Passes ao terço final",
    "goals": "Gols",
    "tackles": "Desarmes",
    "xg": "Gols esperados (xG)",
    "xg_assist": "Assistências esperadas (xA)",
    "shots_on_target": "Finalizações no alvo",
    "carries_into_penalty_area": "Conduções até a área",
}


@dataclass(frozen=True)
class PriceModel:
    """Modelo log10(valor) ~ nota + idade + idade² + posição, ajustado no mercado coberto."""

    score_coef: float
    age_coef: float
    age_squared_coef: float
    position_intercepts: dict[str, float]
    r_squared: float
    r_squared_age_only: float
    typical_error_factor: float
    n_rows: int


def listed_positions(general: object, detailed: object) -> list[str]:
    """Retorna todas as posições detalhadas do jogador; sem detalhe, usa a geral."""
    general_text = str(general).upper()
    detailed_text = str(detailed).upper()
    if "GK" in general_text:
        return ["GK"]
    if "(" in detailed_text and ")" in detailed_text:
        inside = detailed_text[detailed_text.find("(") + 1 : detailed_text.find(")")]
        tokens = [part.strip() for part in inside.replace("-", ",").split(",")]
        found = [token for token in tokens if token in POSITION_WEIGHTS]
        if found:
            return found
    first_general = general_text.replace("-", ",").split(",")[0].strip()
    fallback = GENERAL_POSITION_FALLBACK.get(first_general)
    return [fallback] if fallback else []


def _per_90(frame: pd.DataFrame, metrics: list[str]) -> pd.DataFrame:
    """Converte métricas de volume para por 90 minutos, sem alterar as de taxa."""
    converted = frame[metrics].astype(float).fillna(0.0)
    volume = [metric for metric in metrics if metric not in RATE_METRICS]
    nineties = frame["minutes"].astype(float) / 90.0
    return converted.assign(**{metric: converted[metric] / nineties for metric in volume})


def _position_scores(group: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    metrics = list(weights)
    values = _per_90(group, metrics)
    spread = values.std(ddof=0).replace(0.0, 1.0)
    z_scores = (values - values.mean()) / spread
    raw = z_scores.mul(pd.Series(weights)).sum(axis=1)
    raw_std = raw.std(ddof=0)
    if raw_std == 0:
        return pd.Series(BASE_SCORE, index=group.index)
    return (BASE_SCORE + raw / raw_std * POINTS_PER_STD).clip(0.0, 100.0).round(1)


def add_scores(players: pd.DataFrame) -> pd.DataFrame:
    """Gera uma linha por jogador e posição listada, com `position_group` e `score`."""
    positions = [
        listed_positions(general, detailed)
        for general, detailed in zip(players["Pos"], players["position"], strict=True)
    ]
    long = (
        players.assign(position_group=positions)
        .query("minutes >= @MIN_MINUTES")
        .explode("position_group")
        .dropna(subset=["position_group"])
        .reset_index(drop=True)
    )
    scores = [
        _position_scores(group, POSITION_WEIGHTS[position])
        for position, group in long.groupby("position_group")
    ]
    return long.assign(score=pd.concat(scores).reindex(long.index))


def _r_squared(target: np.ndarray, predicted: np.ndarray) -> float:
    total = float(((target - target.mean()) ** 2).sum())
    return 1.0 - float(((target - predicted) ** 2).sum()) / total if total else 0.0


def fit_price_model(market: pd.DataFrame) -> PriceModel:
    """Ajusta por mínimos quadrados o preço esperado dados nota, idade e posição."""
    target = np.log10(market["value_eur_m"].astype(float)).to_numpy()
    age = market["Age"].astype(float).to_numpy() - REFERENCE_AGE
    score = market["score"].astype(float).to_numpy()
    dummies = pd.get_dummies(market["position_group"], dtype=float)
    design = np.column_stack([score, age, age**2, dummies.to_numpy()])
    coefficients, *_ = np.linalg.lstsq(design, target, rcond=None)
    predicted = design @ coefficients

    age_design = np.column_stack([np.ones(len(age)), age, age**2])
    age_coefficients, *_ = np.linalg.lstsq(age_design, target, rcond=None)

    typical_error = float(np.sqrt(((target - predicted) ** 2).mean()))
    return PriceModel(
        score_coef=float(coefficients[0]),
        age_coef=float(coefficients[1]),
        age_squared_coef=float(coefficients[2]),
        position_intercepts={
            position: float(value) for position, value in zip(dummies.columns, coefficients[3:], strict=True)
        },
        r_squared=_r_squared(target, predicted),
        r_squared_age_only=_r_squared(target, age_design @ age_coefficients),
        typical_error_factor=10.0**typical_error,
        n_rows=len(market),
    )


def add_expected_price(players: pd.DataFrame, model: PriceModel) -> pd.DataFrame:
    """Adiciona preço esperado, razão preço/esperado e o indício de subvalorização.

    Só há indício quando o preço fica abaixo do esperado por mais que o erro típico
    do modelo; diferenças menores não se distinguem do ruído.
    """
    age = players["Age"].astype(float) - REFERENCE_AGE
    log_expected = (
        model.score_coef * players["score"].astype(float)
        + model.age_coef * age
        + model.age_squared_coef * age**2
        + players["position_group"].map(model.position_intercepts).astype(float)
    )
    expected = 10.0**log_expected
    ratio = players["value_eur_m"].astype(float) / expected
    return players.assign(
        expected_value_eur_m=expected.round(1),
        price_ratio=ratio.round(2),
        undervalued=ratio < 1.0 / model.typical_error_factor,
    )


def equal_weight_rank_agreement(players: pd.DataFrame) -> dict[str, float]:
    """Correlação de postos, por posição, entre a nota e a mesma nota sem os pesos.

    Mede quanto o ordenamento depende dos pesos escolhidos pelo projeto de origem.
    """
    agreement = {}
    for position, group in players.groupby("position_group"):
        weights = {metric: float(np.sign(weight)) for metric, weight in POSITION_WEIGHTS[position].items()}
        unweighted = _position_scores(group, weights)
        agreement[str(position)] = round(float(group["score"].rank().corr(unweighted.rank())), 2)
    return agreement


def percentile_profile(players: pd.DataFrame, position: str, names: list[str]) -> pd.DataFrame:
    """Parcela da posição com resultado igual ou pior; 100 é o melhor, mesmo em métricas negativas."""
    weights = POSITION_WEIGHTS[position]
    metrics = list(weights)
    group = players[players["position_group"] == position]
    values = _per_90(group, metrics)
    signs = pd.Series({metric: 1.0 if weight > 0 else -1.0 for metric, weight in weights.items()})
    ranks = values.mul(signs).rank(pct=True, method="max") * 100.0
    rows = [
        {
            "Player": name,
            "metric": metric,
            "label": METRIC_LABELS[metric],
            "weight": abs(weights[metric]),
            "percentile": round(float(ranks.loc[index, metric]), 0),
            "per_90": round(float(values.loc[index, metric]), 2),
            "season_total": float(group.loc[index, metric]) if pd.notna(group.loc[index, metric]) else 0.0,
        }
        for name in names
        for index in group.index[group["Player"] == name][:1]
        for metric in metrics
    ]
    return pd.DataFrame(rows)


def rank_player_metrics(profile: pd.DataFrame, player: str, position: str) -> pd.DataFrame:
    """Ordena as métricas de produção do jogador, da mais forte para a mais fraca.

    Métricas negativas ficam de fora: 100 em cartões vermelhos só indica que o jogador não
    recebeu cartão, como acontece com a maioria dos laterais, e não um ponto forte.
    """
    weights = POSITION_WEIGHTS[position]
    rows = profile[(profile["Player"] == player) & profile["metric"].map(lambda metric: weights[metric] > 0)]
    return rows.sort_values(["percentile", "weight"], ascending=False).reset_index(drop=True)


def lowest_player_metrics(profile: pd.DataFrame, player: str) -> pd.DataFrame:
    """Ordena as métricas do menor percentil para o maior.

    Eventos raros ficam de fora: um único cartão vermelho vira percentil 3, o que
    exagera a diferença para quem não recebeu nenhum. Eles aparecem como contagem.
    """
    rows = profile[(profile["Player"] == player) & ~profile["metric"].isin(RARE_EVENT_METRICS)]
    return rows.sort_values(["percentile", "weight"], ascending=[True, False]).reset_index(drop=True)


def squad_floor(players: pd.DataFrame, club: str, position: str) -> float:
    """Nota média do elenco na posição, ponderada por minutos; é a nota que um reforço precisa superar."""
    squad = players[(players["position_group"] == position) & (players["Squad"] == club)]
    return float(np.average(squad["score"], weights=squad["minutes"])) if len(squad) else 0.0


def shortlist(players: pd.DataFrame, club: str, position: str, budget_eur_m: float) -> pd.DataFrame:
    """Lista reforços: melhores que o elenco, dentro do orçamento e baratos além do erro."""
    group = players[players["position_group"] == position]
    floor = squad_floor(players, club, position)
    selected = group[
        group["in_market"]
        & group["undervalued"]
        & (group["Squad"] != club)
        & (group["value_eur_m"] <= budget_eur_m)
        & (group["score"] > floor)
    ]
    return selected.sort_values("score", ascending=False).reset_index(drop=True)


def diagnose_club(players: pd.DataFrame, club: str) -> pd.DataFrame:
    """Compara, por posição, a nota média do clube (ponderada por minutos) com a liga."""
    rows = []
    for position, group in players.groupby("position_group"):
        squad = group[group["Squad"] == club]
        if squad.empty:
            continue
        weighted = np.average(squad["score"], weights=squad["minutes"])
        rows.append(
            {
                "position_group": position,
                "label": POSITION_LABELS[position],
                "club_score": round(float(weighted), 1),
                "league_median": round(float(group["score"].median()), 1),
                "gap": round(float(weighted - group["score"].median()), 1),
                "club_players": len(squad),
            }
        )
    return pd.DataFrame(rows).sort_values("gap").reset_index(drop=True)
