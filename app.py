"""Segment Signal standalone entry point."""

import os

# pyarrow's bundled mimalloc allocator can segfault on macOS when Streamlit
# serializes tables from a worker thread; the system allocator is stable.
# Must be set before Arrow creates its default memory pool.
os.environ.setdefault("ARROW_DEFAULT_MEMORY_POOL", "system")

from pathlib import Path
import sys

import streamlit as st

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from segmentsignal.ui import render, signal_theme as sig  # noqa: E402

st.set_page_config(**sig.page_config("segment"))
render()
