"""Infer category / subcategory from meal name.

3-tier fallback (mirrors financial_tracker description_inference):
1. Learned mappings  — exact match on names you've corrected before
2. Word-level scoring — generalises from similar meal names you've logged
3. Sheet keywords    — longest MEAL_KEY substring match from FoodMappings tab
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Tuple

import streamlit as st

from utils.constants import paths
from utils.upstash_storage import KEY_MEAL_LEARNED, is_upstash_configured, load_from_upstash, save_to_upstash

_CACHE_LEARNED = "_meal_inference_cache_learned"
_CACHE_WORD_SCORES = "_meal_inference_cache_word_scores"
_CACHE_EFFECTIVE_SUBS = "_meal_inference_cache_effective_subs"

WORD_SCORE_MIN_TOTAL = 2
WORD_SCORE_MIN_OCCURRENCE = 2


def _split_words(text: str) -> list[str]:
    return [w.lower() for w in text.split() if w.strip()]


def _get_effective_subs_cached() -> dict:
    if hasattr(st, "session_state") and _CACHE_EFFECTIVE_SUBS in st.session_state:
        return st.session_state[_CACHE_EFFECTIVE_SUBS]
    from utils.food_category_storage import get_effective_food_subcategories
    effective = get_effective_food_subcategories()
    if hasattr(st, "session_state"):
        st.session_state[_CACHE_EFFECTIVE_SUBS] = effective
    return effective


# ---------------------------------------------------------------------------
# Learned mappings storage (Upstash primary, local JSON fallback)
# ---------------------------------------------------------------------------

def _load_learned_from_storage() -> dict:
    if is_upstash_configured():
        raw = load_from_upstash(KEY_MEAL_LEARNED)
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
    path = Path(paths["inference_learned"])
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_learned_to_storage(learned: dict) -> None:
    raw = json.dumps(learned)
    if is_upstash_configured():
        save_to_upstash(KEY_MEAL_LEARNED, raw)
    path = Path(paths["inference_learned"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(learned, f, indent=2)


def load_learned_mappings() -> dict:
    if hasattr(st, "session_state") and _CACHE_LEARNED in st.session_state:
        return st.session_state[_CACHE_LEARNED]
    learned = _load_learned_from_storage()
    if hasattr(st, "session_state"):
        st.session_state[_CACHE_LEARNED] = learned
    return learned


def save_learned_mapping(meal_name: str, category: str, subcategory: str) -> None:
    if not meal_name or not meal_name.strip():
        return
    learned = load_learned_mappings()
    key = meal_name.lower().strip()
    learned[key] = [category, subcategory]
    _save_learned_to_storage(learned)
    if hasattr(st, "session_state"):
        st.session_state[_CACHE_LEARNED] = learned
    _rebuild_word_scores()


def delete_learned_mapping(meal_name: str) -> bool:
    if not meal_name or not meal_name.strip():
        return False
    learned = load_learned_mappings()
    key = meal_name.lower().strip()
    if key in learned:
        del learned[key]
        _save_learned_to_storage(learned)
        if hasattr(st, "session_state"):
            st.session_state[_CACHE_LEARNED] = learned
        _rebuild_word_scores()
        return True
    return False


# ---------------------------------------------------------------------------
# Word-level scoring
# ---------------------------------------------------------------------------

def _get_word_scores_path() -> Path:
    path = Path(paths["inference_word_scores"])
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_word_scores() -> dict:
    if hasattr(st, "session_state") and _CACHE_WORD_SCORES in st.session_state:
        return st.session_state[_CACHE_WORD_SCORES]
    path = _get_word_scores_path()
    data: dict = {}
    if path.exists():
        try:
            with open(path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    if hasattr(st, "session_state"):
        st.session_state[_CACHE_WORD_SCORES] = data
    return data


def _save_word_scores(word_scores: dict) -> None:
    with open(_get_word_scores_path(), "w") as f:
        json.dump(word_scores, f, indent=2)
    if hasattr(st, "session_state"):
        st.session_state[_CACHE_WORD_SCORES] = word_scores


def _rebuild_word_scores() -> None:
    learned = load_learned_mappings()
    effective = _get_effective_subs_cached()
    word_scores: dict[str, dict[str, dict[str, int]]] = {}
    for name, cat_sub in learned.items():
        if not isinstance(cat_sub, (list, tuple)) or len(cat_sub) < 2:
            continue
        cat, sub = cat_sub[0], cat_sub[1]
        if not cat or not sub or cat not in effective or sub not in effective.get(cat, []):
            continue
        for word in _split_words(name):
            word_scores.setdefault(word, {}).setdefault(cat, {})
            word_scores[word][cat][sub] = word_scores[word][cat].get(sub, 0) + 1
    _save_word_scores(word_scores)


def _infer_from_word_scores(text: str) -> Optional[Tuple[str, str]]:
    word_scores = _load_word_scores()
    words = _split_words(text)
    if not words:
        return None
    scores: dict[tuple, int] = {}
    for word in words:
        if word not in word_scores:
            continue
        for cat, subs in word_scores[word].items():
            for sub, count in subs.items():
                if count >= WORD_SCORE_MIN_OCCURRENCE:
                    key = (cat, sub)
                    scores[key] = scores.get(key, 0) + count
    if not scores:
        return None
    best_key = max(scores, key=scores.__getitem__)
    return best_key if scores[best_key] >= WORD_SCORE_MIN_TOTAL else None


# ---------------------------------------------------------------------------
# Sheet keyword match (Tier 3 — longest MEAL_KEY substring wins)
# ---------------------------------------------------------------------------

def _infer_from_sheet_keywords(meal_name: str, mappings: dict[str, list[str]]) -> Optional[Tuple[str, str]]:
    if not meal_name or not mappings:
        return None
    lower = meal_name.strip().lower()
    best_cat, best_sub = "", ""
    best_len = -1
    for key, val in mappings.items():
        if not key or not isinstance(val, (list, tuple)) or len(val) < 2:
            continue
        k = str(key).lower().strip()
        if not k or k not in lower:
            continue
        if len(k) > best_len:
            best_len = len(k)
            best_cat, best_sub = str(val[0]).strip(), str(val[1]).strip()
    return (best_cat, best_sub) if best_cat and best_sub else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def infer_meal_category(
    meal_name: str, mappings: dict[str, list[str]]
) -> Optional[Tuple[str, tuple]]:
    """
    3-tier inference. Returns (source, (category, subcategory)) or None.
    source is one of: 'learned', 'word_scores', 'sheet'
    """
    if not meal_name or not meal_name.strip():
        return None
    text = meal_name.lower().strip()
    effective = _get_effective_subs_cached()

    # Tier 1: learned mappings (exact match)
    learned = load_learned_mappings()
    if text in learned:
        cat, sub = learned[text]
        if cat in effective and sub in effective.get(cat, []):
            return ("learned", (cat, sub))

    # Tier 2: word-level scoring
    word_result = _infer_from_word_scores(text)
    if word_result:
        return ("word_scores", word_result)

    # Tier 3: sheet keyword rules
    sheet_result = _infer_from_sheet_keywords(meal_name, mappings)
    if sheet_result:
        return ("sheet", sheet_result)

    return None


def invalidate_inference_cache() -> None:
    if hasattr(st, "session_state"):
        for key in (_CACHE_LEARNED, _CACHE_WORD_SCORES, _CACHE_EFFECTIVE_SUBS):
            st.session_state.pop(key, None)


def save_learned_mappings_bulk(learned: dict) -> None:
    _save_learned_to_storage(learned)
    if hasattr(st, "session_state"):
        st.session_state[_CACHE_LEARNED] = learned
    _rebuild_word_scores()


# Keep old name as alias so any other callers don't break
def infer_food_category_subcategory(meal_name: str, mappings: dict[str, list[str]]) -> tuple[str, str]:
    result = _infer_from_sheet_keywords(meal_name, mappings)
    return result if result else ("", "")
