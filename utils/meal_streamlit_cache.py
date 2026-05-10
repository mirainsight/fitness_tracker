"""Streamlit cache helpers for meal tables (same discipline as finance-dashboard tx_streamlit_cache).

- ``cached_load_meals`` reads from session_state once per session; invalidated on save.
- Derived lists and prepared frames use ``@st.cache_data`` with explicit invalidation on save.
- ``preload_upstash_session_caches`` batch-fetches all hot keys in one mget round-trip so
  inference and page loads are instant after the first render.
"""

from __future__ import annotations

import hashlib
import json
from io import StringIO

import pandas as pd
import streamlit as st

from utils.meal_storage import load_meals
from utils.meal_display import prepare_meals_display_df

_MAX_MEAL_NAMES_DROPDOWN = 500
_MAX_MEAL_NAMES_FROM_RECENT = 400

_MEALS_SESSION_KEY = "_fitness_meals_cache"


def preload_upstash_session_caches() -> None:
    """Batch-fetch meals + learned mappings + food data in one mget round-trip.

    Populates all session-state caches so subsequent loads return immediately
    without extra network calls. Only fetches keys whose caches are cold.
    """
    from utils.upstash_storage import (
        batch_load_from_upstash,
        KEY_MEALS, KEY_MEAL_LEARNED, KEY_FOOD_MAPPINGS, KEY_FOOD_CATEGORIES,
        is_upstash_configured,
    )
    from utils.meal_name_inference import _CACHE_LEARNED, _CACHE_EFFECTIVE_SUBS
    from utils.constants import DEFAULT_FOOD_SUBCATEGORIES

    if not is_upstash_configured():
        return

    meals_cold = st.session_state.get(_MEALS_SESSION_KEY) is None
    learned_cold = _CACHE_LEARNED not in st.session_state
    mappings_cold = "_fitness_food_mappings_session" not in st.session_state
    cats_cold = _CACHE_EFFECTIVE_SUBS not in st.session_state

    if not meals_cold and not learned_cold and not mappings_cold and not cats_cold:
        return  # All caches warm

    keys_to_fetch = []
    if meals_cold:
        keys_to_fetch.append(KEY_MEALS)
    if learned_cold:
        keys_to_fetch.append(KEY_MEAL_LEARNED)
    if mappings_cold:
        keys_to_fetch.append(KEY_FOOD_MAPPINGS)
    if cats_cold:
        keys_to_fetch.append(KEY_FOOD_CATEGORIES)

    results = batch_load_from_upstash(*keys_to_fetch)

    if meals_cold:
        raw = results.get(KEY_MEALS)
        if raw:
            try:
                from utils.meal_storage import _normalize_df
                df = pd.read_csv(StringIO(raw))
                st.session_state[_MEALS_SESSION_KEY] = _normalize_df(df)
            except Exception:
                pass

    if learned_cold:
        raw = results.get(KEY_MEAL_LEARNED)
        if raw:
            try:
                st.session_state[_CACHE_LEARNED] = json.loads(raw)
            except Exception:
                pass

    if mappings_cold:
        raw = results.get(KEY_FOOD_MAPPINGS)
        mappings: dict = {}
        if raw:
            try:
                mappings = json.loads(raw)
            except Exception:
                pass
        st.session_state["_fitness_food_mappings_session"] = mappings

    if cats_cold:
        raw = results.get(KEY_FOOD_CATEGORIES)
        user_cats: dict = {}
        if raw:
            try:
                user_cats = json.loads(raw)
            except Exception:
                pass
        # Pre-compute effective subcategories so inference is instant
        effective: dict = {}
        all_cats = set(DEFAULT_FOOD_SUBCATEGORIES.keys()) | set(user_cats.keys())
        for cat in sorted(all_cats):
            subs = list(DEFAULT_FOOD_SUBCATEGORIES.get(cat, []))
            for s in user_cats.get(cat, []):
                if s not in subs:
                    subs.append(s)
            effective[cat] = subs
        st.session_state[_CACHE_EFFECTIVE_SUBS] = effective


def meals_df_hash(df: pd.DataFrame) -> str:
    if df.empty:
        return "empty"
    hash_str = f"{len(df)}_{df.columns.tolist()}_{df.iloc[0].tolist() if len(df) > 0 else ''}"
    return hashlib.md5(hash_str.encode()).hexdigest()[:16]


def cached_load_meals() -> pd.DataFrame:
    """Read from Upstash once per session; re-fetch only after explicit invalidation (save).

    Using session_state avoids a live Upstash read on every Streamlit re-run (e.g. every
    keystroke, every dropdown change). Invalidate by calling invalidate_meal_caches(),
    which is called after save_meals().
    """
    cached = st.session_state.get(_MEALS_SESSION_KEY)
    if cached is not None:
        return cached
    df = load_meals()
    st.session_state[_MEALS_SESSION_KEY] = df
    return df


@st.cache_data(ttl=120, show_spinner=False)
def cached_get_meal_names_list(df_hash: str):
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
    from utils.food_mapping_storage import load_food_mappings_from_storage
    # Return session-preloaded mappings if available (warmed by preload_upstash_session_caches)
    session_mappings = st.session_state.get("_fitness_food_mappings_session")
    if session_mappings is not None:
        return session_mappings
    return load_food_mappings_from_storage()


def invalidate_food_mapping_caches() -> None:
    cached_food_mappings_dict.clear()
    st.session_state.pop("_fitness_food_mappings_session", None)


def invalidate_meal_caches() -> None:
    st.session_state.pop(_MEALS_SESSION_KEY, None)
    cached_get_meal_names_list.clear()
    cached_prepare_meals_display_df_logged.clear()
    cached_prepare_meals_display_df_by_meal_date.clear()
    st.session_state.pop("fitness_df_fetched", None)
