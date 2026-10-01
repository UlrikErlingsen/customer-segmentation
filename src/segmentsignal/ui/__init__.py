"""Segment Signal user interface: the Signal Hub entry point.

The only package under ``segmentsignal`` that imports Streamlit or Plotly. ``render()`` draws the whole app on the
current page and never calls ``st.set_page_config``; the standalone ``app.py`` or Signal Hub owns the page config.
"""

from segmentsignal import __version__
from segmentsignal.ui import signal_theme
from segmentsignal.ui.app import render

APP_INFO = {"product": "Segment Signal", "version": __version__, "repo": "customer-segmentation", "slug": "segment"}

__all__ = ["APP_INFO", "render", "signal_theme"]
