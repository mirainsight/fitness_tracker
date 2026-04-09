"""User-editable food taxonomy (category → subcategories). Mirrors finance-dashboard category_storage."""

from __future__ import annotations

import json
from pathlib import Path
import streamlit as st

from utils.constants import DEFAULT_FOOD_SUBCATEGORIES, paths
from utils.upstash_storage import KEY_FOOD_CATEGORIES, is_upstash_configured, load_from_upstash, save_to_upstash


def load_user_food_categories() -> dict[str, list[str]]:
    """Load user-added categories from Upstash or local JSON."""
    if is_upstash_configured():
        raw = load_from_upstash(KEY_FOOD_CATEGORIES)
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
        path = Path(paths["food_categories_config"])
        if path.exists():
            try:
                with open(path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    path = Path(paths["food_categories_config"])
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_user_food_categories(data: dict[str, list[str]]) -> None:
    raw = json.dumps(data)
    if is_upstash_configured():
        if save_to_upstash(KEY_FOOD_CATEGORIES, raw):
            _write_local_backup(data)
            return
    _write_local_backup(data)


def _write_local_backup(data: dict[str, list[str]]) -> None:
    path = Path(paths["food_categories_config"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def get_effective_food_subcategories() -> dict[str, list[str]]:
    """Merge defaults with user-added (same pattern as get_effective_subcategories)."""
    user = load_user_food_categories()
    effective: dict[str, list[str]] = {}
    all_cats = set(DEFAULT_FOOD_SUBCATEGORIES.keys()) | set(user.keys())
    for cat in sorted(all_cats):
        subs = list(DEFAULT_FOOD_SUBCATEGORIES.get(cat, []))
        for s in user.get(cat, []):
            if s not in subs:
                subs.append(s)
        effective[cat] = subs
    return effective


def get_effective_food_categories() -> list[str]:
    return sorted(get_effective_food_subcategories().keys())


def add_food_category(name: str) -> bool:
    name = name.strip()
    if not name:
        return False
    user = load_user_food_categories()
    if name in user or name in DEFAULT_FOOD_SUBCATEGORIES:
        return False
    user[name] = []
    save_user_food_categories(user)
    return True


def add_food_subcategory(category: str, subcategory: str) -> bool:
    category, subcategory = category.strip(), subcategory.strip()
    if not category or not subcategory:
        return False
    user = load_user_food_categories()
    if category not in DEFAULT_FOOD_SUBCATEGORIES and category not in user:
        user[category] = []
    subs = list(user.get(category, []))
    default_subs = DEFAULT_FOOD_SUBCATEGORIES.get(category, [])
    if subcategory in subs or subcategory in default_subs:
        return False
    subs.append(subcategory)
    user[category] = subs
    save_user_food_categories(user)
    return True
