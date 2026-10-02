"""Signal Hub contract: importable UI entry point, Streamlit only under ui/, slug-namespaced state."""

import ast
from pathlib import Path
import re
import shutil
import subprocess
import sys

from streamlit.testing.v1 import AppTest

from segmentsignal import __version__


ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "src" / "segmentsignal"
UI = PACKAGE / "ui"
UI_ONLY_LIBRARIES = {"streamlit", "plotly"}
PAGES = [
    "Welcome",
    "1 · Data & purpose",
    "2 · Compare solutions",
    "3 · Profiles & export",
    "Methods & limits",
]
RENDER_SCRIPT = """
from segmentsignal.ui import render

render()
"""


def _imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def _widgets(app: AppTest) -> list:
    return [
        *app.radio, *app.selectbox, *app.multiselect, *app.checkbox, *app.toggle, *app.slider,
        *app.number_input, *app.date_input, *app.button,
    ]


def _assert_namespaced(app: AppTest) -> None:
    assert not app.exception, [error.value for error in app.exception]
    widgets = _widgets(app)
    assert widgets
    unkeyed = [(type(widget).__name__, widget.label) for widget in widgets if widget.key is None]
    assert not unkeyed, unkeyed
    foreign = [widget.key for widget in widgets if not widget.key.startswith("segment:")]
    assert not foreign, foreign


def _button(app: AppTest, label: str, *, sidebar: bool = False):
    buttons = app.sidebar.button if sidebar else app.button
    return next(button for button in buttons if button.label == label)


def test_ui_entry_point_matches_the_hub_contract() -> None:
    from segmentsignal.ui import APP_INFO, render

    assert callable(render)
    assert APP_INFO == {
        "product": "Segment Signal",
        "version": __version__,
        "repo": "customer-segmentation",
        "slug": "segment",
    }


def test_only_the_ui_package_imports_streamlit_or_plotly() -> None:
    offenders = {
        str(path.relative_to(PACKAGE)): sorted(_imported_roots(path) & UI_ONLY_LIBRARIES)
        for path in PACKAGE.rglob("*.py")
        if UI not in path.parents and _imported_roots(path) & UI_ONLY_LIBRARIES
    }
    assert not offenders, offenders


def test_core_package_imports_without_streamlit_or_plotly() -> None:
    # A fresh interpreter, so modules already imported by other tests cannot hide a stray import.
    code = (
        f"import sys\nsys.path.insert(0, {str(ROOT / 'src')!r})\n"
        "import segmentsignal, segmentsignal.errors, segmentsignal.features, segmentsignal.io, "
        "segmentsignal.modeling, segmentsignal.preprocessing, segmentsignal.profiling, segmentsignal.validation\n"
        "loaded = sorted(name for name in ('streamlit', 'plotly') if name in sys.modules)\n"
        "assert not loaded, loaded\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr


def test_render_never_sets_page_config_or_navigation() -> None:
    for path in UI.glob("*.py"):
        if path.name == "signal_theme.py":
            continue
        source = path.read_text(encoding="utf-8")
        for call in ("st.set_page_config(", "st.navigation(", "st.Page("):
            assert call not in source, (path.name, call)


def test_render_runs_from_a_script_without_set_page_config() -> None:
    app = AppTest.from_string(RENDER_SCRIPT, default_timeout=120)
    app.run()

    assert not app.exception, [error.value for error in app.exception]
    assert app.sidebar.radio[0].key == "segment:page"
    assert "segment:nav_target" in app.session_state
    assert "nav_target" not in app.session_state
    body = "\n".join(str(item.value) for item in app.markdown)
    assert "B2C SEGMENTATION, WITHOUT THE BLACK BOX" in body
    assert f"Segment Signal v{__version__}" in body


def test_every_page_with_the_preloaded_demo_has_only_namespaced_widgets() -> None:
    app = AppTest.from_string(RENDER_SCRIPT, default_timeout=120)
    app.run()
    assert app.session_state["segment:source_name"] == "demo_customers.csv"
    for page in PAGES:
        app.sidebar.radio[0].set_value(page).run()
        _assert_namespaced(app)
        assert app.sidebar.radio[0].value == page


def test_every_page_without_data_has_only_namespaced_widgets() -> None:
    app = AppTest.from_string(RENDER_SCRIPT, default_timeout=120)
    app.run()
    _button(app, "Clear session data", sidebar=True).click().run()
    assert app.session_state["segment:tables"] is None
    for page in PAGES:
        app.sidebar.radio[0].set_value(page).run()
        _assert_namespaced(app)
        assert app.sidebar.radio[0].value == page


def test_full_workflow_keeps_every_widget_and_state_key_namespaced() -> None:
    app = AppTest.from_string(RENDER_SCRIPT, default_timeout=300)
    app.run()
    _assert_namespaced(app)

    _button(app, "Demo · behavior table", sidebar=True).click().run()
    assert app.sidebar.radio[0].value == "1 · Data & purpose"
    _assert_namespaced(app)
    _button(app, "Save this analysis setup").click().run()
    _assert_namespaced(app)
    assert "segment:setup" in app.session_state

    _button(app, "Continue to 2 · Compare solutions →").click().run()
    assert app.sidebar.radio[0].value == "2 · Compare solutions"
    _assert_namespaced(app)
    _button(app, "Run the comparison").click().run()
    _assert_namespaced(app)
    assert "segment:comparison" in app.session_state

    _button(app, "Create this segmentation").click().run()
    assert app.sidebar.radio[0].value == "3 · Profiles & export"
    _assert_namespaced(app)
    assert "segment:solution" in app.session_state

    for page in PAGES:
        app.sidebar.radio[0].set_value(page).run()
        _assert_namespaced(app)

    unprefixed = [key for key in list(app.session_state) if not str(key).startswith("segment:")]
    assert not unprefixed, unprefixed


def test_transaction_setup_widgets_are_namespaced() -> None:
    app = AppTest.from_string(RENDER_SCRIPT, default_timeout=120)
    app.run()
    _button(app, "Demo · purchase log", sidebar=True).click().run()
    _assert_namespaced(app)
    assert any(widget.label == "Analysis reference date" for widget in app.date_input)


def test_session_state_and_widget_keys_go_through_the_namespace_helper() -> None:
    source = (UI / "app.py").read_text(encoding="utf-8")
    state_keys = re.findall(r"session_state(?:\[|\.get\(|\.pop\(|\.setdefault\()\s*([^,\])]+)", source)
    widget_keys = re.findall(r"\bkey=([^,)\n]+)", source)
    assert state_keys and widget_keys
    assert all(key.startswith("k(") for key in state_keys), state_keys
    assert all(key.startswith("k(") for key in widget_keys), widget_keys
    assert 'NS = "segment"' in source


def test_demo_generators_match_the_committed_example_files() -> None:
    from segmentsignal.examples import DEMO_FILES, demo_csv_bytes

    for filename in DEMO_FILES:
        committed = (ROOT / "examples" / filename).read_bytes().replace(b"\r\n", b"\n")
        assert demo_csv_bytes(filename) == committed, filename


def test_ui_reads_no_files_outside_the_package() -> None:
    # Signal Hub installs the app from its release archive: only src/segmentsignal (and declared package data)
    # exists there, so nothing reachable from render() may read repo-root folders such as examples/ or docs/.
    for path in UI.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "parents[" not in source, path.name
        assert '"examples"' not in source and "'examples'" not in source, path.name


def test_render_and_every_demo_work_from_an_installed_copy_of_the_package(tmp_path: Path) -> None:
    site = tmp_path / "site"
    shutil.copytree(PACKAGE, site / "segmentsignal", ignore=shutil.ignore_patterns("__pycache__"))
    code = f"""
import sys
site = {str(site)!r}
sys.path.insert(0, site)
import segmentsignal
assert segmentsignal.__file__.startswith(site), segmentsignal.__file__
from streamlit.testing.v1 import AppTest

script = "import sys\\nsys.path.insert(0, " + repr(site) + ")\\nfrom segmentsignal.ui import render\\nrender()\\n"
for label, rows in (("Demo · behavior table", "600"), ("Demo · purchase log", "4,288"), ("Demo · needs survey", "450")):
    app = AppTest.from_string(script, default_timeout=120)
    app.run()
    assert not app.exception, [error.value for error in app.exception]
    next(button for button in app.sidebar.button if button.label == label).click().run()
    assert not app.exception, [error.value for error in app.exception]
    assert not app.error, [error.value for error in app.error]
    assert any(metric.label == "Rows" and metric.value == rows for metric in app.metric), label
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr
