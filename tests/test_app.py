"""Executa o dashboard real em modo de teste."""

from streamlit.testing.v1 import AppTest

from src.rating import POSITION_LABELS

APP_PATH = "../app.py"
TIMEOUT_SECONDS = 60
CODE_BY_LABEL = {label: code for code, label in POSITION_LABELS.items()}
LOW_BUDGET_EUR_M = 15


def _run_app() -> AppTest:
    return AppTest.from_file(APP_PATH, default_timeout=TIMEOUT_SECONDS).run()


def _metric_values(app: AppTest) -> dict[str, str]:
    return {metric.label: metric.value for metric in app.metric}


def test_default_case_renders_without_errors() -> None:
    app = _run_app()
    assert not app.exception
    assert app.sidebar.selectbox[0].value == "Brentford"
    assert app.sidebar.selectbox[1].value == "FB"
    assert app.main.selectbox[0].value == "Djed Spence"


def test_every_club_and_position_renders_without_errors() -> None:
    app = _run_app()
    for club in list(app.sidebar.selectbox[0].options):
        app.sidebar.selectbox[0].set_value(club).run()
        assert not app.exception, club
        for label in list(app.sidebar.selectbox[1].options):
            app.sidebar.selectbox[1].set_value(CODE_BY_LABEL[label]).run()
            assert not app.exception, (club, label)


def test_default_cards_show_the_case_numbers() -> None:
    metrics = _metric_values(_run_app())
    assert metrics["Posição mais fraca"] == "Lateral"
    assert metrics["Nota do Brentford"] == "36,7"
    assert metrics["Mediana da liga"] == "50,9"
    assert metrics["Indicados"] == "2"
    assert metrics["Clubes no mercado"] == "10 de 20"


def test_low_budget_replaces_player_cards_with_a_message() -> None:
    app = _run_app()
    app.sidebar.slider[0].set_value(LOW_BUDGET_EUR_M).run()
    assert not app.exception
    assert "Candidato" not in [box.label for box in app.main.selectbox]
    assert _metric_values(app)["Indicados"] == "0"
    assert all("Nenhum jogador atende às regras" in box.value for box in app.info)


def test_players_tab_starts_with_first_pick_against_the_incumbent() -> None:
    selects = {box.label: box.value for box in _run_app().main.selectbox}
    assert selects["Jogador"] == "Djed Spence"
    assert selects["Comparar com"] == "Kristoffer Ajer"


def test_players_tab_handles_low_budget_and_no_comparison() -> None:
    app = _run_app()
    app.sidebar.slider[0].set_value(LOW_BUDGET_EUR_M).run()
    comparison = next(box for box in app.main.selectbox if box.label == "Comparar com")
    comparison.set_value("Só a mediana da posição").run()
    assert not app.exception
