"""Meal log storage: Upstash primary; Google Sheets sync on demand; CSV fallback."""

import json
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import streamlit as st

from utils.constants import (
    DEFAULT_SPREADSHEET_ID,
    MEAL_COLUMNS,
    MEALS_WORKSHEET_NAME,
    paths,
)
from utils.meal_schema import MealInput
from utils.upstash_storage import (
    KEY_MEALS,
    is_upstash_configured,
    load_from_upstash,
    save_to_upstash,
)


def _spreadsheet_id() -> str:
    try:
        if hasattr(st, "secrets") and st.secrets:
            sid = (
                st.secrets.get("FITNESS_SPREADSHEET_ID")
                or st.secrets.get("fitness_spreadsheet_id")
                or getattr(st.secrets, "FITNESS_SPREADSHEET_ID", None)
            )
            if sid:
                return str(sid).strip()
    except Exception:
        pass
    return (DEFAULT_SPREADSHEET_ID or "").strip()


def _worksheet_name() -> str:
    try:
        if hasattr(st, "secrets") and st.secrets:
            w = st.secrets.get("FITNESS_MEALS_WORKSHEET") or st.secrets.get("fitness_meals_worksheet")
            if w:
                return str(w).strip()
    except Exception:
        pass
    return MEALS_WORKSHEET_NAME


def _get_gsheets_config() -> Optional[dict]:
    spreadsheet_id = _spreadsheet_id()
    if not spreadsheet_id or spreadsheet_id == "your-spreadsheet-id-here":
        return None
    try:
        if not hasattr(st, "secrets") or not st.secrets:
            return None
        creds = None
        for key in ("gcp_service_account", "GCP_SERVICE_ACCOUNT"):
            gcp = st.secrets.get(key) or getattr(st.secrets, key, None)
            if gcp is not None:
                try:
                    creds = dict(gcp) if hasattr(gcp, "keys") else None
                    if creds and creds.get("type") == "service_account":
                        break
                except (TypeError, ValueError):
                    pass
                creds = None
        if not creds:
            creds_raw = st.secrets.get("GOOGLE_SHEETS_CREDENTIALS") or st.secrets.get("google_sheets_credentials")
            if creds_raw:
                creds = json.loads(creds_raw) if isinstance(creds_raw, str) else creds_raw
        if not creds:
            creds_file = st.secrets.get("GOOGLE_SHEETS_CREDENTIALS_FILE") or st.secrets.get(
                "google_sheets_credentials_file"
            )
            if creds_file:
                with open(creds_file) as f:
                    creds = json.load(f)
        if creds and (creds.get("type") == "service_account" if isinstance(creds, dict) else True):
            return {
                "spreadsheet_id": spreadsheet_id,
                "credentials": creds,
                "worksheet": _worksheet_name(),
            }
    except Exception:
        pass
    return None


def _get_gsheets_client():
    import gspread
    from google.oauth2.service_account import Credentials

    config = _get_gsheets_config()
    if not config:
        return None
    creds = Credentials.from_service_account_info(
        config["credentials"],
        scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"],
    )
    return gspread.authorize(creds), config


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    text_cols = {"MEAL_DATE", "LOGGED_AT", "MEAL_NAME", "SERVING_SIZE", "SOURCE", "CATEGORY", "SUBCATEGORY", "COMMENTS"}
    for col in MEAL_COLUMNS:
        if col not in df.columns:
            df[col] = "" if col in text_cols else 0.0
    for col in MEAL_COLUMNS:
        if col in df.columns:
            if col in ("MEAL_DATE", "LOGGED_AT", "MEAL_NAME", "SERVING_SIZE", "SOURCE", "CATEGORY", "SUBCATEGORY", "COMMENTS"):
                df[col] = df[col].fillna("").astype(str)
            else:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    cols = [c for c in MEAL_COLUMNS if c in df.columns]
    extra = [c for c in df.columns if c not in MEAL_COLUMNS]
    return df[cols + extra]


def _get_worksheet(gc, config):
    import gspread

    spreadsheet = gc.open_by_key(config["spreadsheet_id"])
    try:
        return spreadsheet.worksheet(config["worksheet"])
    except gspread.WorksheetNotFound:
        return spreadsheet.add_worksheet(config["worksheet"], rows=2000, cols=len(MEAL_COLUMNS) + 2)


def _store_gsheets_error(err: Exception) -> None:
    if hasattr(st, "session_state"):
        st.session_state["_fitness_gsheets_last_error"] = f"{type(err).__name__}: {err}"


def _load_from_gsheets() -> Optional[pd.DataFrame]:
    try:
        pair = _get_gsheets_client()
        if not pair:
            return None
        gc, config = pair
        worksheet = _get_worksheet(gc, config)
        records = worksheet.get_all_records()
        if not records:
            return pd.DataFrame(columns=MEAL_COLUMNS)
        return _normalize_df(pd.DataFrame(records))
    except Exception as e:
        _store_gsheets_error(e)
        return None


_BATCH_SIZE = 500


def _save_to_gsheets(df: pd.DataFrame) -> bool:
    try:
        pair = _get_gsheets_client()
        if not pair:
            return False
        gc, config = pair
        worksheet = _get_worksheet(gc, config)
        out = df.copy()
        for c in MEAL_COLUMNS:
            if c not in out.columns:
                out[c] = (
                    ""
                    if c
                    in ("MEAL_DATE", "LOGGED_AT", "MEAL_NAME", "SERVING_SIZE", "SOURCE", "CATEGORY", "SUBCATEGORY", "COMMENTS")
                    else 0
                )
        out = out[[c for c in MEAL_COLUMNS if c in out.columns]]
        values = [MEAL_COLUMNS] + out.fillna("").astype(str).values.tolist()
        worksheet.clear()
        if values:
            for i in range(0, len(values), _BATCH_SIZE):
                chunk = values[i : i + _BATCH_SIZE]
                start_cell = f"A{i + 1}"
                worksheet.update(chunk, start_cell, value_input_option="RAW")
        return True
    except Exception as e:
        _store_gsheets_error(e)
        return False


def get_meals_path() -> Path:
    path = Path(paths["meals_csv"])
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_meals() -> pd.DataFrame:
    if is_upstash_configured():
        raw = load_from_upstash(KEY_MEALS)
        if raw:
            try:
                df = pd.read_csv(StringIO(raw))
                if hasattr(st, "session_state"):
                    st.session_state["_fitness_gsheets_save_failed"] = False
                return _normalize_df(df)
            except Exception:
                pass
        if _get_gsheets_config():
            df = _load_from_gsheets()
            if df is not None and not df.empty:
                save_meals(df)
                return df
        path = get_meals_path()
        if path.exists():
            df = pd.read_csv(path)
            save_meals(df)
            return _normalize_df(df)
        return pd.DataFrame(columns=MEAL_COLUMNS)

    df = _load_from_gsheets()
    if df is not None:
        if hasattr(st, "session_state"):
            st.session_state["_fitness_gsheets_save_failed"] = False
        return df
    if hasattr(st, "session_state") and _get_gsheets_config():
        st.session_state["_fitness_gsheets_save_failed"] = True
    path = get_meals_path()
    if not path.exists():
        return pd.DataFrame(columns=MEAL_COLUMNS)
    return _normalize_df(pd.read_csv(path))


def save_meals(df: pd.DataFrame) -> None:
    if hasattr(st, "session_state"):
        st.session_state["fitness_df_meals"] = None
    df = _normalize_df(df)
    if is_upstash_configured():
        raw = df.to_csv(index=False)
        if save_to_upstash(KEY_MEALS, raw):
            if hasattr(st, "session_state"):
                st.session_state["_fitness_gsheets_save_failed"] = False
            _invalidate_meal_derived_caches()
            return
        if hasattr(st, "session_state"):
            st.session_state["_fitness_gsheets_save_failed"] = True
        df.to_csv(get_meals_path(), index=False)
        _invalidate_meal_derived_caches()
        return

    if _save_to_gsheets(df):
        if hasattr(st, "session_state"):
            st.session_state["_fitness_gsheets_save_failed"] = False
        _invalidate_meal_derived_caches()
        return
    if hasattr(st, "session_state"):
        st.session_state["_fitness_gsheets_save_failed"] = True
    df.to_csv(get_meals_path(), index=False)
    _invalidate_meal_derived_caches()


def force_sync_to_gsheets(df: pd.DataFrame) -> tuple[bool, str]:
    if not _get_gsheets_config():
        return False, "Google Sheets not configured — set FITNESS_SPREADSHEET_ID and service account in secrets"
    ok = _save_to_gsheets(_normalize_df(df))
    if ok:
        if hasattr(st, "session_state"):
            st.session_state["_fitness_gsheets_save_failed"] = False
        return True, "Synced to Google Sheets."
    err = st.session_state.get("_fitness_gsheets_last_error", "Unknown error")
    return False, str(err)


def force_load_from_gsheets() -> tuple[bool, str, Optional[pd.DataFrame]]:
    if not _get_gsheets_config():
        return False, "Google Sheets not configured", None
    df = _load_from_gsheets()
    if df is None:
        return False, "Failed to load from Google Sheets", None
    return True, f"Loaded {len(df)} meals", df


def is_gsheets_configured() -> bool:
    return _get_gsheets_config() is not None


def get_storage_backend() -> str:
    if is_upstash_configured():
        return "upstash"
    if _get_gsheets_config():
        return "google_sheets"
    return "csv"


def _invalidate_meal_derived_caches() -> None:
    try:
        from utils.meal_streamlit_cache import invalidate_meal_caches

        invalidate_meal_caches()
    except Exception:
        pass


def meal_row_to_json_text(row: pd.Series) -> str:
    """Rebuild nested meal JSON from a flat ledger row (quick re-entry / templates)."""

    def num(col: str) -> float:
        try:
            v = pd.to_numeric(row.get(col), errors="coerce")
            return float(v) if pd.notna(v) else 0.0
        except (TypeError, ValueError):
            return 0.0

    payload = {
        "serving_size": str(row.get("SERVING_SIZE", "") or ""),
        "calories_kcal": num("CALORIES_KCAL"),
        "macronutrients": {
            "protein_g": num("PROTEIN_G"),
            "carbohydrates_g": num("CARBOHYDRATES_G"),
            "fat_g": num("FAT_G"),
            "fiber_g": num("FIBER_G"),
            "sugar_g": num("SUGAR_G"),
        },
        "micronutrients": {
            "sodium_mg": num("SODIUM_MG"),
            "potassium_mg": num("POTASSIUM_MG"),
            "calcium_mg": num("CALCIUM_MG"),
            "iron_mg": num("IRON_MG"),
            "vitamin_c_mg": num("VITAMIN_C_MG"),
        },
    }
    c = str(row.get("CATEGORY", "") or "").strip()
    s = str(row.get("SUBCATEGORY", "") or "").strip()
    if c:
        payload["category"] = c
    if s:
        payload["subcategory"] = s
    return json.dumps(payload, indent=2)


def meal_input_to_row(
    meal: MealInput,
    meal_date: str,
    source: str = "json",
    *,
    meal_name: str = "",
    category: str = "",
    subcategory: str = "",
    comments: str = "",
) -> dict[str, Any]:
    micro = meal.micronutrients
    macro = meal.macronutrients
    logged = datetime.now().isoformat(timespec="seconds")
    return {
        "MEAL_DATE": meal_date,
        "LOGGED_AT": logged,
        "MEAL_NAME": meal_name or meal.meal_name or "",
        "CATEGORY": category or "",
        "SUBCATEGORY": subcategory or "",
        "SERVING_SIZE": meal.serving_size or "",
        "CALORIES_KCAL": meal.calories_kcal,
        "PROTEIN_G": macro.protein_g,
        "CARBOHYDRATES_G": macro.carbohydrates_g,
        "FAT_G": macro.fat_g,
        "FIBER_G": macro.fiber_g,
        "SUGAR_G": macro.sugar_g,
        "SODIUM_MG": micro.sodium_mg if micro else 0,
        "POTASSIUM_MG": micro.potassium_mg if micro else 0,
        "CALCIUM_MG": micro.calcium_mg if micro else 0,
        "IRON_MG": micro.iron_mg if micro else 0,
        "VITAMIN_C_MG": micro.vitamin_c_mg if micro else 0,
        "SOURCE": source,
        "COMMENTS": comments,
    }
