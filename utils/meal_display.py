"""Meal DataFrames for Streamlit tables (shared sorting — mirrors transactions_display)."""

from __future__ import annotations

import pandas as pd

from utils.constants import MEAL_COLUMNS

DISPLAY_ORDER = MEAL_COLUMNS


def prepare_meals_display_df(df: pd.DataFrame, *, sort_mode: str) -> pd.DataFrame:
    """Return a display-ready copy sorted like Past Transactions.

    ``sort_mode``:
    - ``logged_then_date``: newest by LOGGED_AT, then MEAL_DATE.
    - ``date_then_logged``: newest by MEAL_DATE, then LOGGED_AT.
    """
    if df.empty:
        return pd.DataFrame(columns=MEAL_COLUMNS)

    df_display = df.copy()
    df_display["MEAL_DATE"] = pd.to_datetime(df_display.get("MEAL_DATE"), errors="coerce").dt.strftime("%Y-%m-%d")
    if "LOGGED_AT" in df_display.columns:
        logged = pd.to_datetime(df_display["LOGGED_AT"], errors="coerce")
        df_display["LOGGED_AT"] = logged.dt.strftime("%Y-%m-%d %H:%M:%S").fillna("")
    else:
        df_display["LOGGED_AT"] = ""

    text_cols = {"MEAL_NAME", "SERVING_SIZE", "SOURCE", "MEAL_DATE", "LOGGED_AT", "CATEGORY", "SUBCATEGORY", "BRAND", "COMMENTS"}
    num_cols = [c for c in MEAL_COLUMNS if c not in text_cols]
    for col in MEAL_COLUMNS:
        if col not in df_display.columns:
            df_display[col] = "" if col in {"MEAL_NAME", "SERVING_SIZE", "SOURCE", "CATEGORY", "SUBCATEGORY", "BRAND", "COMMENTS"} else 0
    for col in num_cols:
        if col in df_display.columns:
            df_display[col] = pd.to_numeric(df_display[col], errors="coerce").fillna(0)
    for col in MEAL_COLUMNS:
        if col in df_display.columns and col in text_cols:
            df_display[col] = df_display[col].fillna("").astype(str)

    sort_df = df_display.copy()
    sort_df["_sort_meal_date"] = pd.to_datetime(sort_df["MEAL_DATE"], errors="coerce")
    sort_df["_sort_logged"] = pd.to_datetime(sort_df["LOGGED_AT"], errors="coerce")

    if sort_mode == "logged_then_date":
        sort_df = sort_df.sort_values(
            by=["_sort_logged", "_sort_meal_date"],
            ascending=[False, False],
            na_position="last",
        )
    elif sort_mode == "date_then_logged":
        sort_df = sort_df.sort_values(
            by=["_sort_meal_date", "_sort_logged"],
            ascending=[False, False],
            na_position="last",
        )
    else:
        raise ValueError(f"Unknown sort_mode: {sort_mode!r}")

    out = sort_df.drop(columns=["_sort_meal_date", "_sort_logged"])
    return out[[c for c in DISPLAY_ORDER if c in out.columns]]
