"""Meal ledger: view, filter, edit (past transactions analogue)."""

from datetime import datetime

import streamlit as st

from utils.app_utils import load_maincss
from utils.constants import MEAL_COLUMNS, paths
from utils.food_category_storage import get_effective_food_categories
from utils.meal_storage import force_sync_to_gsheets, save_meals
from utils.meal_streamlit_cache import cached_load_meals, cached_prepare_meals_display_df_logged, meals_df_hash
from utils.upstash_storage import get_last_gsheets_sync, save_last_gsheets_sync

load_maincss(paths["maincss"])

st.title("Past meals")

df = cached_load_meals()
if df.empty:
    st.info("No meals yet. Log your first entry on **Log meal**.")
    st.stop()

df_hash = meals_df_hash(df)
df_show = cached_prepare_meals_display_df_logged(df_hash)
display_cols = [c for c in MEAL_COLUMNS if c in df_show.columns]
df_show = df_show[display_cols].copy()

st.caption(f"**{len(df_show)}** meals · Last GSheets sync: **{get_last_gsheets_sync()}**")

q = st.text_input("Filter by meal name", "")
if q.strip():
    df_show = df_show[df_show["MEAL_NAME"].astype(str).str.contains(q.strip(), case=False, na=False)]

if "CATEGORY" in df_show.columns:
    from_data = {
        (c.strip() if str(c).strip() else "(blank)")
        for c in df_show["CATEGORY"].dropna().astype(str).tolist()
    }
    fcats = ["(All)", *sorted(set(get_effective_food_categories()) | from_data)]
    cat_f = st.selectbox("Category", fcats, key="past_meals_cat_filter")
    if cat_f != "(All)":
        if cat_f == "(blank)":
            df_show = df_show[df_show["CATEGORY"].astype(str).str.strip() == ""]
        else:
            df_show = df_show[df_show["CATEGORY"].astype(str).str.strip() == cat_f]

edited = st.data_editor(
    df_show,
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "CALORIES_KCAL": st.column_config.NumberColumn(format="%.0f"),
        "PROTEIN_G": st.column_config.NumberColumn(format="%.1f"),
        "CARBOHYDRATES_G": st.column_config.NumberColumn(format="%.1f"),
        "FAT_G": st.column_config.NumberColumn(format="%.1f"),
        "FIBER_G": st.column_config.NumberColumn(format="%.1f"),
        "SUGAR_G": st.column_config.NumberColumn(format="%.1f"),
        "SODIUM_MG": st.column_config.NumberColumn(format="%.0f"),
        "POTASSIUM_MG": st.column_config.NumberColumn(format="%.0f"),
        "CALCIUM_MG": st.column_config.NumberColumn(format="%.0f"),
        "IRON_MG": st.column_config.NumberColumn(format="%.2f"),
        "VITAMIN_C_MG": st.column_config.NumberColumn(format="%.1f"),
    },
    key="past_meals_editor",
)

c1, c2 = st.columns(2)
with c1:
    if st.button("Save changes to storage", type="primary"):
        save_meals(edited)
        st.success("Saved.")
        st.rerun()
with c2:
    if st.button("Push current table → Google Sheets"):
        ok, msg = force_sync_to_gsheets(edited)
        if ok:
            save_last_gsheets_sync(datetime.now().isoformat(timespec="seconds"))
            st.success(msg)
        else:
            st.error(msg)
