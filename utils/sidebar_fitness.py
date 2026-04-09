"""Sidebar monthly summary for fitness.

Mirrors ``display_sidebar_monthly_summary`` in
``finance-dashboard/utils/dashboard_utils.py`` (same timezone, same “always use
shared load path” idea so the sidebar never lags the ledger).
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st
from zoneinfo import ZoneInfo

from utils.meal_streamlit_cache import cached_load_meals
from utils.target_storage import load_targets

# Same default timezone as finance-dashboard monthly summary.
_SIDEBAR_TZ = ZoneInfo("Asia/Kuala_Lumpur")


def display_sidebar_monthly_fitness_summary() -> None:
    """At-a-glance nutrition metrics for the current calendar month in the sidebar."""
    with st.sidebar:
        st.caption("📊 This month")
        # Same loading path as Log meal / Past meals / Dashboard so the sidebar never lags the ledger.
        df = cached_load_meals()
        if df is None or df.empty or "MEAL_DATE" not in df.columns:
            st.caption("No meals logged yet. Use **Log meal** to add entries.")
            return

        df = df.copy()
        df["MEAL_DATE"] = pd.to_datetime(df["MEAL_DATE"], errors="coerce")
        df = df.dropna(subset=["MEAL_DATE"])
        if df.empty:
            st.caption("No meals with valid dates.")
            return

        for c in ("CALORIES_KCAL", "PROTEIN_G"):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

        now = dt.datetime.now(_SIDEBAR_TZ)
        month_mask = (df["MEAL_DATE"].dt.month == now.month) & (df["MEAL_DATE"].dt.year == now.year)
        month_df = df[month_mask]
        if month_df.empty:
            st.caption("No meals this month.")
            return

        total_kcal = float(month_df["CALORIES_KCAL"].sum()) if "CALORIES_KCAL" in month_df.columns else 0.0
        total_protein = float(month_df["PROTEIN_G"].sum()) if "PROTEIN_G" in month_df.columns else 0.0

        # Average kcal per calendar day spanned by logged data this month (same idea as avg daily spend span).
        d_min = month_df["MEAL_DATE"].min().date()
        d_max = month_df["MEAL_DATE"].max().date()
        month_end = now.date()
        clip_max = min(d_max, month_end)
        days = max(1, (clip_max - d_min).days + 1)
        avg_kcal = total_kcal / days

        st.metric("Total kcal", f"{total_kcal:,.0f}", help="Sum of kcal for meals dated this month")
        st.metric("Avg kcal / day", f"{avg_kcal:,.0f}", help=f"Total ÷ days from first logged day to today ({days} d)")
        st.metric("Total protein (g)", f"{total_protein:,.0f}", help="Protein sum this month")

        targets = load_targets()
        t_cal = float(targets.get("calories_kcal") or 0)
        if t_cal > 0:
            # Days from month start through today (cap to month end).
            month_start = now.date().replace(day=1)
            elapsed = max(1, (month_end - month_start).days + 1)
            budget_so_far = t_cal * elapsed
            pct = (total_kcal / budget_so_far * 100) if budget_so_far > 0 else 0
            st.metric(
                "Vs kcal target (MTD)",
                f"{pct:.0f}%",
                help=f"Month-to-date kcal vs {t_cal:.0f} kcal × {elapsed} days from month start",
            )

        if "CALORIES_KCAL" in month_df.columns and "MEAL_NAME" in month_df.columns:
            idx_max = month_df["CALORIES_KCAL"].idxmax()
            if pd.notna(idx_max):
                row = month_df.loc[idx_max]
                name = str(row.get("MEAL_NAME", ""))[:36]
                st.metric("Largest meal (kcal)", f"{float(row.get('CALORIES_KCAL', 0)):,.0f}", name or None)

        if "LOGGED_AT" in month_df.columns:
            sort_df = month_df.assign(
                _logged=pd.to_datetime(month_df["LOGGED_AT"], errors="coerce"),
            ).sort_values("_logged", ascending=False, na_position="last")
        else:
            sort_df = month_df.sort_values("MEAL_DATE", ascending=False)
        if not sort_df.empty:
            row = sort_df.iloc[0]
            desc = (str(row.get("MEAL_NAME", "")) or "")[:30]
            kcal = float(row.get("CALORIES_KCAL", 0) or 0)
            st.metric("Last logged meal", f"{kcal:,.0f} kcal", desc or None)
