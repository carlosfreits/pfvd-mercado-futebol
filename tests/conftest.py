"""Ignora os testes que dependem da base, que não é distribuída com o repositório."""

from pathlib import Path

PROCESSED_PLAYERS = Path(__file__).parent.parent / "data" / "processed" / "players.csv"
TESTS_THAT_NEED_DATA = ["test_app.py", "test_radar.py"]

collect_ignore = [] if PROCESSED_PLAYERS.exists() else TESTS_THAT_NEED_DATA
