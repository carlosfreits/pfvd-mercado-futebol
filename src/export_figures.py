"""Gera as figuras do artigo e os números citados no texto.

Uso: `uv run python -m src.export_figures`
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from src.charts import FIGURE_WIDTH, comparison_chart, diagnosis_chart, market_chart
from src.prepare import CASE_CLUB, ROOT, load_processed
from src.rating import diagnose_club, percentile_profile, shortlist

logger = logging.getLogger(__name__)

OUTPUT_DIR = ROOT / "article" / "figures"
CASE_POSITION = "FB"
CASE_BUDGET_EUR_M = 25.0
EXPORT_SCALE = 2


def incumbent_for(players: pd.DataFrame, club: str, position: str) -> str:
    """Retorna o jogador do clube com mais minutos na posição."""
    squad = players[(players["Squad"] == club) & (players["position_group"] == position)]
    return str(squad.sort_values("minutes", ascending=False)["Player"].iloc[0])


def score_value_correlations(players: pd.DataFrame) -> dict[str, float]:
    """Correlação entre log10(valor) e nota no mercado, por posição."""
    market = players[players["in_market"]]
    return {
        str(position): round(float(np.corrcoef(np.log10(group["value_eur_m"]), group["score"])[0, 1]), 2)
        for position, group in market.groupby("position_group")
    }


def build_facts(players: pd.DataFrame, report: dict[str, object], picks: pd.DataFrame) -> dict[str, object]:
    """Reúne os números citados no artigo, para nenhum ser digitado à mão."""
    columns = ["Player", "Squad", "Age", "minutes", "score", "value_eur_m", "expected_value_eur_m", "price_ratio"]
    return {
        "report": report,
        "diagnosis": diagnose_club(players, CASE_CLUB).to_dict("records"),
        "budget_eur_m": CASE_BUDGET_EUR_M,
        "picks": picks[columns].to_dict("records"),
        "score_value_correlation": score_value_correlations(players),
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    players, report = load_processed()
    diagnosis = diagnose_club(players, CASE_CLUB)
    picks = shortlist(players, CASE_CLUB, CASE_POSITION, CASE_BUDGET_EUR_M)
    incumbent = incumbent_for(players, CASE_CLUB, CASE_POSITION)
    candidate = str(picks["Player"].iloc[0])
    profile = percentile_profile(players, CASE_POSITION, [candidate, incumbent])

    figures = {
        "fig1_diagnostico.png": diagnosis_chart(players, diagnosis, CASE_CLUB),
        "fig2_mercado.png": market_chart(players, picks, CASE_CLUB, CASE_POSITION, CASE_BUDGET_EUR_M),
        "fig3_decisao.png": comparison_chart(profile, candidate, incumbent),
    }
    for name, figure in figures.items():
        figure.write_image(Path(OUTPUT_DIR / name), width=FIGURE_WIDTH, scale=EXPORT_SCALE)
        logger.info("Figura gerada: %s", name)

    facts = build_facts(players, report, picks)
    (ROOT / "article" / "facts.json").write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
