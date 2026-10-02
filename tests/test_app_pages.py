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


def _clear_session(app):
    next(button for button in app.sidebar.button if button.label == "Clear session data").click().run()
    assert app.session_state["segment:tables"] is None


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders_with_the_preloaded_demo(page):
    app = AppTest.from_file(APP, default_timeout=30)
    app.run()
    app.sidebar.radio[0].set_value(page).run()
    assert not app.exception, [error.value for error in app.exception]


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders_without_data(page):
    app = AppTest.from_file(APP, default_timeout=30)
    app.run()
    _clear_session(app)
    app.sidebar.radio[0].set_value(page).run()
    assert not app.exception, [error.value for error in app.exception]


def test_first_run_preloads_the_fictional_behavior_demo():
    app = AppTest.from_file(APP, default_timeout=30)
    app.run()
    assert not app.exception, [error.value for error in app.exception]
    assert app.sidebar.radio[0].value == "Welcome"
    assert app.session_state["segment:source_name"] == "demo_customers.csv"
    assert app.session_state["segment:grain_hint"] == "customer"
    body = "\n".join(str(item.value) for item in app.markdown)
    assert "fictional behavior-table demo is already loaded" in body
    assert any("demo_customers.csv · 600 rows" in str(caption.value) for caption in app.sidebar.caption)

    app.sidebar.radio[0].set_value("1 · Data & purpose").run()
    assert not app.exception, [error.value for error in app.exception]
    assert any(metric.label == "Rows" and metric.value == "600" for metric in app.metric)
    assert any(button.label == "Save this analysis setup" for button in app.button)


def test_cleared_session_stays_empty_and_demo_buttons_restore_it():
    app = AppTest.from_file(APP, default_timeout=30)
    app.run()
    _clear_session(app)
    app.run()
    assert app.session_state["segment:tables"] is None
    body = "\n".join(str(item.value) for item in app.markdown)
    assert "fictional behavior-table demo is already loaded" not in body
    next(button for button in app.sidebar.button if button.label == "Demo · behavior table").click().run()
    assert not app.exception, [error.value for error in app.exception]
    assert any(metric.label == "Rows" and metric.value == "600" for metric in app.metric)


def test_upload_replaces_the_preloaded_demo():
    from segmentsignal.examples import demo_csv_bytes

    app = AppTest.from_file(APP, default_timeout=30)
    app.run()
    assert app.session_state["segment:source_name"] == "demo_customers.csv"
    app.sidebar.file_uploader[0].set_value(("my_customers.csv", demo_csv_bytes("demo_needs_survey.csv"), "text/csv"))
    app.run()
    assert not app.exception, [error.value for error in app.exception]
    assert app.session_state["segment:source_name"] == "my_customers.csv"
    assert app.sidebar.radio[0].value == "1 · Data & purpose"
    assert any(metric.label == "Rows" and metric.value == "450" for metric in app.metric)
    app.run()
    assert app.session_state["segment:source_name"] == "my_customers.csv"


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
    assert app.session_state["segment:nav_target"] == "1 · Data & purpose"
    assert app.sidebar.radio[0].key == "segment:page"
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


def test_loading_a_second_demo_resets_data_dependent_controls():
    app = AppTest.from_file(APP, default_timeout=30)
    app.run()
    next(button for button in app.sidebar.button if button.label == "Demo · behavior table").click().run()
    assert any(button.label == "Save this analysis setup" for button in app.button)
    next(button for button in app.sidebar.button if button.label == "Demo · purchase log").click().run()
    assert not app.exception, [error.value for error in app.exception]
    grain = next(radio for radio in app.radio if radio.label == "What does one row represent?")
    assert grain.value == "Transaction log (many rows per customer)"
    assert any(button.label == "Build RFM features and save setup" for button in app.button)
