"""Log meals from JSON + category / subcategory (finance-style mappings)."""

import json
from datetime import date, datetime

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
from utils.meal_name_inference import infer_food_category_subcategory
from utils.meal_streamlit_cache import (
    cached_food_mappings_dict,
    cached_get_meal_names_list,
    cached_load_meals,
    meals_df_hash,
)
from utils.upstash_storage import get_last_gsheets_sync, save_last_gsheets_sync, test_upstash_connection

load_maincss(paths["maincss"])


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
    st.code(sample, language="json")

mappings = cached_food_mappings_dict()
effective = get_effective_food_subcategories()
categories = sorted(effective.keys())

meal_name_preview = _peek_meal_name(st.session_state.fitness_meal_json)
prev_peek = st.session_state.get("_fitness_meal_name_peek", "")
if meal_name_preview != prev_peek:
    st.session_state["_fitness_meal_name_peek"] = meal_name_preview
    st.session_state.pop("fitness_log_cat", None)
    st.session_state.pop("fitness_log_sub", None)

inf_cat, inf_sub = infer_food_category_subcategory(meal_name_preview, mappings)

if "fitness_log_cat" not in st.session_state:
    st.session_state.fitness_log_cat = inf_cat if inf_cat in categories else (categories[0] if categories else "")
cat = st.selectbox("Category", categories, key="fitness_log_cat")
subs = effective.get(cat, ["Other"])
if st.session_state.get("fitness_log_sub") not in subs:
    st.session_state.fitness_log_sub = (
        inf_sub if (inf_cat == cat and inf_sub in subs) else subs[0]
    )
sub_ix = subs.index(st.session_state.fitness_log_sub) if st.session_state.fitness_log_sub in subs else 0
sub = st.selectbox("Subcategory", subs, index=sub_ix, key="fitness_log_sub")

if meal_name_preview and mappings:
    st.caption(f"Sheet inference for this name: **{inf_cat or '—'}** / **{inf_sub or '—'}** (longest keyword match)")

with st.expander("Food mapping sheet"):
    st.markdown(
        "Use a tab with columns such as **MEAL_KEY** (or KEYWORD / FOOD_KEY), **CATEGORY**, **SUBCATEGORY**. "
        "Set the tab name in secrets as `FITNESS_FOOD_MAPPINGS_WORKSHEET` "
        "(the `gid` in the URL is **not** the tab name — check the sheet tab label)."
    )
    if is_food_mappings_gsheets_configured():
        if st.button("Reload mappings from Google Sheet"):
            ok, msg = force_load_food_mappings_from_gsheets()
            (st.success if ok else st.error)(msg)
            st.rerun()
    else:
        st.caption("Configure `FITNESS_SPREADSHEET_ID` + credentials to load mappings from Sheets.")

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

col_a, col_b = st.columns(2)
with col_a:
    add_meal = st.button("Add meal", type="primary")
with col_b:
    sync_gs = st.button("Sync meals → Google Sheets")

if add_meal:
    try:
        meal = MealInput.model_validate_json(st.session_state.fitness_meal_json)
        jc = (meal.category or "").strip()
        js = (meal.subcategory or "").strip()
        if jc and js:
            res_cat, res_sub = jc, js
        else:
            res_cat = (st.session_state.get("fitness_log_cat") or inf_cat or "").strip()
            res_sub = (st.session_state.get("fitness_log_sub") or inf_sub or "").strip()
        if res_cat and not res_sub:
            res_sub = (effective.get(res_cat, ["Other"]) or ["Other"])[0]
        row = meal_input_to_row(meal, meal_date.isoformat(), category=res_cat, subcategory=res_sub)
        df_new = pd.concat([cached_load_meals(), pd.DataFrame([row])], ignore_index=True)
        save_meals(df_new)
        st.session_state.fitness_meal_json = sample
        st.toast(f"Logged {meal.meal_name} — {meal.calories_kcal:.0f} kcal", icon="✅")
        st.rerun()
    except ValidationError as e:
        st.error("JSON does not match the expected meal schema.")
        st.json(e.errors())

if sync_gs:
    df2 = cached_load_meals()
    ok, msg = force_sync_to_gsheets(df2)
    if ok:
        save_last_gsheets_sync(datetime.now().isoformat(timespec="seconds"))
        st.success(msg)
    else:
        st.error(msg)

df_rows = cached_load_meals()
st.divider()
st.caption(f"Last GSheets sync: **{get_last_gsheets_sync()}**  ·  Rows in log: **{len(df_rows)}**")
