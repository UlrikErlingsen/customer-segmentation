"""The shared Signal shell, README information architecture and runtime scaffolding."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from segmentsignal import __version__


ROOT = Path(__file__).parents[1]
APP = str(ROOT / "app.py")
UI = ROOT / "src" / "segmentsignal" / "ui"


def test_shared_signal_shell_renders() -> None:
    app = AppTest.from_file(APP, default_timeout=60)
    app.run()

    assert not app.exception, [error.value for error in app.exception]
    body = "\n".join(str(item.value) for item in app.markdown)
    sidebar = "\n".join(str(item.value) for item in app.sidebar.markdown)
    assert "OPEN CUSTOMER SEGMENTATION" in body
    assert "B2C SEGMENTATION, WITHOUT THE BLACK BOX" in body
    assert "Treat segments as decision support, not discovered truth." in body
    assert f"Segment Signal v{__version__}" in body
    assert "Patterns, not discovered truth" in body
    assert "Part of the Signal suite" in body
    assert "AGPL-3.0-or-later" in body
    assert "sg-mast" in body  # the shared Signal masthead
    assert "sg-hero" in body  # the shared Signal hero
    assert "sg-foot" in body  # the shared Signal footer
    assert "Find the groups worth understanding." in sidebar
    assert "sg-side" in sidebar  # the shared Signal sidebar lockup


def test_app_uses_shared_signal_theme_instead_of_pasted_styles() -> None:
    standalone = (ROOT / "app.py").read_text(encoding="utf-8")
    ui_source = (UI / "app.py").read_text(encoding="utf-8")
    assert 'st.set_page_config(**sig.page_config("segment"))' in standalone
    assert "sig.apply(NS)" in ui_source
    assert "<style>" not in standalone + ui_source
    for old_colour in ("#173c3a", "#d95b40", "#83d2b4", "#f2c66d", "#17322e", "#102c2a", "#73837f"):
        assert old_colour not in (standalone + ui_source).lower()
    assert "SegmentSignal" not in ui_source  # display name has a space
    assert "st.plotly_chart(" not in ui_source  # charts go through sig.chart (template + theme=None)
    assert (UI / "assets" / "marks" / "segmentsignal-mark-64.png").exists()
    assert "friendly_message" in ui_source


def test_readme_matches_suite_information_architecture() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    # Signal README template order: readers find the same section in the same place in every repo.
    sections = [
        "## Read this first",
        "## Scope",
        "## Try the demo in three minutes",
        "## Data contract",
        "## Analysis contract",
        "## Methods",
        "## Decision statuses",
        "## Exports",
        "## Run locally",
        "## Privacy",
        "## No install? Give this file to an AI",
        "## Development",
        "## Where this fits in Signal",
        "## References",
        "## Originality and license",
    ]
    positions = [readme.find(f"\n{heading}\n") for heading in sections]
    assert all(position >= 0 for position in positions), dict(zip(sections, positions, strict=True))
    assert positions == sorted(positions)
    assert readme.startswith('<p align="center">\n  <img src="assets/segmentsignal-banner.png"')
    assert "assets/segmentsignal-banner.svg" not in readme
    assert "Signal-Customer-aa5d83" in readme  # family badge in the Customer 600 colour
    assert "github.com/UlrikErlingsen/customer-segmentation/actions" in readme  # tests badge
    assert "**Segment Signal**" in readme
    assert '<img src="assets/segmentsignal-mark-64.png"' in readme  # suite footer
    assert "Creator Signal" not in readme
    assert "Treat segments as decision support, not discovered truth." in readme
    assert "“no reliable segmentation found.”" in readme
    for path in ("assets/segmentsignal-banner.png", "assets/segmentsignal-mark-64.png", "assets/segmentsignal-social.png"):
        assert (ROOT / path).exists()
    assert not (ROOT / "assets" / "segmentsignal-banner.svg").exists()


def test_runtime_scaffolding_is_private_and_health_checked() -> None:
    config = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    launcher = (ROOT / "run_app.command").read_text(encoding="utf-8")

    assert "gatherUsageStats = false" in config
    assert 'base = "light"' in config
    assert 'primaryColor = "#aa5d83"' in config  # Signal Customer family, 600 step
    assert "USER segmentsignal" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "--browser.gatherUsageStats=false" in launcher
    assert "SEGMENTSIGNAL_PORT" in launcher
    assert "Segment Signal is ready" in launcher
