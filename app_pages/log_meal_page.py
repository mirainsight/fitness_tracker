"""Log meals from JSON + category / subcategory (finance-style mappings)."""

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from utils.app_utils import load_maincss
from utils.constants import paths
from utils.food_category_storage import (
    add_food_category,
    add_food_subcategory,
    get_effective_food_subcategories,
)
from utils.food_mapping_storage import force_load_food_mappings_from_gsheets, is_food_mappings_gsheets_configured
from utils.meal_schema import MealInput
from utils.meal_storage import (
    force_sync_to_gsheets,
    meal_input_to_row,
    meal_row_to_json_text,
    save_meals,
)
from utils.meal_name_inference import infer_meal_category, save_learned_mapping, delete_learned_mapping, invalidate_inference_cache
from utils.meal_streamlit_cache import (
    cached_food_mappings_dict,
    cached_get_meal_names_list,
    cached_load_meals,
    invalidate_meal_caches,
    meals_df_hash,
    preload_upstash_session_caches,
)
from utils.upstash_storage import get_last_gsheets_sync, save_last_gsheets_sync, test_upstash_connection

load_maincss(paths["maincss"])
preload_upstash_session_caches()


def _peek_meal_name(json_str: str) -> str:
    try:
        return str(json.loads(json_str).get("meal_name", "")).strip()
    except Exception:
        return ""


st.title("Log meal")
st.caption(
    "Nutrition JSON + **category / subcategory** (mapped from your sheet keywords, like finance transactions). "
    "JSON can include optional `category` / `subcategory` to override the pickers."
)

sample = """{
  "meal_name": "Grilled chicken rice bowl",
  "serving_size": "1 bowl",
  "calories_kcal": 520,
  "macronutrients": {
    "protein_g": 38,
    "carbohydrates_g": 45,
    "fat_g": 18,
    "fiber_g": 6,
    "sugar_g": 4
  },
  "micronutrients": {
    "sodium_mg": 640,
    "potassium_mg": 720,
    "calcium_mg": 80,
    "iron_mg": 3.1,
    "vitamin_c_mg": 12
  }
}"""

if "fitness_meal_json" not in st.session_state:
    st.session_state.fitness_meal_json = sample

with st.expander("Sample JSON"):
    st.code(
        "Estimate based on my meal in chat or picture given. Output in the following format\n\n" + sample,
        language="json",
    )

mappings = cached_food_mappings_dict()
effective = get_effective_food_subcategories()
categories = sorted(effective.keys())

meal_name_preview = _peek_meal_name(st.session_state.fitness_meal_json)
prev_peek = st.session_state.get("_fitness_meal_name_peek", "")
if meal_name_preview != prev_peek:
    st.session_state["_fitness_meal_name_peek"] = meal_name_preview
    inferred = infer_meal_category(meal_name_preview, mappings) if meal_name_preview else None
    st.session_state["_last_inferred_meal_result"] = inferred
    st.session_state.pop("fitness_log_cat", None)
    st.session_state.pop("fitness_log_sub", None)
    if inferred:
        _, (cat_inf, sub_inf) = inferred
        if cat_inf in categories:
            st.session_state["fitness_log_cat"] = cat_inf
            if sub_inf in effective.get(cat_inf, []):
                st.session_state["fitness_log_sub"] = sub_inf

if "fitness_log_cat" not in st.session_state:
    st.session_state.fitness_log_cat = categories[0] if categories else ""
cat = st.selectbox("Category", categories, key="fitness_log_cat")
subs = effective.get(cat, ["Other"])
if st.session_state.get("fitness_log_sub") not in subs:
    st.session_state.fitness_log_sub = subs[0] if subs else "Other"
sub_ix = subs.index(st.session_state.fitness_log_sub) if st.session_state.fitness_log_sub in subs else 0
sub = st.selectbox("Subcategory", subs, index=sub_ix, key="fitness_log_sub")

inferred = st.session_state.get("_last_inferred_meal_result")
if inferred:
    source, (cat_inf, sub_inf) = inferred
    source_label = {"learned": "saved", "word_scores": "similar", "sheet": "sheet"}.get(source, source)
    col_infer, col_forget = st.columns([3, 1])
    with col_infer:
        st.caption(f"✨ Inferred ({source_label}): **{cat_inf}** → **{sub_inf}**")
    with col_forget:
        if st.button("Wrong? Forget", key="forget_meal_inference", help="Clear saved mapping for this meal name"):
            delete_learned_mapping(meal_name_preview)
            invalidate_inference_cache()
            st.session_state["_last_inferred_meal_result"] = None
            st.session_state["_fitness_meal_name_peek"] = ""
            st.rerun()

with st.expander("Add taxonomy (optional)"):
    nc = st.text_input("New category name")
    if st.button("Add category") and nc:
        if add_food_category(nc):
            st.success("Added.")
            st.rerun()
        else:
            st.warning("Already exists or invalid.")
    ac = st.selectbox("Category", categories, key="fitness_add_sub_cat")
    ns = st.text_input("New subcategory")
    if st.button("Add subcategory") and ns:
        if add_food_subcategory(ac, ns):
            st.success("Added.")
            st.rerun()
        else:
            st.warning("Duplicate or invalid.")

df = cached_load_meals()
df_hash = meals_df_hash(df)
past_meal_names = cached_get_meal_names_list(df_hash)

tcol1, tcol2 = st.columns([4, 1])
with tcol1:
    template_name = st.selectbox(
        "Template from past meal (optional)",
        options=[""] + past_meal_names,
        key="fitness_meal_template",
        help="Most recent row with that meal name (includes category if saved).",
    )
with tcol2:
    st.write("")
    if st.button("Fill JSON from template", disabled=not bool(template_name)):
        m = df[df["MEAL_NAME"].astype(str).str.strip() == str(template_name).strip()]
        if not m.empty:
            m_sorted = m.assign(_lg=pd.to_datetime(m["LOGGED_AT"], errors="coerce")).sort_values(
                "_lg", ascending=False, na_position="last"
            )
            st.session_state.fitness_meal_json = meal_row_to_json_text(m_sorted.iloc[0])
            st.rerun()

with st.expander("Diagnostics"):
    if st.button("Test Upstash"):
        ok, msg = test_upstash_connection()
        (st.success if ok else st.error)(msg)

meal_date = st.date_input("Meal date", value=date.today())
st.text_area(
    "Meal JSON",
    height=280,
    placeholder="Paste JSON here…",
    key="fitness_meal_json",
)

add_meal = st.button("Add meal", type="primary")

if add_meal:
    try:
        meal = MealInput.model_validate_json(st.session_state.fitness_meal_json)
        jc = (meal.category or "").strip()
        js = (meal.subcategory or "").strip()
        if jc and js:
            res_cat, res_sub = jc, js
        else:
            res_cat = (st.session_state.get("fitness_log_cat") or "").strip()
            res_sub = (st.session_state.get("fitness_log_sub") or "").strip()
        if res_cat and not res_sub:
            res_sub = (effective.get(res_cat, ["Other"]) or ["Other"])[0]
        row = meal_input_to_row(meal, meal_date.isoformat(), category=res_cat, subcategory=res_sub)
        df_new = pd.concat([cached_load_meals(), pd.DataFrame([row])], ignore_index=True)
        save_meals(df_new)
        invalidate_meal_caches()
        if meal.meal_name and res_cat and res_sub:
            save_learned_mapping(meal.meal_name, res_cat, res_sub)
        st.session_state.fitness_meal_json = sample
        st.toast(f"Logged {meal.meal_name} — {meal.calories_kcal:.0f} kcal", icon="✅")
        st.rerun()
    except ValidationError as e:
        st.error("JSON does not match the expected meal schema.")
        st.json(e.errors())

df_rows = cached_load_meals()
st.divider()

with st.expander("Sync with Google Sheets"):
    st.markdown("Pushes meal log from Upstash → Sheets and reloads food mappings from Sheets → Upstash.")
    if st.button("Sync with Google Sheets"):
        df2 = cached_load_meals()
        ok1, msg1 = force_sync_to_gsheets(df2)
        if ok1:
            ts = datetime.now(ZoneInfo("Asia/Kuala_Lumpur")).strftime("%b %d, %Y %I:%M %p")
            save_last_gsheets_sync(ts)
            st.session_state["_fitness_last_gsheets_refresh"] = ts
            st.success("Meals synced to Google Sheets.")
        else:
            st.error(f"Meal sync failed: {msg1}")
        ok2, msg2 = force_load_food_mappings_from_gsheets()
        if ok2:
            st.success("Food mappings reloaded.")
        else:
            st.error(f"Mappings reload failed: {msg2}")
        st.rerun()
    if "_fitness_last_gsheets_refresh" not in st.session_state:
        st.session_state["_fitness_last_gsheets_refresh"] = get_last_gsheets_sync()
    st.caption(f"*Last refreshed: {st.session_state['_fitness_last_gsheets_refresh']}*  ·  Rows in log: **{len(df_rows)}**")
