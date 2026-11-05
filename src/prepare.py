"""Limpa e une FBref e Transfermarkt, gerando a base usada no artigo e no dashboard.

Uso: `uv run python -m src.prepare`
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import asdict
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz
from unidecode import unidecode

from src.rating import (
    POSITION_WEIGHTS,
    add_expected_price,
    add_scores,
    equal_weight_rank_agreement,
    fit_price_model,
)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"

CASE_CLUB = "Brentford"
LEAGUE_LABEL = "Premier League 2024-25"
NAME_SCORE_CUTOFF = 85.0
MIN_CLUB_COVERAGE = 0.6
IDENTITY_COLUMNS = ["Player", "Nation", "Pos", "position", "Squad", "Age", "Born", "minutes"]
MATCH_COLUMNS = ["tm_id", "tm_name", "tm_club", "value_eur_m", "value_updated", "match_score"]
VALUE_PATTERN = re.compile(r"^€(\d+(?:\.\d+)?)([mk])$")
UNIT_TO_MILLIONS = {"m": 1.0, "k": 0.001}
TM_TO_FBREF_CLUB = {
    "Man Utd": "Manchester Utd",
    "Man City": "Manchester City",
    "Nott'm Forest": "Nott'ham Forest",
    "Newcastle": "Newcastle Utd",
}


def parse_value(raw: object) -> float:
    """Converte `€35.00m` ou `€500k` em milhões de euros; o resto vira NaN.

    Valores sem unidade são rejeitados de propósito: `€300` pode significar 300 mil,
    e adivinhar a unidade distorceria a escala em até mil vezes.
    """
    match = VALUE_PATTERN.match(str(raw).strip())
    if match is None:
        return math.nan
    return float(match.group(1)) * UNIT_TO_MILLIONS[match.group(2)]


def normalize_name(name: object) -> str:
    """Remove acentos e pontuação para comparar nomes entre as fontes."""
    return " ".join(re.sub(r"[^a-z ]", " ", unidecode(str(name)).lower()).split())


def _to_number(column: pd.Series) -> pd.Series:
    return pd.to_numeric(column.astype(str).str.replace(",", "", regex=False), errors="coerce")


def load_fbref(raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    """Une jogadores de linha e goleiros em uma linha por passagem em um clube."""
    outfield = pd.read_csv(raw_dir / "fbref_jogadores.csv", low_memory=False)
    keepers = pd.read_csv(raw_dir / "fbref_goleiros.csv", low_memory=False)
    keepers = keepers.assign(minutes=keepers["gk_minutes"])
    metrics = sorted({metric for weights in POSITION_WEIGHTS.values() for metric in weights})
    combined = pd.concat([outfield, keepers], ignore_index=True, sort=False)[IDENTITY_COLUMNS + metrics]
    return combined.assign(
        minutes=_to_number(combined["minutes"]).fillna(0.0),
        Born=_to_number(combined["Born"]),
        Age=_to_number(combined["Age"]),
    )


def load_transfermarkt(raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    """Lê o Transfermarkt, retirando repetições e convertendo valor e clube."""
    market = pd.read_csv(raw_dir / "transfermarkt_jogadores.csv").drop_duplicates("ID")
    return market.assign(
        value_eur_m=market["Value"].map(parse_value),
        birth_year=pd.to_datetime(market["DOB"], errors="coerce", format="%b %d, %Y").dt.year,
        name_key=market["Name"].map(normalize_name),
        tm_club=market["Team"].replace(TM_TO_FBREF_CLUB),
    ).dropna(subset=["value_eur_m", "birth_year"])


def match_players(fbref: pd.DataFrame, market: pd.DataFrame) -> pd.DataFrame:
    """Associa cada registro do Transfermarkt a no máximo uma linha do FBref.

    Exige mesmo ano de nascimento e nome parecido. Empates vão para a maior
    similaridade e, depois, para a passagem com mais minutos.
    """
    keys = fbref["Player"].map(normalize_name)
    candidates = []
    for index, player_key, born, minutes in zip(
        fbref.index, keys, fbref["Born"], fbref["minutes"], strict=True
    ):
        same_year = market[market["birth_year"] == born]
        for _, row in same_year.iterrows():
            similarity = fuzz.token_set_ratio(player_key, row["name_key"])
            if similarity >= NAME_SCORE_CUTOFF:
                candidates.append((similarity, minutes, index, row["ID"], row))

    candidates.sort(key=lambda item: (-item[0], -item[1]))
    used_rows: set[int] = set()
    used_ids: set[object] = set()
    matches = []
    for similarity, _, index, tm_id, row in candidates:
        if index in used_rows or tm_id in used_ids:
            continue
        used_rows.add(index)
        used_ids.add(tm_id)
        matches.append(
            {
                "fb_index": index,
                "tm_id": tm_id,
                "tm_name": row["Name"],
                "tm_club": row["tm_club"],
                "value_eur_m": row["value_eur_m"],
                "value_updated": row["Value last updated"],
                "match_score": similarity,
            }
        )
    joined = pd.DataFrame(matches, columns=["fb_index", *MATCH_COLUMNS]).set_index("fb_index")
    return fbref.join(joined, how="left")


def club_coverage(players: pd.DataFrame) -> pd.Series:
    """Fração dos jogadores de cada clube que recebeu valor de mercado."""
    unique_players = players.drop_duplicates(["Player", "Squad"])
    return (
        unique_players.groupby("Squad")["value_eur_m"]
        .apply(lambda values: values.notna().mean())
        .sort_values(ascending=False)
    )


def build_dataset(raw_dir: Path = RAW_DIR) -> tuple[pd.DataFrame, dict[str, object]]:
    """Executa o pipeline e devolve a base com o relatório de cobertura."""
    fbref = load_fbref(raw_dir)
    market = load_transfermarkt(raw_dir)
    rated = add_scores(match_players(fbref, market))

    coverage = club_coverage(rated)
    covered_clubs = coverage[coverage >= MIN_CLUB_COVERAGE].index.tolist()
    in_market = rated["Squad"].isin(covered_clubs) & rated["value_eur_m"].notna()
    model = fit_price_model(rated[in_market])

    priced = add_expected_price(rated[rated["value_eur_m"].notna()], model)
    price_columns = ["expected_value_eur_m", "price_ratio", "undervalued"]
    players = rated.join(priced[price_columns]).assign(in_market=in_market)

    unique_players = players.drop_duplicates(["Player", "Squad"])
    has_value = unique_players["value_eur_m"].notna()
    report: dict[str, object] = {
        "league": LEAGUE_LABEL,
        "case_club": CASE_CLUB,
        "players_rated": int(len(unique_players)),
        "player_position_rows": int(len(players)),
        "players_with_value": int(has_value.sum()),
        "market_players": int(unique_players["in_market"].sum()),
        "clubs_total": int(unique_players["Squad"].nunique()),
        "covered_clubs": covered_clubs,
        "coverage_by_club": {club: round(float(share), 3) for club, share in coverage.items()},
        "price_model": asdict(model),
        "rank_agreement_without_weights": equal_weight_rank_agreement(players),
        "club_mismatches": int((has_value & (unique_players["tm_club"] != unique_players["Squad"])).sum()),
        "fuzzy_matches": int((unique_players["match_score"] < 100).sum()),
    }
    return players, report


def load_processed(processed_dir: Path = PROCESSED_DIR) -> tuple[pd.DataFrame, dict[str, object]]:
    """Lê a base gerada por `main`, com as colunas lógicas já normalizadas."""
    players = pd.read_csv(processed_dir / "players.csv", low_memory=False)
    report = json.loads((processed_dir / "coverage.json").read_text(encoding="utf-8"))
    return players.assign(
        undervalued=players["undervalued"].astype("boolean").fillna(False).astype(bool),
        in_market=players["in_market"].astype(bool),
    ), report


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    players, report = build_dataset()
    players.to_csv(PROCESSED_DIR / "players.csv", index=False)
    (PROCESSED_DIR / "coverage.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("%s jogadores avaliados, %s no mercado.", report["players_rated"], report["market_players"])


if __name__ == "__main__":
    main()
