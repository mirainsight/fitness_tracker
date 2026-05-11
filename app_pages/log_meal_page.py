"""Log meals from JSON + category / subcategory (finance-style mappings)."""

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from pydantic import ValidationError

from utils.app_utils import load_maincss
from utils.constants import paths
from utils.food_category_storage import (
    add_food_category,
    add_food_subcategory,
    get_effective_food_subcategories,
    is_user_added_food_subcategory,
    load_user_food_categories,
    remove_food_category,
    remove_food_subcategory,
    rename_food_category,
    rename_food_subcategory,
)
from utils.food_mapping_storage import force_load_food_mappings_from_gsheets
from utils.meal_schema import MealInput
from utils.meal_storage import (
    force_sync_to_gsheets,
    load_meals,
    meal_input_to_row,
    meal_row_to_json_text,
    save_meals,
)
from utils.meal_name_inference import (
    delete_learned_mapping,
    infer_meal_category,
    invalidate_inference_cache,
    load_learned_mappings,
    save_learned_mapping,
    save_learned_mappings_bulk,
)
from utils.meal_streamlit_cache import (
    cached_food_mappings_dict,
    cached_get_meal_names_list,
    cached_load_meals,
    invalidate_meal_caches,
    meals_df_hash,
    preload_upstash_session_caches,
)
from utils.upstash_storage import get_last_gsheets_sync, save_last_gsheets_sync

load_maincss(paths["maincss"])
preload_upstash_session_caches()

st.title("Log meal")

sample = """{
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

if not st.session_state.get("_fitness_json_initialized"):
    st.session_state.fitness_meal_json = ""
    st.session_state["_fitness_json_initialized"] = True
elif st.session_state.pop("_fitness_json_reset", False):
    st.session_state.fitness_meal_json = ""
    st.session_state.fitness_meal_comments = ""

with st.expander("Sample JSON"):
    st.code(
        "Estimate based on my meal in chat or picture given. Output in the following format\n\n" + sample,
        language="json",
    )

mappings = cached_food_mappings_dict()
effective = get_effective_food_subcategories()
categories = sorted(effective.keys())

# Clear meal name on the rerun after a successful add (must run before the selectbox renders)
if st.session_state.pop("_fitness_meal_name_reset", False):
    st.session_state.fitness_meal_name_input = ""

# --- Meal name field (drives inference, like description in financial tracker) ---
df = cached_load_meals()
df_hash = meals_df_hash(df)
past_meal_names = cached_get_meal_names_list(df_hash)

meal_name = st.selectbox(
    "Meal name",
    options=[""] + past_meal_names,
    key="fitness_meal_name_input",
    placeholder="e.g. Nasi lemak, Wantan mee, Grilled chicken...",
    help="Select a past meal to auto-fill, or type a new one.",
    accept_new_options=True,
)

# Run 3-tier inference when meal name changes (same pattern as financial tracker)
if meal_name and meal_name.strip():
    last_inferred_name = st.session_state.get("_last_inferred_meal_name", "")
    if meal_name != last_inferred_name:
        inferred = infer_meal_category(meal_name, mappings)
        st.session_state["_last_inferred_meal_result"] = inferred
        if inferred:
            _, (cat_inf, sub_inf) = inferred
            if cat_inf in categories:
                st.session_state["fitness_log_cat"] = cat_inf
                if sub_inf in effective.get(cat_inf, []):
                    st.session_state["fitness_log_sub"] = sub_inf
        st.session_state["_last_inferred_meal_name"] = meal_name
else:
    st.session_state["_last_inferred_meal_name"] = ""
    st.session_state["_last_inferred_meal_result"] = None

# Category / subcategory dropdowns with inline add-new (finance-style)
_ADD_NEW_CAT = "➕ Add new category"
_ADD_NEW_SUB = "➕ Add new subcategory"

cat_options = categories + [_ADD_NEW_CAT]
if "fitness_log_cat" not in st.session_state:
    st.session_state.fitness_log_cat = categories[0] if categories else ""
cat = st.selectbox("Category", cat_options, key="fitness_log_cat")

if cat == _ADD_NEW_CAT:
    st.text_input("New category name", key="fitness_new_cat_inline", placeholder="e.g. Supplements")
    st.text_input("New subcategory name", key="fitness_new_sub_inline", placeholder="e.g. Protein shake")
    sub = _ADD_NEW_SUB
else:
    subs = effective.get(cat, ["Other"])
    sub_options = subs + [_ADD_NEW_SUB]
    if st.session_state.get("fitness_log_sub") not in sub_options:
        st.session_state.fitness_log_sub = subs[0] if subs else "Other"
    sub = st.selectbox("Subcategory", sub_options, key="fitness_log_sub")
    if sub == _ADD_NEW_SUB:
        st.text_input("New subcategory name", key="fitness_new_sub_inline", placeholder="e.g. Smoothie")

# Inference hint + Wrong? Forget
inferred = st.session_state.get("_last_inferred_meal_result")
if inferred:
    source, (cat_inf, sub_inf) = inferred
    source_label = {"learned": "saved", "word_scores": "similar", "sheet": "sheet"}.get(source, source)
    col_infer, col_forget = st.columns([3, 1])
    with col_infer:
        st.caption(f"✨ Inferred ({source_label}): **{cat_inf}** → **{sub_inf}**")
    with col_forget:
        if st.button("Wrong? Forget", key="forget_meal_inference", help="Clear saved mapping for this meal name"):
            delete_learned_mapping(meal_name)
            invalidate_inference_cache()
            st.session_state["_last_inferred_meal_result"] = None
            st.session_state["_last_inferred_meal_name"] = ""
            st.rerun()

# Template fill — sets meal name field + nutrition JSON
tcol1, tcol2 = st.columns([4, 1])
with tcol1:
    template_name = st.selectbox(
        "Fill from past meal (optional)",
        options=[""] + past_meal_names,
        key="fitness_meal_template",
        help="Fills nutrition JSON and meal name from a previous entry.",
    )
with tcol2:
    st.write("")
    if st.button("Fill", disabled=not bool(template_name)):
        m = df[df["MEAL_NAME"].astype(str).str.strip() == str(template_name).strip()]
        if not m.empty:
            m_sorted = m.assign(_lg=pd.to_datetime(m["LOGGED_AT"], errors="coerce")).sort_values(
                "_lg", ascending=False, na_position="last"
            )
            st.session_state.fitness_meal_json = meal_row_to_json_text(m_sorted.iloc[0])
            st.session_state.fitness_meal_name_input = str(template_name).strip()
            st.rerun()


meal_date = st.date_input("Meal date", value=date.today())
st.text_area(
    "Nutrition JSON",
    height=280,
    placeholder="Paste nutrition JSON here…",
    key="fitness_meal_json",
)
st.text_input(
    "Comments (optional)",
    placeholder="e.g. Post-workout, cheat day, estimate…",
    key="fitness_meal_comments",
)

add_meal = st.button("Add meal", type="primary")

if add_meal:
    meal_name_val = (st.session_state.get("fitness_meal_name_input") or "").strip()
    if not meal_name_val:
        st.error("Please enter a meal name.")
    else:
        try:
            meal = MealInput.model_validate_json(st.session_state.fitness_meal_json)
            jc = (meal.category or "").strip()
            js = (meal.subcategory or "").strip()

            cat_val = st.session_state.get("fitness_log_cat", "")
            sub_val = st.session_state.get("fitness_log_sub", "")
            _error = None
            res_cat = res_sub = ""

            if jc and js:
                res_cat, res_sub = jc, js
            elif cat_val == _ADD_NEW_CAT:
                new_cat = (st.session_state.get("fitness_new_cat_inline") or "").strip()
                new_sub = (st.session_state.get("fitness_new_sub_inline") or "").strip()
                if not new_cat or not new_sub:
                    _error = "Enter both category and subcategory names."
                else:
                    add_food_category(new_cat)
                    add_food_subcategory(new_cat, new_sub)
                    invalidate_inference_cache()
                    st.session_state.fitness_log_cat = new_cat
                    st.session_state.fitness_log_sub = new_sub
                    res_cat, res_sub = new_cat, new_sub
            elif sub_val == _ADD_NEW_SUB:
                new_sub = (st.session_state.get("fitness_new_sub_inline") or "").strip()
                if not new_sub:
                    _error = "Enter the new subcategory name."
                else:
                    add_food_subcategory(cat_val, new_sub)
                    invalidate_inference_cache()
                    st.session_state.fitness_log_sub = new_sub
                    res_cat, res_sub = cat_val, new_sub
            else:
                res_cat = cat_val.strip()
                res_sub = sub_val.strip()

            if _error:
                st.error(_error)
            else:
                if res_cat and not res_sub:
                    res_sub = (effective.get(res_cat, ["Other"]) or ["Other"])[0]
                comments_val = (st.session_state.get("fitness_meal_comments") or "").strip()
                row = meal_input_to_row(meal, meal_date.isoformat(), meal_name=meal_name_val, category=res_cat, subcategory=res_sub, comments=comments_val)
                df_new = pd.concat([cached_load_meals(), pd.DataFrame([row])], ignore_index=True)
                save_meals(df_new)
                invalidate_meal_caches()
                if res_cat and res_sub:
                    save_learned_mapping(meal_name_val, res_cat, res_sub)
                st.session_state["_fitness_json_reset"] = True
                st.session_state["_fitness_meal_name_reset"] = True
                st.session_state["_last_added_meal"] = {
                    "name": meal_name_val,
                    "calories": meal.calories_kcal,
                }
                st.rerun()
        except ValidationError as e:
            st.error("JSON does not match the expected schema.")
            st.json(e.errors())

# --- Celebratory banner ---
if st.session_state.get("_last_added_meal"):
    m = st.session_state["_last_added_meal"]
    components.html("""
    <script src="https://cdn.jsdelivr.net/npm/canvas-confetti@1.6.0/dist/confetti.browser.min.js"></script>
    <script>
        var existingCanvas = parent.document.getElementById('confetti-canvas');
        if (existingCanvas) { existingCanvas.remove(); }
        var canvas = parent.document.createElement('canvas');
        canvas.id = 'confetti-canvas';
        canvas.style.position = 'fixed';
        canvas.style.top = '0';
        canvas.style.left = '0';
        canvas.style.width = '100%';
        canvas.style.height = '100%';
        canvas.style.pointerEvents = 'none';
        canvas.style.zIndex = '9999';
        parent.document.body.appendChild(canvas);
        var myConfetti = confetti.create(canvas, { resize: true });
        myConfetti({
            particleCount: 150,
            spread: 100,
            origin: { x: 0.5, y: 0.5 },
            colors: ['#ff0000', '#00ff00', '#0000ff', '#ffff00', '#ff00ff', '#00ffff']
        });
        setTimeout(function() { myConfetti.reset(); canvas.remove(); }, 3000);
    </script>
    """, height=0)
    st.success(f"**{m['name']}** — **{m['calories']:.0f} kcal** logged!")
    del st.session_state["_last_added_meal"]

df_rows = cached_load_meals()
st.divider()

# --- Exercise log ---
from utils.exercise_storage import exercise_to_row, load_exercises, save_exercises

st.subheader("Log exercise")
with st.form("exercise_form"):
    ex_col1, ex_col2, ex_col3 = st.columns([2, 3, 2])
    with ex_col1:
        ex_date = st.date_input("Date", value=date.today(), key="ex_date")
    with ex_col2:
        ex_name = st.text_input("Exercise", placeholder="e.g. Running, Cycling, Gym…", key="ex_name")
    with ex_col3:
        ex_kcal = st.number_input("Calories burned", min_value=0.0, step=10.0, key="ex_kcal")
    ex_submitted = st.form_submit_button("Add exercise", type="primary")

if ex_submitted:
    if not ex_name.strip():
        st.error("Enter an exercise name.")
    elif ex_kcal <= 0:
        st.error("Enter calories burned.")
    else:
        ex_df = load_exercises()
        new_row = exercise_to_row(ex_date.isoformat(), ex_name.strip(), ex_kcal)
        ex_df = pd.concat([ex_df, pd.DataFrame([new_row])], ignore_index=True)
        save_exercises(ex_df)
        st.toast(f"Logged {ex_name.strip()} — {ex_kcal:.0f} kcal burned", icon="🏃")
        st.rerun()

ex_df_display = load_exercises()
if not ex_df_display.empty:
    ex_df_display = ex_df_display.copy()
    ex_df_display["EXERCISE_DATE"] = pd.to_datetime(ex_df_display["EXERCISE_DATE"], errors="coerce")
    ex_df_display = ex_df_display.sort_values("EXERCISE_DATE", ascending=False).head(10)
    ex_df_display["EXERCISE_DATE"] = ex_df_display["EXERCISE_DATE"].dt.strftime("%Y-%m-%d")
    st.dataframe(
        ex_df_display[["EXERCISE_DATE", "EXERCISE_NAME", "CALORIES_BURNED"]].rename(
            columns={"EXERCISE_DATE": "Date", "EXERCISE_NAME": "Exercise", "CALORIES_BURNED": "kcal burned"}
        ),
        use_container_width=True,
        hide_index=True,
    )

st.divider()

# --- Rename or remove categories ---
with st.expander("Rename or remove categories", expanded=False):
    effective_r = get_effective_food_subcategories()
    user_cats_r = load_user_food_categories()
    user_cat_list = sorted(user_cats_r.keys())
    user_sub_list = [
        (c, s) for c in sorted(effective_r.keys()) for s in effective_r.get(c, [])
        if is_user_added_food_subcategory(c, s)
    ]

    st.caption("User-added categories and subcategories only")

    mod_col1, mod_col2 = st.columns(2)
    with mod_col1:
        if not user_cat_list:
            st.info("No user-added categories to modify.")
        else:
            sel_cat = st.selectbox("Select category", options=user_cat_list, key="meal_sel_mod_cat")
            if sel_cat:
                new_name = st.text_input("New name (rename)", key="meal_rename_cat_new", placeholder="Leave blank to skip rename")
                confirm_remove_cat = st.checkbox("I confirm I want to remove this category", key="meal_confirm_remove_cat")
                btn_col1, btn_col2 = st.columns(2)
                with btn_col1:
                    if st.button("Rename category", key="meal_btn_rename_cat"):
                        if new_name and new_name.strip() and new_name.strip() != sel_cat:
                            if rename_food_category(sel_cat, new_name.strip()):
                                df_upd = load_meals()
                                if not df_upd.empty and "CATEGORY" in df_upd.columns:
                                    mask = df_upd["CATEGORY"].astype(str).str.strip() == sel_cat
                                    df_upd.loc[mask, "CATEGORY"] = new_name.strip()
                                    save_meals(df_upd)
                                learned = load_learned_mappings()
                                updated = False
                                for mk, cs in list(learned.items()):
                                    if isinstance(cs, (list, tuple)) and len(cs) >= 2 and cs[0] == sel_cat:
                                        learned[mk] = [new_name.strip(), cs[1]]
                                        updated = True
                                if updated:
                                    save_learned_mappings_bulk(learned)
                                invalidate_inference_cache()
                                invalidate_meal_caches()
                                st.success(f'Renamed "{sel_cat}" to "{new_name.strip()}"')
                                st.rerun()
                            else:
                                st.warning(f'Category "{new_name.strip()}" already exists.')
                        else:
                            st.error("Enter a different name.")
                with btn_col2:
                    if st.button("Remove category", key="meal_btn_remove_cat", disabled=not confirm_remove_cat):
                        df_check = cached_load_meals()
                        n = 0
                        if not df_check.empty and "CATEGORY" in df_check.columns:
                            n = (df_check["CATEGORY"].astype(str).str.strip() == sel_cat).sum()
                        if n > 0:
                            st.error(f"Cannot remove: {n} meal(s) use this category. Reassign them first.")
                        else:
                            remove_food_category(sel_cat)
                            invalidate_inference_cache()
                            st.success(f'Removed category "{sel_cat}"')
                            st.rerun()

    with mod_col2:
        if not user_sub_list:
            st.info("No user-added subcategories to modify.")
        else:
            sel_opts = [f"{c} → {s}" for c, s in user_sub_list]
            sel_idx = st.selectbox("Select subcategory", range(len(sel_opts)), format_func=lambda i: sel_opts[i], key="meal_sel_mod_sub")
            if sel_idx is not None:
                r_cat, r_sub = user_sub_list[sel_idx]
                new_sub_rename = st.text_input("New name (rename)", key="meal_rename_sub_new", placeholder="Leave blank to skip rename")
                confirm_remove_sub = st.checkbox("I confirm I want to remove this subcategory", key="meal_confirm_remove_sub")
                btn_col1, btn_col2 = st.columns(2)
                with btn_col1:
                    if st.button("Rename subcategory", key="meal_btn_rename_sub"):
                        if new_sub_rename and new_sub_rename.strip() and new_sub_rename.strip() != r_sub:
                            if rename_food_subcategory(r_cat, r_sub, new_sub_rename.strip()):
                                df_upd = load_meals()
                                if not df_upd.empty and "CATEGORY" in df_upd.columns and "SUBCATEGORY" in df_upd.columns:
                                    mask = (
                                        (df_upd["CATEGORY"].astype(str).str.strip() == r_cat)
                                        & (df_upd["SUBCATEGORY"].astype(str).str.strip() == r_sub)
                                    )
                                    df_upd.loc[mask, "SUBCATEGORY"] = new_sub_rename.strip()
                                    save_meals(df_upd)
                                learned = load_learned_mappings()
                                updated = False
                                for mk, cs in list(learned.items()):
                                    if isinstance(cs, (list, tuple)) and len(cs) >= 2 and cs[0] == r_cat and cs[1] == r_sub:
                                        learned[mk] = [r_cat, new_sub_rename.strip()]
                                        updated = True
                                if updated:
                                    save_learned_mappings_bulk(learned)
                                invalidate_inference_cache()
                                invalidate_meal_caches()
                                st.success(f'Renamed "{r_sub}" to "{new_sub_rename.strip()}" in {r_cat}')
                                st.rerun()
                            else:
                                st.warning(f'Subcategory "{new_sub_rename.strip()}" already exists in {r_cat}.')
                        else:
                            st.error("Enter a different name.")
                with btn_col2:
                    if st.button("Remove subcategory", key="meal_btn_remove_sub", disabled=not confirm_remove_sub):
                        df_check = cached_load_meals()
                        n = 0
                        if not df_check.empty and "CATEGORY" in df_check.columns and "SUBCATEGORY" in df_check.columns:
                            n = (
                                (df_check["CATEGORY"].astype(str).str.strip() == r_cat)
                                & (df_check["SUBCATEGORY"].astype(str).str.strip() == r_sub)
                            ).sum()
                        if n > 0:
                            st.error(f"Cannot remove: {n} meal(s) use this subcategory. Reassign them first.")
                        else:
                            remove_food_subcategory(r_cat, r_sub)
                            invalidate_inference_cache()
                            st.success(f'Removed "{r_sub}" from {r_cat}')
                            st.rerun()

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
            # Extract unique (category, subcategory) pairs from mappings and merge into taxonomy
            from utils.food_mapping_storage import load_food_mappings_from_storage as _load_mappings
            from utils.constants import DEFAULT_FOOD_SUBCATEGORIES as _DEFAULTS
            _new_mappings = _load_mappings()
            _user_cats = load_user_food_categories()
            _changed = False
            for _cs in _new_mappings.values():
                if not isinstance(_cs, (list, tuple)) or len(_cs) < 2:
                    continue
                _cat, _sub = str(_cs[0]).strip(), str(_cs[1]).strip()
                if not _cat or not _sub:
                    continue
                if _sub in _DEFAULTS.get(_cat, []):
                    continue
                if _sub not in _user_cats.get(_cat, []):
                    _user_cats.setdefault(_cat, [])
                    if _sub not in _user_cats[_cat]:
                        _user_cats[_cat].append(_sub)
                        _changed = True
            if _changed:
                from utils.food_category_storage import save_user_food_categories as _save_cats
                _save_cats(_user_cats)
            invalidate_inference_cache()
            st.success(f"Food mappings reloaded ({len(_new_mappings)} entries). Categories updated.")
        else:
            st.error(f"Mappings reload failed: {msg2}")
        st.rerun()
    if "_fitness_last_gsheets_refresh" not in st.session_state:
        st.session_state["_fitness_last_gsheets_refresh"] = get_last_gsheets_sync()
    st.caption(f"*Last refreshed: {st.session_state['_fitness_last_gsheets_refresh']}*  ·  Rows in log: **{len(df_rows)}**")
