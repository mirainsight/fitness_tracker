"""Infer CATEGORY / SUBCATEGORY from meal name using sheet-backed mappings (like description_inference)."""

from __future__ import annotations


def infer_food_category_subcategory(meal_name: str, mappings: dict[str, list[str]]) -> tuple[str, str]:
    """
    Longest ``meal_key`` substring match wins (case-insensitive).

    ``mappings``: ``{ "keyword_lower": [category, subcategory], ... }``
    """
    if not meal_name or not mappings:
        return "", ""
    lower = meal_name.strip().lower()
    best_cat, best_sub = "", ""
    best_len = -1
    for key, val in mappings.items():
        if not key or not isinstance(val, (list, tuple)) or len(val) < 2:
            continue
        k = str(key).lower().strip()
        if not k:
            continue
        if k not in lower:
            continue
        if len(k) > best_len:
            best_len = len(k)
            best_cat, best_sub = str(val[0]).strip(), str(val[1]).strip()
    return best_cat, best_sub
