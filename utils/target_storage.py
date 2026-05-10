"""Daily nutrition targets (budget analogue): Upstash + Misc tab JSON."""

import json
from pathlib import Path
from typing import Any, Optional

import streamlit as st

from utils.constants import DEFAULT_SPREADSHEET_ID, MISC_WORKSHEET_NAME, paths
from utils.upstash_storage import KEY_TARGETS, is_upstash_configured, load_from_upstash, save_to_upstash


def _spreadsheet_id() -> str:
    try:
        if hasattr(st, "secrets") and st.secrets:
            sid = st.secrets.get("FITNESS_SPREADSHEET_ID") or getattr(st.secrets, "FITNESS_SPREADSHEET_ID", None)
            if sid:
                return str(sid).strip()
    except Exception:
        pass
    return (DEFAULT_SPREADSHEET_ID or "").strip()


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


def _default_targets() -> dict[str, Any]:
    return {
        "calories_kcal": 2000,
        "protein_g": 120,
        "carbohydrates_g": 200,
        "fat_g": 65,
        "fiber_g": 30,
        "sodium_mg_max": 2300,
        "base_calories_burned": 0,
    }


def _load_local_file() -> dict[str, Any]:
    path = Path(paths["targets_json"])
    if not path.exists():
        return _default_targets()
    try:
        data = json.loads(path.read_text())
        out = _default_targets()
        out.update({k: v for k, v in data.items() if k in out})
        return out
    except Exception:
        return _default_targets()


def _save_local_file(data: dict[str, Any]) -> None:
    path = Path(paths["targets_json"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def _load_from_gsheets() -> Optional[dict]:
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
        try:
            ws = spreadsheet.worksheet(MISC_WORKSHEET_NAME)
        except gspread.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(MISC_WORKSHEET_NAME, rows=50, cols=5)
        cell = ws.acell("A1")
        val = cell.value if cell else None
        if not val or not str(val).strip():
            return _default_targets()
        data = json.loads(val)
        out = _default_targets()
        out.update({k: v for k, v in data.items() if k in out})
        return out
    except Exception:
        return None


def _save_to_gsheets(data: dict[str, Any]) -> bool:
    config = _get_gsheets_config()
    if not config:
        return False
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds = Credentials.from_service_account_info(
            config["credentials"],
            scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"],
        )
        gc = gspread.authorize(creds)
        spreadsheet = gc.open_by_key(config["spreadsheet_id"])
        try:
            ws = spreadsheet.worksheet(MISC_WORKSHEET_NAME)
        except gspread.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(MISC_WORKSHEET_NAME, rows=50, cols=5)
        ws.update("A1", json.dumps(data), value_input_option="RAW")
        return True
    except Exception:
        return False


def load_targets() -> dict[str, Any]:
    if is_upstash_configured():
        raw = load_from_upstash(KEY_TARGETS)
        if raw:
            try:
                data = json.loads(raw)
                out = _default_targets()
                out.update({k: v for k, v in data.items() if k in out})
                return out
            except Exception:
                pass
        g = _load_from_gsheets()
        if g:
            save_targets(g)
            return g
        return _load_local_file()

    if _get_gsheets_config():
        g = _load_from_gsheets()
        if g:
            return g
    return _load_local_file()


def save_targets(data: dict[str, Any]) -> None:
    out = _default_targets()
    for k in out:
        if k not in data:
            continue
        try:
            out[k] = float(data[k])
        except (TypeError, ValueError):
            pass
    # preserve any extra keys not in defaults
    for k, v in data.items():
        if k not in out:
            out[k] = v
    if is_upstash_configured():
        if save_to_upstash(KEY_TARGETS, json.dumps(out)):
            _save_local_file(out)
            return
    if _get_gsheets_config():
        _save_to_gsheets(out)
    _save_local_file(out)


def force_sync_targets_to_gsheets(data: dict[str, Any]) -> tuple[bool, str]:
    if not _get_gsheets_config():
        return False, "Google Sheets not configured"
    ok = _save_to_gsheets(data)
    return (True, "Targets synced to Misc!A1") if ok else (False, "GSheets write failed")
