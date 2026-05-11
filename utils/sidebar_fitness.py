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

from utils.exercise_storage import load_exercises
from utils.meal_streamlit_cache import cached_load_meals
from utils.target_storage import load_targets

# Same default timezone as finance-dashboard monthly summary.
_SIDEBAR_TZ = ZoneInfo("Asia/Kuala_Lumpur")


def display_sidebar_monthly_fitness_summary() -> None:
    """At-a-glance nutrition metrics for the current calendar month in the sidebar."""
    with st.sidebar:
        # --- Today's net calories ---
        now_tz = dt.datetime.now(_SIDEBAR_TZ)
        today = now_tz.date()

        _df_all = cached_load_meals()
        _today_intake = 0.0
        if _df_all is not None and not _df_all.empty and "MEAL_DATE" in _df_all.columns:
            _df_t = _df_all.copy()
            _df_t["MEAL_DATE"] = pd.to_datetime(_df_t["MEAL_DATE"], errors="coerce")
            _df_t["CALORIES_KCAL"] = pd.to_numeric(_df_t.get("CALORIES_KCAL", 0), errors="coerce").fillna(0)
            _today_intake = float(_df_t.loc[_df_t["MEAL_DATE"].dt.date == today, "CALORIES_KCAL"].sum())

        _targets = load_targets()
        _today_base = float(_targets.get("base_calories_burned") or 0)
        _today_ex = 0.0
        _ex_raw = load_exercises()
        if not _ex_raw.empty:
            _ex = _ex_raw.copy()
            _ex["EXERCISE_DATE"] = pd.to_datetime(_ex["EXERCISE_DATE"], errors="coerce").dt.date
            _ex["CALORIES_BURNED"] = pd.to_numeric(_ex["CALORIES_BURNED"], errors="coerce").fillna(0)
            _today_ex = float(_ex.loc[_ex["EXERCISE_DATE"] == today, "CALORIES_BURNED"].sum())
        _today_burned = _today_base + _today_ex
        _today_net = _today_intake - _today_burned

        if _today_burned > 0:
            if _today_net > 0:
                _bar_color, _bar_label = "#E63946", "Over"
            elif _today_net > -400:
                _bar_color, _bar_label = "#2dc653", "On track"
            else:
                _bar_color, _bar_label = "#2E86AB", "Well under"
            _bar_fill = min(100.0, _today_intake / _today_burned * 100)
            _net_str = f"net <strong style='color:{_bar_color}'>{_today_net:+,.0f} kcal</strong>"
        else:
            _bar_color, _bar_label = "#888", ""
            _bar_fill = min(100.0, _today_intake / 2000 * 100)
            _net_str = "no burned data set"

        _label_html = f"<span style='font-size:0.75rem;color:{_bar_color};font-weight:600;'>{_bar_label}</span>" if _bar_label else ""
        st.markdown(f"""
<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:3px;">
  <span style="font-size:0.82rem;font-weight:600;">Today</span>
  {_label_html}
</div>
<div style="font-size:1.6rem;font-weight:700;line-height:1.1;margin-bottom:1px;">
  {_today_intake:,.0f}&thinsp;<span style="font-size:0.85rem;font-weight:400;color:#aaa;">kcal in</span>
</div>
<div style="font-size:0.72rem;color:#888;margin-bottom:6px;">
  {_today_burned:,.0f} burned &middot; {_net_str}
</div>
<div style="background:#333;border-radius:4px;height:6px;width:100%;overflow:hidden;">
  <div style="background:{_bar_color};height:100%;width:{_bar_fill:.1f}%;border-radius:4px;"></div>
</div>
""", unsafe_allow_html=True)
        st.divider()

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

        if "CALORIES_KCAL" in df.columns:
            df["CALORIES_KCAL"] = pd.to_numeric(df["CALORIES_KCAL"], errors="coerce").fillna(0)

        now = dt.datetime.now(_SIDEBAR_TZ)
        month_mask = (df["MEAL_DATE"].dt.month == now.month) & (df["MEAL_DATE"].dt.year == now.year)
        month_df = df[month_mask]
        if month_df.empty:
            st.caption("No meals this month.")
            return

        total_kcal = float(month_df["CALORIES_KCAL"].sum()) if "CALORIES_KCAL" in month_df.columns else 0.0

        # Average kcal per calendar day spanned by logged data this month
        d_min = month_df["MEAL_DATE"].min().date()
        d_max = month_df["MEAL_DATE"].max().date()
        month_end = now.date()
        clip_max = min(d_max, month_end)
        days = max(1, (clip_max - d_min).days + 1)
        avg_kcal = total_kcal / days

        # Days on track this month
        _daily_m = (month_df.groupby(month_df["MEAL_DATE"].dt.date)["CALORIES_KCAL"].sum()
                    if "CALORIES_KCAL" in month_df.columns else pd.Series(dtype=float))
        _logged_days_m = len(_daily_m)
        _base_b = float(_targets.get("base_calories_burned") or 0)
        _ex_by_day_m: dict = {}
        if not _ex_raw.empty:
            _ex_m = _ex_raw.copy()
            _ex_m["EXERCISE_DATE"] = pd.to_datetime(_ex_m["EXERCISE_DATE"], errors="coerce").dt.date
            _ex_m["CALORIES_BURNED"] = pd.to_numeric(_ex_m["CALORIES_BURNED"], errors="coerce").fillna(0)
            _ex_m = _ex_m[_ex_m["EXERCISE_DATE"].apply(lambda d: d.month == now.month and d.year == now.year)]
            _ex_by_day_m = _ex_m.groupby("EXERCISE_DATE")["CALORIES_BURNED"].sum().to_dict()

        t_cal = float(_targets.get("calories_kcal") or 0)
        if _base_b > 0 or _ex_by_day_m:
            _on_track_m = sum(
                1 for day, intake in _daily_m.items()
                if float(intake) <= _base_b + _ex_by_day_m.get(day, 0)
            )
            _otk_help = "Days this month where net kcal ≤ 0"
        elif t_cal > 0:
            _on_track_m = int((_daily_m <= t_cal).sum())
            _otk_help = f"Days where intake ≤ {t_cal:.0f} kcal target"
        else:
            _on_track_m, _otk_help = None, ""

        if _on_track_m is not None and _logged_days_m > 0:
            _otk_pct = _on_track_m / _logged_days_m * 100
            st.metric("Days on track", f"{_on_track_m} / {_logged_days_m}", f"{_otk_pct:.0f}%", help=_otk_help)

        st.metric("Avg kcal / day", f"{avg_kcal:,.0f}", help=f"Total ÷ days from first logged day to today ({days} d)")

        if t_cal > 0:
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
