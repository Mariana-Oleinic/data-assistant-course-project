from pathlib import Path

from streamlit.testing.v1 import AppTest


def _checkbox(app: AppTest, label: str):
    return next(item for item in app.checkbox if item.label == label)


def test_data_generation_ui_runs_offline_end_to_end() -> None:
    app_path = Path(__file__).parents[1] / "app.py"
    app = AppTest.from_file(app_path, default_timeout=10).run()
    assert not app.exception
    assert app.title[0].value == "Data Generation"

    _checkbox(app, "Save to PostgreSQL").uncheck()
    next(button for button in app.button if button.label == "Generate").click()
    app.run()

    assert not app.exception
    assert any("generated and validated" in message.value for message in app.success)
    assert [metric.value for metric in app.metric[:3]] == ["4", "400", "Passed"]
    assert {button.label for button in app.download_button} == {
        "Download table CSV",
        "Download complete ZIP",
    }
