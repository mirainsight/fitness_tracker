"""Shared app helpers."""

from pathlib import Path

import streamlit as st


def load_maincss(file_path: str) -> None:
    p = Path(file_path)
    if not p.exists():
        return
    st.markdown(f"<style>{p.read_text()}</style>", unsafe_allow_html=True)
