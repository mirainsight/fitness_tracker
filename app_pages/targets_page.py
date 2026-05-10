"""Daily nutrition targets (budget plan analogue)."""

import pandas as pd
import streamlit as st

from utils.app_utils import load_maincss
from utils.constants import paths
from utils.meal_streamlit_cache import cached_load_meals
from utils.target_storage import force_sync_targets_to_gsheets, load_targets, save_targets

load_maincss(paths["maincss"])

st.title("Daily targets")
st.caption("Set daily goals. Compare against **today’s logged meals** below.")

data = load_targets()

with st.form("targets_form"):
    st.markdown("**Intake targets**")
    cals = st.number_input("Calories (kcal)", min_value=0.0, value=float(data["calories_kcal"]), step=50.0)
    prot = st.number_input("Protein (g)", min_value=0.0, value=float(data["protein_g"]), step=5.0)
    carb = st.number_input("Carbohydrates (g)", min_value=0.0, value=float(data["carbohydrates_g"]), step=5.0)
    fat = st.number_input("Fat (g)", min_value=0.0, value=float(data["fat_g"]), step=1.0)
    fiber = st.number_input("Fiber (g)", min_value=0.0, value=float(data["fiber_g"]), step=1.0)
    sodium_max = st.number_input("Sodium ceiling (mg)", min_value=0.0, value=float(data["sodium_mg_max"]), step=50.0)
    st.markdown("**Calories burned baseline**")
    base_burned = st.number_input(
        "Base calories burned / day (just living — TDEE without exercise)",
        min_value=0.0,
        value=float(data.get("base_calories_burned") or 0),
        step=50.0,
        help="Resting / baseline daily burn before any logged exercise. Used in the dashboard intake vs burned chart.",
    )
    submitted = st.form_submit_button("Save targets")

if submitted:
    new_data = {
        "calories_kcal": cals,
        "protein_g": prot,
        "carbohydrates_g": carb,
        "fat_g": fat,
        "fiber_g": fiber,
        "sodium_mg_max": sodium_max,
        "base_calories_burned": base_burned,
    }
    save_targets(new_data)
    st.success("Targets saved.")

st.divider()
st.subheader("Today vs targets")

df = cached_load_meals()
today = pd.Timestamp.now(tz=None).normalize()
if df.empty or "MEAL_DATE" not in df.columns:
    st.info("Log meals to see progress here.")
else:
    df = df.copy()
    df["_d"] = pd.to_datetime(df["MEAL_DATE"], errors="coerce").dt.normalize()
    today_df = df[df["_d"] == today]
    if today_df.empty:
        st.warning("No meals logged for today yet.")
    else:
        def _sum(col):
            return pd.to_numeric(today_df[col], errors="coerce").fillna(0).sum()

        t = data
        metrics = [
            ("Calories (kcal)", _sum("CALORIES_KCAL"), t["calories_kcal"], False),
            ("Protein (g)", _sum("PROTEIN_G"), t["protein_g"], False),
            ("Carbs (g)", _sum("CARBOHYDRATES_G"), t["carbohydrates_g"], False),
            ("Fat (g)", _sum("FAT_G"), t["fat_g"], False),
            ("Fiber (g)", _sum("FIBER_G"), t["fiber_g"], False),
            ("Sodium (mg)", _sum("SODIUM_MG"), t["sodium_mg_max"], True),
        ]
        for label, actual, target, inverse in metrics:
            if target <= 0:
                continue
            ratio = actual / target
            if inverse:
                st.markdown(f"**{label}** — {actual:.0f} / {target:.0f} (stay under)")
                st.progress(min(1.0, ratio))
            else:
                st.markdown(f"**{label}** — {actual:.0f} / {target:.0f} ({100 * ratio:.0f}%)")
                st.progress(min(1.0, ratio))

st.divider()
if st.button("Sync targets JSON → Google Sheets (Misc!A1)"):
    ok, msg = force_sync_targets_to_gsheets(load_targets())
    (st.success if ok else st.error)(msg)
