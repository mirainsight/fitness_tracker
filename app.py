"""Fitness tracker — Streamlit entry (Upstash + Google Sheets, like finance-dashboard)."""

import streamlit as st

from utils.app_utils import load_maincss
from utils.constants import paths
from utils.meal_storage import get_storage_backend
from utils.sidebar_fitness import display_sidebar_monthly_fitness_summary

st.set_page_config(page_title="Fitness tracker", layout="wide")
load_maincss(paths["maincss"])

# Same pattern as finance-dashboard ``app.py``: monthly summary in the sidebar for every page.
display_sidebar_monthly_fitness_summary()
st.sidebar.divider()
st.sidebar.caption(f"Storage: `{get_storage_backend()}`")

log_meal = st.Page(
    "app_pages/log_meal_page.py",
    title="Log meal",
    icon=":material/restaurant:",
    url_path="log_meal",
)
past_meals = st.Page(
    "app_pages/past_meals_page.py",
    title="Past meals",
    icon=":material/history:",
    url_path="past_meals",
)
dashboard = st.Page(
    "app_pages/dashboard_page.py",
    title="Dashboard",
    icon=":material/bar_chart_4_bars:",
    url_path="dashboard",
)
targets = st.Page(
    "app_pages/targets_page.py",
    title="Daily targets",
    icon=":material/track_changes:",
    url_path="targets",
)

pg = st.navigation([log_meal, past_meals, dashboard, targets])
pg.run()
