"""Exercise log storage: Upstash primary, CSV fallback."""

from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from utils.constants import paths

EXERCISE_COLUMNS = ["EXERCISE_DATE", "LOGGED_AT", "EXERCISE_NAME", "CALORIES_BURNED"]
from utils.upstash_storage import KEY_EXERCISES, is_upstash_configured, load_from_upstash, save_to_upstash


def _get_path() -> Path:
    path = Path(paths["exercises_csv"])
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    for col in EXERCISE_COLUMNS:
        if col not in df.columns:
            df[col] = "" if col in ("EXERCISE_DATE", "LOGGED_AT", "EXERCISE_NAME") else 0.0
    for col in EXERCISE_COLUMNS:
        if col in ("EXERCISE_DATE", "LOGGED_AT", "EXERCISE_NAME"):
            df[col] = df[col].fillna("").astype(str)
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    cols = [c for c in EXERCISE_COLUMNS if c in df.columns]
    return df[cols]


def load_exercises() -> pd.DataFrame:
    if is_upstash_configured():
        raw = load_from_upstash(KEY_EXERCISES)
        if raw:
            try:
                return _normalize(pd.read_csv(StringIO(raw)))
            except Exception:
                pass
    path = _get_path()
    if path.exists():
        try:
            return _normalize(pd.read_csv(path))
        except Exception:
            pass
    return pd.DataFrame(columns=EXERCISE_COLUMNS)


def save_exercises(df: pd.DataFrame) -> None:
    df = _normalize(df)
    raw = df.to_csv(index=False)
    if is_upstash_configured():
        save_to_upstash(KEY_EXERCISES, raw)
    _get_path().write_text(raw)
    if hasattr(st, "session_state"):
        st.session_state.pop("_cached_exercises", None)


def exercise_to_row(exercise_date: str, exercise_name: str, calories_burned: float) -> dict[str, Any]:
    return {
        "EXERCISE_DATE": exercise_date,
        "LOGGED_AT": datetime.now().isoformat(timespec="seconds"),
        "EXERCISE_NAME": exercise_name,
        "CALORIES_BURNED": calories_burned,
    }
