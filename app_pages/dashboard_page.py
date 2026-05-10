"""Fitness dashboard: intake trends, macros, and targets (dashboard analogue)."""

from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from utils.app_utils import load_maincss
from utils.constants import paths
from utils.meal_streamlit_cache import cached_load_meals
from utils.target_storage import load_targets

load_maincss(paths["maincss"])

st.title("Dashboard")

df = cached_load_meals()
targets = load_targets()

if df.empty:
    st.info("No data yet. Add meals on **Log meal**.")
    st.stop()

df = df.copy()
df["MEAL_DATE"] = pd.to_datetime(df["MEAL_DATE"], errors="coerce")
df = df.dropna(subset=["MEAL_DATE"])
for c in ["CALORIES_KCAL", "PROTEIN_G", "CARBOHYDRATES_G", "FAT_G", "FIBER_G", "SUGAR_G", "SODIUM_MG"]:
    if c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

dmin, dmax = df["MEAL_DATE"].min().date(), df["MEAL_DATE"].max().date()
default_start = max(dmin, dmax - timedelta(days=30))
col_a, col_b = st.columns(2)
with col_a:
    start = st.date_input("From", value=default_start, min_value=dmin, max_value=dmax)
with col_b:
    end = st.date_input("To", value=dmax, min_value=dmin, max_value=dmax)

mask = (df["MEAL_DATE"].dt.date >= start) & (df["MEAL_DATE"].dt.date <= end)
d = df.loc[mask]
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
total_kcal = float(d["CALORIES_KCAL"].sum())
avg_kcal = total_kcal / n_days
total_protein = float(d["PROTEIN_G"].sum())

st.subheader("At a glance")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Total kcal (range)", f"{total_kcal:,.0f}")
m2.metric("Avg kcal / day", f"{avg_kcal:,.0f}")
m3.metric("Total protein (g)", f"{total_protein:,.0f}")
m4.metric("Logged meals", f"{len(d):,}")

st.divider()
st.subheader("Energy trend")
fig_line = px.line(
    daily,
    x="date",
    y="calories",
    markers=True,
    labels={"calories": "kcal", "date": ""},
)
if targets.get("calories_kcal"):
    fig_line.add_hline(
        y=float(targets["calories_kcal"]),
        line_dash="dash",
        line_color="rgba(255,140,0,0.8)",
        annotation_text="Daily kcal target",
    )
st.plotly_chart(fig_line, use_container_width=True)

left, right = st.columns(2)
with left:
    st.markdown("**Macro grams per day**")
    fig_stack = go.Figure(
        data=[
            go.Bar(name="Protein", x=daily["date"], y=daily["protein_g"], marker_color="#2E86AB"),
            go.Bar(name="Carbs", x=daily["date"], y=daily["carbohydrates_g"], marker_color="#A23B72"),
            go.Bar(name="Fat", x=daily["date"], y=daily["fat_g"], marker_color="#F18F01"),
        ]
    )
    fig_stack.update_layout(barmode="group", legend=dict(orientation="h", yanchor="bottom", y=1.02), margin=dict(t=30, b=40), yaxis_title="g")
    st.plotly_chart(fig_stack, use_container_width=True)

with right:
    st.markdown("**% of calories from each macro** (range total)")
    p_kcal = 4 * float(d["PROTEIN_G"].sum())
    c_kcal = 4 * float(d["CARBOHYDRATES_G"].sum())
    f_kcal = 9 * float(d["FAT_G"].sum())
    denom = p_kcal + c_kcal + f_kcal
    if denom <= 0:
        st.caption("Not enough macro data for a split.")
    else:
        pie = px.pie(
            names=["Protein", "Carbohydrates", "Fat"],
            values=[p_kcal / denom, c_kcal / denom, f_kcal / denom],
            hole=0.45,
            color_discrete_sequence=["#2E86AB", "#A23B72", "#F18F01"],
        )
        st.plotly_chart(pie, use_container_width=True)

st.divider()
if "CATEGORY" in d.columns:
    st.subheader("By food category")
    dc = d.assign(_cat=d["CATEGORY"].fillna("").astype(str).str.strip().replace("", "(blank)"))
    by_cat = (
        dc.groupby("_cat", as_index=False)
        .agg(kcal=("CALORIES_KCAL", "sum"))
        .sort_values("kcal", ascending=False)
    )
    fig_cat = px.bar(by_cat, x="_cat", y="kcal", labels={"kcal": "kcal", "_cat": "Category"})
    st.plotly_chart(fig_cat, use_container_width=True)
    st.divider()

st.subheader("Where the calories come from")
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
st.subheader("Targets snapshot (daily goals vs range average)")
t_cal = float(targets.get("calories_kcal") or 0)
t_p = float(targets.get("protein_g") or 0)
c1, c2, c3 = st.columns(3)
if t_cal > 0:
    c1.metric("Avg kcal / day vs target", f"{avg_kcal:.0f} / {t_cal:.0f}", delta=f"{avg_kcal - t_cal:+.0f}")
if t_p > 0:
    avg_p = float(d["PROTEIN_G"].sum()) / n_days
    c2.metric("Avg protein vs target (g)", f"{avg_p:.1f} / {t_p:.1f}", delta=f"{avg_p - t_p:+.1f}")
avg_sodium = float(d["SODIUM_MG"].sum()) / n_days if "SODIUM_MG" in d.columns else 0
t_na = float(targets.get("sodium_mg_max") or 0)
if t_na > 0:
    c3.metric("Avg sodium vs ceiling (mg)", f"{avg_sodium:.0f} / {t_na:.0f}", delta=f"{avg_sodium - t_na:+.0f}")
