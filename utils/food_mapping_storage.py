"""Food name → category / subcategory mappings. Mirrors finance-dashboard mapping_storage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import streamlit as st

from utils.constants import DEFAULT_SPREADSHEET_ID, DEFAULT_FOOD_MAPPINGS_WORKSHEET, paths
from utils.upstash_storage import KEY_FOOD_MAPPINGS, is_upstash_configured, load_from_upstash, save_to_upstash


def _spreadsheet_id() -> str:
    try:
        if hasattr(st, "secrets") and st.secrets:
            sid = st.secrets.get("FITNESS_SPREADSHEET_ID") or getattr(st.secrets, "FITNESS_SPREADSHEET_ID", None)
            if sid:
                return str(sid).strip()
    except Exception:
        pass
    return (DEFAULT_SPREADSHEET_ID or "").strip()


def _mappings_worksheet_title() -> str:
    try:
        if hasattr(st, "secrets") and st.secrets:
            w = st.secrets.get("FITNESS_FOOD_MAPPINGS_WORKSHEET") or st.secrets.get(
                "fitness_food_mappings_worksheet"
            )
            if w:
                return str(w).strip()
    except Exception:
        pass
    return DEFAULT_FOOD_MAPPINGS_WORKSHEET


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
            creds_file = st.secrets.get("GOOGLE_SHEETS_CREDENTIALS_FILE")
            if creds_file:
                with open(creds_file) as f:
                    creds = json.load(f)
        if creds and (creds.get("type") == "service_account" if isinstance(creds, dict) else True):
            return {"spreadsheet_id": spreadsheet_id, "credentials": creds}
    except Exception:
        pass
    return None


def _row_key_cat_sub(row: dict[str, Any]) -> Optional[tuple[str, str, str]]:
    """Pick (meal_key, category, subcategory) from flexible column headers."""
    keys_ci = {str(k).strip().lower(): k for k in row}

    def get_ci(*candidates: str) -> str:
        for c in candidates:
            lk = c.lower()
            if lk in keys_ci:
                return str(row[keys_ci[lk]] or "").strip()
        return ""

    meal_key = get_ci(
        "meal_key",
        "keyword",
        "food_key",
        "key",
        "description",
        "food",
        "name_pattern",
    )
    cat = get_ci("category", "food_category", "food_type", "type")
    sub = get_ci("subcategory", "food_subcategory", "subtype", "sub_type", "food_subtype")
    if meal_key and cat and sub:
        return (meal_key, cat, sub)
    return None


def _load_from_gsheets() -> Optional[dict[str, list[str]]]:
    """Return mapping dict keyed by meal_key.lower() -> [category, subcategory]."""
    config = _get_gsheets_config()
    if not config:
        return None
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds = Credentials.from_service_account_info(
            config["credentials"],
            scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"],
        )
        gc = gspread.authorize(creds)
        spreadsheet = gc.open_by_key(config["spreadsheet_id"])
        title = _mappings_worksheet_title()
        try:
            worksheet = spreadsheet.worksheet(title)
        except gspread.WorksheetNotFound:
            return {}

        records = worksheet.get_all_records()
        learned: dict[str, list[str]] = {}
        for row in records:
            parsed = _row_key_cat_sub(row)
            if not parsed:
                continue
            key, cat, sub = parsed
            learned[key.lower()] = [cat, sub]
        return learned
    except Exception as e:
        if hasattr(st, "session_state"):
            st.session_state["_food_mappings_gsheets_error"] = f"{type(e).__name__}: {e}"
        return None


def load_food_mappings_from_storage() -> dict[str, list[str]]:
    """Upstash primary; seed from GSheets tab or local JSON (finance mapping_storage pattern)."""
    if is_upstash_configured():
        raw = load_from_upstash(KEY_FOOD_MAPPINGS)
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
        learned = _load_from_gsheets()
        if learned is not None and learned:
            save_food_mappings_to_storage(learned)
            return learned
        path = Path(paths["food_mappings_local"])
        if path.exists():
            try:
                with open(path) as f:
                    local = json.load(f)
                if local:
                    save_food_mappings_to_storage(local)
                    return local
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    learned = _load_from_gsheets()
    if learned is not None:
        return learned
    path = Path(paths["food_mappings_local"])
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_food_mappings_to_storage(learned: dict[str, list[str]]) -> None:
    if is_upstash_configured():
        if save_to_upstash(KEY_FOOD_MAPPINGS, json.dumps(learned)):
            _write_local_mappings(learned)
            _bust_mapping_cache()
            return
    _write_local_mappings(learned)
    _bust_mapping_cache()


def _bust_mapping_cache() -> None:
    try:
        from utils.meal_streamlit_cache import invalidate_food_mapping_caches

        invalidate_food_mapping_caches()
    except Exception:
        pass


def _write_local_mappings(data: dict[str, list[str]]) -> None:
    path = Path(paths["food_mappings_local"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def force_load_food_mappings_from_gsheets() -> tuple[bool, str]:
    if not _get_gsheets_config():
        return False, "Google Sheets not configured"
    learned = _load_from_gsheets()
    if learned is None:
        return False, "Failed to load mappings tab (check tab name in FITNESS_FOOD_MAPPINGS_WORKSHEET)"
    save_food_mappings_to_storage(learned)
    return True, f"Loaded {len(learned)} food mappings from the sheet"


def is_food_mappings_gsheets_configured() -> bool:
    return _get_gsheets_config() is not None
