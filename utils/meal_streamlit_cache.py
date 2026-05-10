"""Streamlit cache helpers for meal tables (same discipline as finance-dashboard tx_streamlit_cache).

- ``cached_load_meals`` is **not** wrapped in ``@st.cache_data`` so sidebar and ledger always
  read the latest Upstash/Sheets/CSV state (avoids stale workers).
- Derived lists and prepared frames use ``@st.cache_data`` with explicit invalidation on save.
"""

from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st

from utils.meal_storage import load_meals
from utils.meal_display import prepare_meals_display_df

# Large option lists slow Streamlit (see finance-dashboard transactions_page).
_MAX_MEAL_NAMES_DROPDOWN = 500
_MAX_MEAL_NAMES_FROM_RECENT = 400


def meals_df_hash(df: pd.DataFrame) -> str:
    """Stable short hash for cache keys (matches finance-dashboard transaction hash style)."""
    if df.empty:
        return "empty"
    hash_str = f"{len(df)}_{df.columns.tolist()}_{df.iloc[0].tolist() if len(df) > 0 else ''}"
    return hashlib.md5(hash_str.encode()).hexdigest()[:16]


def cached_load_meals() -> pd.DataFrame:
    """Always read from storage — do not ``@st.cache_data`` (see tx_streamlit_cache docstring)."""
    return load_meals()


@st.cache_data(ttl=120, show_spinner=False)
def cached_get_meal_names_list(df_hash: str):
    """Distinct meal names, recent-first then alphabetical (for template / quick entry)."""
    df = cached_load_meals()
    seen: dict[str, str] = {}

    def add(raw: str) -> None:
        t = (raw or "").strip()
        if not t:
            return
        k = t.casefold()
        if k not in seen:
            seen[k] = t

    if not df.empty and "MEAL_NAME" in df.columns:
        for name in reversed(df["MEAL_NAME"].dropna().astype(str).tolist()):
            add(name)
            if len(seen) >= _MAX_MEAL_NAMES_FROM_RECENT:
                break

    return sorted(seen.values())[:_MAX_MEAL_NAMES_DROPDOWN]


@st.cache_data(ttl=120, show_spinner=False)
def cached_prepare_meals_display_df_logged(df_hash: str) -> pd.DataFrame:
    return prepare_meals_display_df(cached_load_meals(), sort_mode="logged_then_date")


@st.cache_data(ttl=120, show_spinner=False)
def cached_prepare_meals_display_df_by_meal_date(df_hash: str) -> pd.DataFrame:
    return prepare_meals_display_df(cached_load_meals(), sort_mode="date_then_logged")


@st.cache_data(ttl=120, show_spinner=False)
def cached_food_mappings_dict() -> dict[str, list[str]]:
    """Sheet/Upstash food name → [category, subcategory]; TTL avoids hammering storage."""
    from utils.food_mapping_storage import load_food_mappings_from_storage

    return load_food_mappings_from_storage()


def invalidate_food_mapping_caches() -> None:
    cached_food_mappings_dict.clear()


def invalidate_meal_caches() -> None:
    cached_get_meal_names_list.clear()
    cached_prepare_meals_display_df_logged.clear()
    cached_prepare_meals_display_df_by_meal_date.clear()
    if hasattr(st, "session_state"):
        st.session_state.pop("fitness_df_fetched", None)
