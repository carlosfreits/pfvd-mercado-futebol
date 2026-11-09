"""Importa a temporada 2025-2026 do dataset aberto transfermarkt-datasets (licença CC0).

Traz minutos, gols, assistências, cartões, posição detalhada e valor de mercado de 7 ligas.
Não usa scraping: lê o arquivo publicado pelo projeto e grava CSVs por liga.

Uso (a partir da raiz do repositório):
    uv run python collect/transfermarkt_datasets/import_dataset.py --zip caminho/do/arquivo.zip
    uv run python collect/transfermarkt_datasets/import_dataset.py --download
"""

from __future__ import annotations

import argparse
import logging
import sys
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd
import requests

DATASET_URL = "https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/transfermarkt-datasets.zip"
DOWNLOAD_TIMEOUT_SECONDS = 600
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "open" / "transfermarkt_datasets"
DEFAULT_ZIP = REPO_ROOT / "data" / "raw" / "transfermarkt-datasets.zip"
DATA_SOURCE = "transfermarkt_datasets"
PLAYER_ID_PREFIX = "tm_"
SEASON_YEAR = 2025
SEASON_LABEL = "2025-2026"
SEASON_END_YEAR = 2026
# Só estas ligas têm atuações por jogador no dataset; Brasil, Argentina, México e MLS não têm.
COMPETITIONS = {
    "GB1": "Premier_League",
    "ES1": "La_Liga",
    "IT1": "Serie_A_TIM",
    "L1": "Bundesliga",
    "FR1": "Ligue_1",
    "PO1": "Primeira_Liga",
    "BE1": "Belgian_Pro_League",
}
GENERAL_POSITIONS = {"Goalkeeper": "GK", "Defender": "DF", "Midfield": "MF", "Attack": "FW"}
DETAILED_POSITIONS = {
    "Centre-Back": "CB",
    "Left-Back": "FB",
    "Right-Back": "FB",
    "Defensive Midfield": "DM",
    "Central Midfield": "CM",
    "Attacking Midfield": "AM",
    "Left Midfield": "WM",
    "Right Midfield": "WM",
    "Left Winger": "WM",
    "Right Winger": "WM",
    "Second Striker": "AM",
    "Centre-Forward": "AM",
}

logger = logging.getLogger("transfermarkt_datasets")


def read_table(archive: zipfile.ZipFile, name: str) -> pd.DataFrame:
    path = next(n for n in archive.namelist() if n.split("/")[-1] == f"{name}.csv.gz")
    with archive.open(path) as handle:
        return pd.read_csv(handle, compression="gzip", low_memory=False)


def format_market_value(value: float) -> str | None:
    """Usa o formato que `parse_value`, de src/prepare.py, sabe interpretar."""
    if pd.isna(value) or value <= 0:
        return None
    return f"€{value / 1e6:.2f}m" if value >= 1e6 else f"€{value / 1e3:.0f}k"


def _position_label(general: object, detailed: object) -> str:
    """Gera 'DF (CB)': posição geral e detalhada."""
    code = GENERAL_POSITIONS.get(str(general), "")
    if code in ("", "GK"):
        return code
    detail = DETAILED_POSITIONS.get(str(detailed))
    return f"{code} ({detail})" if detail else code


def season_appearances(appearances: pd.DataFrame, games: pd.DataFrame, competition: str) -> pd.DataFrame:
    """Soma as atuações da liga na temporada, com uma linha por jogador e clube."""
    season_games = games[(games["competition_id"] == competition) & (games["season"] == SEASON_YEAR)]
    played = appearances[
        appearances["game_id"].isin(season_games["game_id"]) & (appearances["minutes_played"] > 0)
    ]
    return (
        played.groupby(["player_id", "player_club_id"], as_index=False)
        .agg(
            games=("game_id", "nunique"),
            minutes=("minutes_played", "sum"),
            goals=("goals", "sum"),
            assists=("assists", "sum"),
            cards_yellow=("yellow_cards", "sum"),
            cards_red=("red_cards", "sum"),
        )
    )


def build_rows(totals: pd.DataFrame, players: pd.DataFrame, clubs: pd.DataFrame, today: date) -> pd.DataFrame:
    """Junta os totais aos perfis e calcula as colunas derivadas."""
    merged = totals.merge(players, on="player_id", how="left", validate="many_to_one").merge(
        clubs[["club_id", "name"]].rename(columns={"name": "Squad"}),
        left_on="player_club_id",
        right_on="club_id",
        how="left",
        validate="many_to_one",
    )
    born = pd.to_datetime(merged["date_of_birth"], errors="coerce").dt.year
    minutes_90s = (merged["minutes"] / 90).round(2)
    position = [
        _position_label(general, detailed)
        for general, detailed in zip(merged["position"], merged["sub_position"], strict=True)
    ]
    goals_assists = merged["goals"] + merged["assists"]
    return pd.DataFrame(
        {
            "Player": merged["name"],
            "Nation": merged["country_of_citizenship"],
            "Pos": [label[:2] for label in position],
            "position": position,
            "Squad": merged["Squad"],
            "Age": SEASON_END_YEAR - born,
            "Born": born,
            "height": merged["height_in_cm"].map(lambda cm: f"{cm:.0f}cm", na_action="ignore"),
            "player_id": PLAYER_ID_PREFIX + merged["player_id"].astype(str),
            "games": merged["games"],
            "minutes": merged["minutes"],
            "minutes_90s": minutes_90s,
            "goals": merged["goals"],
            "assists": merged["assists"],
            "goals_assists": goals_assists,
            "cards_yellow": merged["cards_yellow"],
            "cards_red": merged["cards_red"],
            "goals_per90": (merged["goals"] / minutes_90s).round(2),
            "assists_per90": (merged["assists"] / minutes_90s).round(2),
            "goals_assists_per90": (goals_assists / minutes_90s).round(2),
            "market_value": merged["market_value_in_eur"].map(format_market_value),
            "data_source": DATA_SOURCE,
            "is_partial": False,
            "collected_at": today.isoformat(),
        }
    )


def keeper_rows(rows: pd.DataFrame) -> pd.DataFrame:
    keepers = rows[rows["Pos"] == "GK"].copy()
    keepers["gk_games"] = keepers["games"]
    keepers["gk_minutes"] = keepers["minutes"]
    return keepers


def value_rows(rows: pd.DataFrame, league: str) -> pd.DataFrame:
    """Gera a tabela de valores de mercado de uma liga."""
    return pd.DataFrame(
        {
            "league": league,
            "season": SEASON_LABEL,
            "Name": rows["Player"],
            "ID": rows["player_id"],
            "Value": rows["market_value"],
            "Age": rows["Age"],
            "Height (m)": rows["height"],
            "Nationality": rows["Nation"],
            "Position": rows["position"],
            "Team": rows["Squad"],
        }
    )


def import_dataset(zip_path: Path, data_dir: Path, today: date) -> dict[str, tuple[int, int]]:
    """Grava os CSVs de cada liga e devolve (jogadores de linha, goleiros) por liga."""
    with zipfile.ZipFile(zip_path) as archive:
        appearances = read_table(archive, "appearances")
        games = read_table(archive, "games")
        players = read_table(archive, "players")
        clubs = read_table(archive, "clubs")

    results = {}
    all_values = []
    for competition, league in COMPETITIONS.items():
        rows = build_rows(season_appearances(appearances, games, competition), players, clubs, today)
        if rows.empty:
            raise ValueError(f"{competition}: sem atuações na temporada {SEASON_LABEL}.")
        outfield = rows[rows["Pos"] != "GK"].drop(columns="market_value")
        keepers = keeper_rows(rows).drop(columns="market_value")
        target = data_dir / "player_data" / f"{league}_{SEASON_LABEL}"
        target.mkdir(parents=True, exist_ok=True)
        outfield.to_csv(target / "jogadores.csv", index=False, encoding="utf-8")
        keepers.to_csv(target / "goleiros.csv", index=False, encoding="utf-8")
        all_values.append(value_rows(rows, league))
        results[league] = (len(outfield), len(keepers))

    values_dir = data_dir / "values"
    values_dir.mkdir(parents=True, exist_ok=True)
    pd.concat(all_values, ignore_index=True).to_csv(
        values_dir / f"{SEASON_LABEL}_players.csv", index=False, encoding="utf-8"
    )
    return results


def download_dataset(destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    with requests.get(DATASET_URL, stream=True, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
        response.raise_for_status()
        with temporary.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                handle.write(chunk)
    temporary.replace(destination)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, help="arquivo já baixado")
    parser.add_argument("--download", action="store_true", help="baixa o arquivo (cerca de 240 MB)")
    args = parser.parse_args(argv)

    zip_path = args.zip or DEFAULT_ZIP
    if args.download:
        download_dataset(zip_path)
    if not zip_path.exists():
        logger.error("Arquivo não encontrado: %s. Use --download ou --zip.", zip_path)
        return 2
    for league, (outfield, keepers) in import_dataset(zip_path, DATA_DIR, date.today()).items():
        logger.info("%-22s %4d de linha | %3d goleiros", league, outfield, keepers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
