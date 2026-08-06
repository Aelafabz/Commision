"""String normalization and fuzzy matching helpers."""

from __future__ import annotations

import re

import pandas as pd
from difflib import SequenceMatcher, get_close_matches


def normalize_string(s) -> str:
    if not isinstance(s, str):
        return ""
    s = s.upper()
    s = re.sub(r"[^A-Z0-9\s]", "", s)
    return " ".join(s.split())


def parse_abronal_date(s):
    if not isinstance(s, str):
        return pd.NaT
    s_clean = (
        s.replace(":AM", " AM")
        .replace(":PM", " PM")
        .replace(":am", " AM")
        .replace(":pm", " PM")
    )
    return pd.to_datetime(s_clean, errors="coerce")


def advanced_name_match(name1: str, name2: str) -> float:
    """Return similarity score 0.0–1.0 with word-subset handling."""
    char_sim = SequenceMatcher(None, name1, name2).ratio()
    w1 = name1.split()
    w2 = name2.split()
    if not w1 or not w2:
        return char_sim

    shorter, longer = (w1, w2) if len(w1) < len(w2) else (w2, w1)
    if len(shorter) < 2:
        return char_sim

    matched_words = sum(
        1 for sw in shorter if get_close_matches(sw, longer, n=1, cutoff=0.85)
    )
    word_match_ratio = matched_words / len(shorter)
    if word_match_ratio == 1.0:
        return max(char_sim, 0.95)
    if word_match_ratio >= 0.66 and len(shorter) >= 3:
        return max(char_sim, 0.85)
    return char_sim


def date_distance_days(date1, date2) -> int:
    if pd.isna(date1) or pd.isna(date2):
        return 999_999
    return abs((date1.normalize() - date2.normalize()).days)


def signed_day_difference(date1, date2):
    if pd.isna(date1) or pd.isna(date2):
        return "N/A"
    return (date1.normalize() - date2.normalize()).days


def best_date_pairs(abr_entries, sot_entries, same_service_required=True):
    """Pair duplicate candidates by closest dates."""
    candidates = []
    for ai, a in enumerate(abr_entries):
        for si, s in enumerate(sot_entries):
            if same_service_required and a["Norm_Service"] != s["Norm_Service"]:
                continue
            if abs(a["Amount"] - s["Amount"]) >= 0.01:
                continue
            candidates.append((date_distance_days(a["Date"], s["Date"]), ai, si))

    candidates.sort()
    matched_abr: set[int] = set()
    matched_sot: set[int] = set()
    pairs = []
    for _, ai, si in candidates:
        if ai in matched_abr or si in matched_sot:
            continue
        matched_abr.add(ai)
        matched_sot.add(si)
        pairs.append((ai, si))
    return pairs


def secondary_name_confidence(
    abr_entry: dict,
    sot_entry: dict,
    *,
    name_threshold: float = 0.70,
    date_tolerance_days: int = 1,
) -> tuple[bool, float]:
    """
    Secondary matcher: name similarity >= threshold, matching amount,
    and visit dates within ±date_tolerance_days.
    """
    score = advanced_name_match(abr_entry["Norm_Name"], sot_entry["Norm_Name"])
    if score < name_threshold:
        return False, score
    if abs(abr_entry["Amount"] - sot_entry["Amount"]) >= 0.01:
        return False, score
    if date_distance_days(abr_entry["Date"], sot_entry["Date"]) > date_tolerance_days:
        return False, score
    return True, score
