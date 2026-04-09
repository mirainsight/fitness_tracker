"""Upstash Redis: primary store; Google Sheets sync on demand."""

from pathlib import Path
from typing import Optional

import streamlit as st

from utils.constants import paths

KEY_MEALS = "fitness:meals"
KEY_TARGETS = "fitness:daily_targets"
KEY_LAST_GSHEETS_SYNC = "fitness:last_gsheets_sync"
KEY_FOOD_MAPPINGS = "fitness:food_mappings"
KEY_FOOD_CATEGORIES = "fitness:food_categories"


def _get_upstash_creds():
    try:
        if not hasattr(st, "secrets") or not st.secrets:
            return None, None
        s = st.secrets
        url = (
            s.get("UPSTASH_REDIS_REST_URL")
            or s.get("upstash_redis_rest_url")
            or getattr(s, "UPSTASH_REDIS_REST_URL", None)
        )
        token = (
            s.get("UPSTASH_REDIS_REST_TOKEN")
            or s.get("upstash_redis_rest_token")
            or getattr(s, "UPSTASH_REDIS_REST_TOKEN", None)
        )
        if (not url or not token) and hasattr(s, "get"):
            upstash = s.get("upstash") or getattr(s, "upstash", None)
            if upstash:
                up = upstash if hasattr(upstash, "get") else {}
                url = url or up.get("redis_rest_url") or up.get("upstash_redis_rest_url") or getattr(
                    upstash, "redis_rest_url", None
                )
                token = token or up.get("redis_rest_token") or up.get("upstash_redis_rest_token") or getattr(
                    upstash, "redis_rest_token", None
                )
        return (url, token) if (url and token) else (None, None)
    except Exception:
        return None, None


def _get_upstash_client():
    url, token = _get_upstash_creds()
    if not url or not token:
        return None
    try:
        from upstash_redis import Redis

        return Redis(url=str(url), token=str(token))
    except Exception:
        return None


def is_upstash_configured() -> bool:
    return _get_upstash_client() is not None


def load_from_upstash(key: str) -> Optional[str]:
    client = _get_upstash_client()
    if not client:
        return None
    try:
        val = client.get(key)
        return val if val is not None else None
    except Exception:
        return None


def save_to_upstash(key: str, value: str) -> bool:
    client = _get_upstash_client()
    if not client:
        return False
    try:
        client.set(key, value)
        return True
    except Exception:
        return False


def get_last_gsheets_sync() -> str:
    val = load_from_upstash(KEY_LAST_GSHEETS_SYNC)
    if val:
        return val
    path = Path(paths.get("last_gsheets_sync", "data/last_gsheets_sync.txt"))
    if path.exists():
        try:
            return path.read_text().strip() or "Never"
        except Exception:
            pass
    return "Never"


def save_last_gsheets_sync(value: str) -> bool:
    ok = False
    if is_upstash_configured():
        ok = save_to_upstash(KEY_LAST_GSHEETS_SYNC, value)
    path = Path(paths.get("last_gsheets_sync", "data/last_gsheets_sync.txt"))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
        ok = True
    except Exception:
        pass
    return ok


def test_upstash_connection() -> tuple[bool, str]:
    if not hasattr(st, "secrets") or not st.secrets:
        return False, "st.secrets is missing or empty"
    client = _get_upstash_client()
    if not client:
        url, token = _get_upstash_creds()
        if not url:
            return False, "UPSTASH_REDIS_REST_URL not found in secrets"
        if not token:
            return False, "UPSTASH_REDIS_REST_TOKEN not found in secrets"
        return False, "Could not create Upstash client (check URL/token)"

    test_key = "fitness:_test_connection"
    test_val = "ok"
    try:
        client.set(test_key, test_val)
        got = client.get(test_key)
        if got == test_val:
            client.delete(test_key)
            return True, "Upstash OK"
        return False, f"Read-back mismatch: {got!r}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
