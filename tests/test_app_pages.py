from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


APP = str(Path(__file__).parents[1] / "app.py")
PAGES = [
    "Welcome",
    "1 · Data & purpose",
    "2 · Compare solutions",
    "3 · Profiles & export",
    "Methods & limits",
]


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders_without_data(page):
    app = AppTest.from_file(APP, default_timeout=30)
    app.run()
    app.sidebar.radio[0].set_value(page).run()
    assert not app.exception, [error.value for error in app.exception]


def test_demo_customer_data_reaches_setup_page():
    app = AppTest.from_file(APP, default_timeout=30)
    app.run()
    demo = next(button for button in app.sidebar.button if button.label == "Demo · behavior table")
    demo.click().run()
    app.sidebar.radio[0].set_value("1 · Data & purpose").run()
    assert not app.exception, [error.value for error in app.exception]
    assert any(metric.label == "Rows" and metric.value == "600" for metric in app.metric)


def test_loading_a_demo_navigates_to_page_one_and_keeps_the_radio_in_sync():
    app = AppTest.from_file(APP, default_timeout=30)
    app.run()
    next(button for button in app.sidebar.button if button.label == "Demo · behavior table").click().run()
    assert app.sidebar.radio[0].value == "1 · Data & purpose"
    assert app.session_state["nav_target"] == "1 · Data & purpose"
    assert any(metric.label == "Rows" and metric.value == "600" for metric in app.metric)
    assert not app.exception, [error.value for error in app.exception]


def test_demo_transaction_data_reaches_rfm_setup():
    app = AppTest.from_file(APP, default_timeout=30)
    app.run()
    demo = next(button for button in app.sidebar.button if button.label == "Demo · purchase log")
    demo.click().run()
    app.sidebar.radio[0].set_value("1 · Data & purpose").run()
    assert not app.exception, [error.value for error in app.exception]
    assert any(metric.label == "Rows" and metric.value == "4,288" for metric in app.metric)
    assert any(button.label == "Build RFM features and save setup" for button in app.button)


def test_non_rfm_needs_demo_reaches_customer_setup():
    app = AppTest.from_file(APP, default_timeout=30)
    app.run()
    demo = next(button for button in app.sidebar.button if button.label == "Demo · needs survey")
    demo.click().run()
    app.sidebar.radio[0].set_value("1 · Data & purpose").run()
    assert not app.exception, [error.value for error in app.exception]
    assert any(metric.label == "Rows" and metric.value == "450" for metric in app.metric)
    selected_bases = app.multiselect[0].value
    assert "need_convenience" in selected_bases
    assert "price_sensitivity" in selected_bases


def test_specific_segment_count_above_eight_is_available():
    app = AppTest.from_file(APP, default_timeout=30)
    app.run()
    next(button for button in app.sidebar.button if button.label == "Demo · behavior table").click().run()
    app.sidebar.radio[0].set_value("1 · Data & purpose").run()
    next(button for button in app.button if button.label == "Save this analysis setup").click().run()
    app.sidebar.radio[0].set_value("2 · Compare solutions").run()
    count_mode = next(radio for radio in app.radio if radio.label == "How do you want to choose the number of segments?")
    count_mode.set_value("Test specific numbers").run()
    exact_counts = next(select for select in app.multiselect if select.label == "Exact segment counts to test")
    exact_counts.set_value([9]).run()
    assert exact_counts.value == [9]
    assert not app.exception, [error.value for error in app.exception]
