"""Fitness dashboard: intake trends, macros, and targets."""

from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from utils.app_utils import load_maincss
from utils.constants import paths
from utils.exercise_storage import load_exercises
from utils.meal_streamlit_cache import cached_load_meals
from utils.target_storage import load_targets

load_maincss(paths["maincss"])
st.title("Dashboard")

df_raw = cached_load_meals()
ex_raw = load_exercises()
targets = load_targets()

if df_raw.empty:
    st.info("No data yet. Add meals on **Log meal**.")
    st.stop()

df_all = df_raw.copy()
df_all["MEAL_DATE"] = pd.to_datetime(df_all["MEAL_DATE"], errors="coerce")
df_all = df_all.dropna(subset=["MEAL_DATE"])

_NUM = ["CALORIES_KCAL", "PROTEIN_G", "CARBOHYDRATES_G", "FAT_G", "FIBER_G", "SUGAR_G", "SODIUM_MG"]
for c in _NUM:
    if c in df_all.columns:
        df_all[c] = pd.to_numeric(df_all[c], errors="coerce").fillna(0)

dmin = df_all["MEAL_DATE"].min().date()
dmax = df_all["MEAL_DATE"].max().date()
today = date.today()


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _months_back(n: int) -> date:
    m, y = today.month - n, today.year
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


def _resolve_preset(preset: str) -> tuple[date, date]:
    if preset == "This month":
        return _month_start(today), today
    if preset == "Last month":
        end = _month_start(today) - timedelta(days=1)
        return _month_start(end), end
    if preset == "Last 3 months":
        return _months_back(3), today
    if preset == "Last 6 months":
        return _months_back(6), today
    return dmin, dmax  # All time


# --- Time period selector ---
_PRESETS = ["This month", "Last month", "Last 3 months", "Last 6 months", "All time", "Custom"]
preset = st.segmented_control("Time period", _PRESETS, default="This month", key="dash_preset")
if preset is None:
    preset = "This month"

if preset == "Custom":
    col_a, col_b = st.columns(2)
    with col_a:
        start = st.date_input("From", value=max(dmin, dmax - timedelta(days=30)), min_value=dmin, max_value=dmax)
    with col_b:
        end = st.date_input("To", value=dmax, min_value=dmin, max_value=dmax)
else:
    start, end = _resolve_preset(preset)
    start = max(start, dmin)
    end = min(end, dmax)

mask = (df_all["MEAL_DATE"].dt.date >= start) & (df_all["MEAL_DATE"].dt.date <= end)
d = df_all.loc[mask].copy()

if d.empty:
    st.warning("No meals in this range.")
    st.stop()

d["_day"] = d["MEAL_DATE"].dt.date
daily = (
    d.groupby("_day", as_index=False)
    .agg(
        calories=("CALORIES_KCAL", "sum"),
        protein_g=("PROTEIN_G", "sum"),
        carbohydrates_g=("CARBOHYDRATES_G", "sum"),
        fat_g=("FAT_G", "sum"),
        fiber_g=("FIBER_G", "sum"),
        meals=("MEAL_NAME", "count"),
    )
    .sort_values("_day")
)
daily["date"] = pd.to_datetime(daily["_day"])

n_days = max(1, (end - start).days + 1)
avg_kcal = float(d["CALORIES_KCAL"].sum()) / n_days
avg_protein = float(d["PROTEIN_G"].sum()) / n_days
avg_carbs = float(d["CARBOHYDRATES_G"].sum()) / n_days
avg_fat = float(d["FAT_G"].sum()) / n_days
avg_sodium = float(d["SODIUM_MG"].sum()) / n_days if "SODIUM_MG" in d.columns else 0


def _period_avgs(s: date, e: date) -> dict:
    sub = df_all.loc[(df_all["MEAL_DATE"].dt.date >= s) & (df_all["MEAL_DATE"].dt.date <= e)]
    if sub.empty:
        return {}
    n = max(1, (e - s).days + 1)
    return {
        "Avg kcal/day": sub["CALORIES_KCAL"].sum() / n,
        "Avg protein (g)": sub["PROTEIN_G"].sum() / n,
        "Avg carbs (g)": sub["CARBOHYDRATES_G"].sum() / n,
        "Avg fat (g)": sub["FAT_G"].sum() / n,
        "Avg fiber (g)": sub["FIBER_G"].sum() / n,
        "Meals logged": float(len(sub)),
    }


this_m_start = _month_start(today)
last_m_end = this_m_start - timedelta(days=1)
last_m_start = _month_start(last_m_end)
three_m_start = _months_back(3)

this_m = _period_avgs(this_m_start, today)
last_m = _period_avgs(last_m_start, last_m_end)
three_m = _period_avgs(three_m_start, today)

_METRICS = ["Avg kcal/day", "Avg protein (g)", "Avg carbs (g)", "Avg fat (g)", "Avg fiber (g)", "Meals logged"]
this_label = today.strftime("This month (%b %Y)")
last_label = last_m_start.strftime("Last month (%b %Y)")


def _fmt(val, metric: str) -> str:
    if val is None:
        return "—"
    return f"{val:,.0f}" if metric == "Meals logged" else f"{val:,.1f}"


comp_rows = [
    {
        "Metric": m,
        this_label: _fmt(this_m.get(m), m),
        last_label: _fmt(last_m.get(m), m),
        "3-month avg": _fmt(three_m.get(m), m),
    }
    for m in _METRICS
]

# ── Section 1: At a glance ────────────────────────────────────────────────────
st.subheader("📊 At a glance")
t_cal = float(targets.get("calories_kcal") or 0)
t_p = float(targets.get("protein_g") or 0)
m1, m2, m3, m4 = st.columns(4)
m1.metric("Avg kcal / day", f"{avg_kcal:,.0f}", delta=f"{avg_kcal - t_cal:+.0f} vs target" if t_cal else None)
m2.metric("Avg protein / day (g)", f"{avg_protein:,.1f}", delta=f"{avg_protein - t_p:+.1f} vs target" if t_p else None)
m3.metric("Logged meals", f"{len(d):,}")
m4.metric("Days with data", f"{daily['_day'].nunique()} / {n_days}")

st.markdown("**This month · Last month · 3-month average**")
st.dataframe(pd.DataFrame(comp_rows), use_container_width=True, hide_index=True)

st.divider()

# ── Section 2: Intake vs burned ───────────────────────────────────────────────
st.subheader("⚡ Intake vs burned")

base_burned = float(targets.get("base_calories_burned") or 0)

# Build daily exercise burns
ex_daily: dict = {}
if not ex_raw.empty:
    ex = ex_raw.copy()
    ex["EXERCISE_DATE"] = pd.to_datetime(ex["EXERCISE_DATE"], errors="coerce").dt.date
    ex["CALORIES_BURNED"] = pd.to_numeric(ex["CALORIES_BURNED"], errors="coerce").fillna(0)
    ex = ex.loc[(ex["EXERCISE_DATE"] >= start) & (ex["EXERCISE_DATE"] <= end)]
    ex_daily = ex.groupby("EXERCISE_DATE")["CALORIES_BURNED"].sum().to_dict()

# Union of all dates in range that have either intake or exercise
all_dates = sorted(set(daily["_day"].tolist()) | set(ex_daily.keys()))

intake_vals = [float(daily.loc[daily["_day"] == day, "calories"].sum()) for day in all_dates]
burned_vals = [base_burned + ex_daily.get(day, 0) for day in all_dates]
date_labels = [pd.Timestamp(day) for day in all_dates]

fig_ivb = go.Figure()
fig_ivb.add_trace(go.Bar(name="Intake (kcal)", x=date_labels, y=intake_vals, marker_color="#2E86AB"))
fig_ivb.add_trace(go.Bar(name="Burned (kcal)", x=date_labels, y=burned_vals, marker_color="#E63946"))
fig_ivb.update_layout(
    barmode="group",
    legend=dict(orientation="h", yanchor="bottom", y=1.02),
    margin=dict(t=30, b=40),
    yaxis_title="kcal",
    xaxis_title="",
)
if base_burned == 0 and not ex_daily:
    st.caption("Set a base calories burned on **Daily targets** and log exercises on **Log meal** to see burned data.")
st.plotly_chart(fig_ivb, use_container_width=True)

st.divider()

# ── Section 3: Energy trend & heatmap ────────────────────────────────────────
st.subheader("🔥 Energy & calorie trend")

fig_line = px.line(daily, x="date", y="calories", markers=True, labels={"calories": "kcal", "date": ""})
if t_cal:
    fig_line.add_hline(y=t_cal, line_dash="dash", line_color="rgba(255,140,0,0.8)", annotation_text="Daily kcal target")
st.plotly_chart(fig_line, use_container_width=True)

# Calendar heatmap — rows = months, cols = day-of-month
st.markdown("**Daily calorie heatmap**")
hm = d.groupby("_day")["CALORIES_KCAL"].sum().reset_index()
hm["ym"] = pd.to_datetime(hm["_day"]).dt.strftime("%Y-%m")
hm["dom"] = pd.to_datetime(hm["_day"]).dt.day
pivot_hm = hm.pivot(index="ym", columns="dom", values="CALORIES_KCAL").sort_index()
for day_n in range(1, 32):
    if day_n not in pivot_hm.columns:
        pivot_hm[day_n] = None
pivot_hm = pivot_hm[[c for c in range(1, 32) if c in pivot_hm.columns]]
y_labels = [pd.to_datetime(ym + "-01").strftime("%b %Y") for ym in pivot_hm.index]

fig_hm = go.Figure(go.Heatmap(
    z=pivot_hm.values.tolist(),
    x=[str(c) for c in pivot_hm.columns],
    y=y_labels,
    colorscale="YlOrRd",
    hovertemplate="Day %{x}, %{y}<br>%{z:,.0f} kcal<extra></extra>",
    colorbar=dict(title="kcal", orientation="h", y=-0.4, len=0.7),
    xgap=2,
    ygap=2,
))
fig_hm.update_layout(
    height=max(200, 90 + len(pivot_hm) * 45),
    margin=dict(t=10, b=90, l=90, r=10),
    xaxis=dict(title="Day of month"),
)
st.plotly_chart(fig_hm, use_container_width=True)

st.divider()

# ── Section 3: Macro breakdown ────────────────────────────────────────────────
st.subheader("🥩 Macro breakdown")
left, right = st.columns(2)
with left:
    st.markdown("**Macro grams per day**")
    fig_stack = go.Figure(data=[
        go.Bar(name="Protein", x=daily["date"], y=daily["protein_g"], marker_color="#2E86AB"),
        go.Bar(name="Carbs", x=daily["date"], y=daily["carbohydrates_g"], marker_color="#A23B72"),
        go.Bar(name="Fat", x=daily["date"], y=daily["fat_g"], marker_color="#F18F01"),
    ])
    fig_stack.update_layout(
        barmode="group",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(t=30, b=40),
        yaxis_title="g",
    )
    st.plotly_chart(fig_stack, use_container_width=True)

with right:
    st.markdown("**% of calories from each macro**")
    p_kcal = 4 * float(d["PROTEIN_G"].sum())
    c_kcal = 4 * float(d["CARBOHYDRATES_G"].sum())
    f_kcal = 9 * float(d["FAT_G"].sum())
    denom = p_kcal + c_kcal + f_kcal
    if denom <= 0:
        st.caption("Not enough macro data.")
    else:
        pie = px.pie(
            names=["Protein", "Carbohydrates", "Fat"],
            values=[p_kcal / denom, c_kcal / denom, f_kcal / denom],
            hole=0.45,
            color_discrete_sequence=["#2E86AB", "#A23B72", "#F18F01"],
        )
        st.plotly_chart(pie, use_container_width=True)

st.divider()

# ── Section 4: Food categories ────────────────────────────────────────────────
if "CATEGORY" in d.columns:
    st.subheader("🍽️ By food category")
    dc = d.copy()
    dc["_cat"] = dc["CATEGORY"].fillna("").astype(str).str.strip()
    dc["_cat"] = dc["_cat"].replace("", "(Uncategorized)")

    by_cat = dc.groupby("_cat", as_index=False).agg(kcal=("CALORIES_KCAL", "sum")).sort_values("kcal", ascending=False)
    fig_cat = px.bar(by_cat, x="_cat", y="kcal", labels={"kcal": "kcal", "_cat": "Category"})
    st.plotly_chart(fig_cat, use_container_width=True)

    # Category × month heatmap
    st.markdown("**Calories by category & month**")
    dc["ym"] = dc["MEAL_DATE"].dt.strftime("%Y-%m")
    cat_month = dc.groupby(["_cat", "ym"])["CALORIES_KCAL"].sum().reset_index()
    cat_pivot = cat_month.pivot(index="_cat", columns="ym", values="CALORIES_KCAL").fillna(0)
    cat_pivot = cat_pivot[sorted(cat_pivot.columns)]
    cat_pivot = cat_pivot.loc[cat_pivot.sum(axis=1).sort_values(ascending=False).index]
    x_month_labels = [pd.to_datetime(ym + "-01").strftime("%b %Y") for ym in cat_pivot.columns]

    fig_cat_hm = go.Figure(go.Heatmap(
        z=cat_pivot.values.tolist(),
        x=x_month_labels,
        y=cat_pivot.index.tolist(),
        colorscale=[[0, "#fff7ed"], [1, "#7c2d12"]],
        hovertemplate="%{y}<br>%{x}<br>%{z:,.0f} kcal<extra></extra>",
        colorbar=dict(title="kcal", orientation="h", y=-0.4, len=0.7),
        xgap=2,
        ygap=2,
    ))
    fig_cat_hm.update_layout(
        height=max(200, 90 + len(cat_pivot) * 40),
        margin=dict(t=10, b=90, l=160, r=10),
    )
    st.plotly_chart(fig_cat_hm, use_container_width=True)
    st.divider()

# ── Section 5: Top meals ──────────────────────────────────────────────────────
st.subheader("🍳 Where the calories come from")
top = (
    d.groupby("MEAL_NAME", as_index=False)
    .agg(kcal=("CALORIES_KCAL", "sum"), n=("MEAL_NAME", "count"))
    .sort_values("kcal", ascending=False)
    .head(15)
)
fig_bar = px.bar(top, x="kcal", y="MEAL_NAME", orientation="h", labels={"kcal": "kcal", "MEAL_NAME": ""})
fig_bar.update_layout(yaxis={"categoryorder": "total ascending"})
st.plotly_chart(fig_bar, use_container_width=True)

st.divider()

# ── Section 6: Monthly summary ────────────────────────────────────────────────
st.subheader("📅 Monthly summary")
df_all["ym"] = df_all["MEAL_DATE"].dt.strftime("%Y-%m")
monthly_rows = []
for ym, grp in df_all.groupby("ym"):
    n_d = max(1, grp["MEAL_DATE"].dt.date.nunique())
    monthly_rows.append({
        "Month": pd.to_datetime(ym + "-01").strftime("%b %Y"),
        "Avg kcal/day": round(grp["CALORIES_KCAL"].sum() / n_d, 1),
        "Avg protein (g)": round(grp["PROTEIN_G"].sum() / n_d, 1),
        "Avg carbs (g)": round(grp["CARBOHYDRATES_G"].sum() / n_d, 1),
        "Avg fat (g)": round(grp["FAT_G"].sum() / n_d, 1),
        "Meals": len(grp),
        "_ym": ym,
    })
monthly_df = pd.DataFrame(monthly_rows).sort_values("_ym", ascending=False).drop(columns="_ym")
st.dataframe(monthly_df, use_container_width=True, hide_index=True)

st.divider()

# ── Section 7: Targets snapshot ───────────────────────────────────────────────
st.subheader("🎯 Targets snapshot")
t_na = float(targets.get("sodium_mg_max") or 0)
c1, c2, c3 = st.columns(3)
if t_cal:
    c1.metric("Avg kcal / day vs target", f"{avg_kcal:.0f} / {t_cal:.0f}", delta=f"{avg_kcal - t_cal:+.0f}")
if t_p:
    c2.metric("Avg protein vs target (g)", f"{avg_protein:.1f} / {t_p:.1f}", delta=f"{avg_protein - t_p:+.1f}")
if t_na:
    c3.metric("Avg sodium vs ceiling (mg)", f"{avg_sodium:.0f} / {t_na:.0f}", delta=f"{avg_sodium - t_na:+.0f}")
