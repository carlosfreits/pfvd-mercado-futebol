"""Junta as temporadas das fontes do projeto em uma tabela única para os gráficos.

Mantém só as métricas comuns às fontes, e ausente continua vazio, nunca 0. As colunas
`data_source` e `is_partial` indicam o que cada linha permite concluir (veja docs/dados.md).

Uso:
    uv run python -m src.build_seasons
    uv run python -m src.build_seasons --fbref-dir caminho/com/2024-2025_outfield.csv
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

import pandas as pd

from src.prepare import PROCESSED_DIR, RAW_DIR, ROOT, _to_number, parse_value

logger = logging.getLogger(__name__)

OPEN_DIR = ROOT / "data" / "open" / "transfermarkt_datasets"
API_DIR = RAW_DIR / "api_football"
OUTPUT_FILE = PROCESSED_DIR / "seasons.csv"
FBREF_SOURCE = "fbref"
OPEN_SOURCE = "transfermarkt_datasets"
API_SOURCE = "api_football"
CASE_LEAGUE = "Premier_League"
CASE_SEASON = "2024-2025"
# Coletadas no meio do campeonato: têm de 19 a 27 jogos por time.
PARTIAL_FBREF = {("Brasileirao_A", "2025"), ("Brasileirao_B", "2025"), ("LPF", "2025"), ("MLS", "2025")}
KEY_COLUMNS = ["league", "season", "Player", "Squad"]
NUMERIC_COLUMNS = ["Age", "minutes", "games", "goals", "assists", "cards_yellow", "cards_red"]
COLUMNS = [
    "league",
    "season",
    "data_source",
    "is_partial",
    "player_id",
    "Player",
    "Squad",
    "Pos",
    *NUMERIC_COLUMNS,
    "value_eur_m",
]


def _standardize(frame: pd.DataFrame, source: str, is_partial: pd.Series | bool) -> pd.DataFrame:
    """Reduz às colunas comuns, sem preencher o que a fonte não informa."""
    subset = frame.reindex(columns=COLUMNS)
    # A idade do FBref pode vir como "25-123" (anos-dias).
    age = subset["Age"].astype("string").str.split("-").str[0]
    converted = {column: _to_number(subset[column]) for column in NUMERIC_COLUMNS if column != "Age"}
    return subset.assign(
        **converted,
        Age=pd.to_numeric(age, errors="coerce"),
        data_source=source,
        is_partial=is_partial,
    )


def _read_season_folder(folder: Path) -> pd.DataFrame:
    """Lê jogadores de linha e goleiros de uma pasta `{liga}_{temporada}`."""
    league, season = folder.name.rsplit("_", 1)
    files = [folder / name for name in ("jogadores.csv", "goleiros.csv") if (folder / name).exists()]
    if not files:
        return pd.DataFrame()
    frame = pd.concat([pd.read_csv(path) for path in files], ignore_index=True)
    return frame.assign(league=league, season=season)


def _read_source(base_dir: Path, source: str) -> pd.DataFrame:
    folders = sorted(path for path in (base_dir / "player_data").glob("*_*") if path.is_dir())
    frames = [frame for frame in map(_read_season_folder, folders) if not frame.empty]
    if not frames:
        return pd.DataFrame(columns=COLUMNS)
    combined = pd.concat(frames, ignore_index=True)
    partial = combined["is_partial"].astype("string").str.lower().eq("true")
    return _standardize(combined, source, partial.astype(bool))


def load_open_dataset(base_dir: Path = OPEN_DIR) -> pd.DataFrame:
    """Lê o dataset aberto e acrescenta o valor de mercado de cada jogador no clube."""
    players = _read_source(base_dir, OPEN_SOURCE)
    if players.empty:
        return players
    values = pd.concat(
        [pd.read_csv(path) for path in sorted((base_dir / "values").glob("*.csv"))], ignore_index=True
    ).drop_duplicates(["league", "ID", "Team"])
    lookup = values.assign(parsed_value=values["Value"].map(parse_value))[["league", "ID", "Team", "parsed_value"]]
    merged = players.drop(columns="value_eur_m").merge(
        lookup,
        how="left",
        left_on=["league", "player_id", "Squad"],
        right_on=["league", "ID", "Team"],
        validate="many_to_one",
    )
    return merged.rename(columns={"parsed_value": "value_eur_m"}).reindex(columns=COLUMNS)


def _fbref_partial(frame: pd.DataFrame) -> pd.Series:
    pairs = zip(frame["league"], frame["season"].astype(str), strict=True)
    return pd.Series([pair in PARTIAL_FBREF for pair in pairs], index=frame.index)


def _standardize_fbref(frame: pd.DataFrame) -> pd.DataFrame:
    """Goleiros guardam minutos e jogos em colunas próprias."""
    renames = {
        source: target
        for source, target in (("gk_minutes", "minutes"), ("gk_games", "games"))
        if source in frame and target not in frame
    }
    renamed = frame.rename(columns=renames).assign(season=lambda data: data["season"].astype(str))
    return _standardize(renamed, FBREF_SOURCE, _fbref_partial(renamed))


def load_case_fbref(raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    """Lê os arquivos do estudo de caso (Drive), se existirem."""
    frames = []
    for name in ("fbref_jogadores.csv", "fbref_goleiros.csv"):
        path = raw_dir / name
        if path.exists():
            frame = pd.read_csv(path, low_memory=False)
            defaults = {column: value for column, value in (("league", CASE_LEAGUE), ("season", CASE_SEASON)) if column not in frame}
            frames.append(_standardize_fbref(frame.assign(**defaults)))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLUMNS)


def load_fbref_history(fbref_dir: Path) -> pd.DataFrame:
    """Lê arquivos `{temporada}_outfield.csv` e `{temporada}_keepers.csv` de outra pasta."""
    paths = sorted(fbref_dir.glob("*_outfield.csv")) + sorted(fbref_dir.glob("*_keepers.csv"))
    if not paths:
        raise FileNotFoundError(f"Nenhum arquivo do FBref em {fbref_dir}.")
    tables = [pd.read_csv(path, low_memory=False) for path in paths]
    # Arquivos com `data_source` vieram de outra fonte e não são do FBref.
    frames = [_standardize_fbref(table) for table in tables if "data_source" not in table]
    if not frames:
        raise FileNotFoundError(f"Nenhum arquivo do FBref em {fbref_dir}.")
    return pd.concat(frames, ignore_index=True)


def build_seasons(
    open_dir: Path = OPEN_DIR,
    api_dir: Path = API_DIR,
    raw_dir: Path = RAW_DIR,
    fbref_dir: Path | None = None,
) -> pd.DataFrame:
    """Une as fontes disponíveis; só o dataset aberto é obrigatório."""
    sources = [load_open_dataset(open_dir), _read_source(api_dir, API_SOURCE), load_case_fbref(raw_dir)]
    if fbref_dir is not None:
        sources.append(load_fbref_history(fbref_dir))
    available = [frame.astype({"season": str}) for frame in sources if not frame.empty]
    if not available:
        raise FileNotFoundError(f"Nenhum dado encontrado em {open_dir}.")
    combined = pd.concat(available, ignore_index=True)
    # No FBref, um jogador pode aparecer no estudo de caso e no histórico, e goleiros em dois
    # arquivos. As outras fontes têm identificador, e homônimos no mesmo clube são pessoas diferentes.
    is_fbref = combined["data_source"] == FBREF_SOURCE
    fbref = combined[is_fbref].sort_values("minutes", ascending=False).drop_duplicates(KEY_COLUMNS)
    return pd.concat([combined[~is_fbref], fbref]).sort_values(KEY_COLUMNS, ignore_index=True)


def summarize(seasons: pd.DataFrame) -> pd.DataFrame:
    """Resume o que entrou, por fonte e temporada."""
    return (
        seasons.groupby(["data_source", "season"], as_index=False)
        .agg(ligas=("league", "nunique"), jogadores=("Player", "size"))
        .sort_values(["data_source", "season"])
    )


def main(argv: Sequence[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fbref-dir", type=Path, help="pasta opcional com a história do FBref")
    args = parser.parse_args(argv)

    seasons = build_seasons(fbref_dir=args.fbref_dir)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    seasons.to_csv(OUTPUT_FILE, index=False)
    logger.info("%s\n\n%s linhas gravadas em %s", summarize(seasons).to_string(index=False), len(seasons), OUTPUT_FILE)


if __name__ == "__main__":
    main()
