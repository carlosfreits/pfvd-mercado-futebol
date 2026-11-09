"""Os coletores precisam ler e gravar dentro do projeto, e não em uma pasta acima dele."""

from pathlib import Path

import import_dataset
import run

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_api_paths_stay_inside_the_project() -> None:
    assert run.REPO_ROOT == PROJECT_ROOT
    assert run.DATA_DIR == PROJECT_ROOT / "data" / "raw" / "api_football"
    assert run.ENV_FILE == PROJECT_ROOT / ".env"


def test_open_dataset_paths_stay_inside_the_project() -> None:
    assert import_dataset.DATA_DIR == PROJECT_ROOT / "data" / "open" / "transfermarkt_datasets"


def test_large_dataset_zip_is_not_saved_in_the_versioned_folder() -> None:
    assert import_dataset.DEFAULT_ZIP.parent == PROJECT_ROOT / "data" / "raw"
