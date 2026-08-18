from __future__ import annotations

from difflib import SequenceMatcher, get_close_matches

DEFAULT_CONFIDENCE = 0.70
DEFAULT_DATE_WINDOW_DAYS = 1


def advanced_name_match(name1: str, name2: str) -> float:
    char_sim = SequenceMatcher(None, name1, name2).ratio()

    w1, w2 = name1.split(), name2.split()
    if not w1 or not w2:
        return char_sim

    shorter, longer = (w1, w2) if len(w1) < len(w2) else (w2, w1)
    if len(shorter) < 2:
        return char_sim  # single-word subset matches are too risky

    matched_words = sum(1 for sw in shorter if get_close_matches(sw, longer, n=1, cutoff=0.85))
    ratio = matched_words / len(shorter)

    if ratio == 1.0:
        return max(char_sim, 0.95)
    if ratio >= 0.66 and len(shorter) >= 3:
        return max(char_sim, 0.85)
    return char_sim


def load_mismatched_data(remaining_abr_by_name: dict, remaining_sot_by_name: dict):
    
    return dict(remaining_abr_by_name), dict(remaining_sot_by_name)


def name_comparator(
    remaining_abr_by_name: dict,
    remaining_sot_by_name: dict,
    confidence: float = DEFAULT_CONFIDENCE,
    date_window_days: int = DEFAULT_DATE_WINDOW_DAYS,
):

    abr_names = list(remaining_abr_by_name.keys())
    sot_names = list(remaining_sot_by_name.keys())

    # bucket SoT names by first letter for speed
    by_letter: dict[str, list[str]] = {}
    for sn in sot_names:
        by_letter.setdefault(sn[0] if sn else "", []).append(sn)

    buffer = []
    consumed_abr, consumed_sot = set(), set()

    for an in abr_names:
        candidates = [c for c in by_letter.get(an[0] if an else "", []) if c not in consumed_sot]
        if not candidates:
            continue

        best_score, best_match = 0.0, None
        for cand in candidates:
            score = advanced_name_match(an, cand)
            if score > best_score:
                best_score, best_match = score, cand

        if best_score < confidence or best_match is None:
            continue

        abr_entries = remaining_abr_by_name[an]
        sot_entries = remaining_sot_by_name[best_match]

        # Require amount + date agreement between at least one pair before
        # trusting the name guess -- similarity alone isn't enough.
        confirmed = False
        for a in abr_entries:
            for s in sot_entries:
                if abs(a["Amount"] - s["Amount"]) < 0.01:
                    d1, d2 = a.get("Date"), s.get("Date")
                    try:
                        within_window = abs((d1.normalize() - d2.normalize()).days) <= date_window_days
                    except Exception:
                        within_window = False
                    if within_window:
                        confirmed = True
                        break
            if confirmed:
                break

        if not confirmed:
            continue

        # Rename SoT-side entries to the Abronal name, per spec.
        renamed_sot_entries = []
        for s in sot_entries:
            s = dict(s)
            s["Original_Name"] = abr_entries[0]["Original_Name"]
            s["Norm_Name"] = an
            renamed_sot_entries.append(s)

        buffer.append({
            "abr_name": an,
            "sot_name_original": best_match,
            "similarity": round(best_score * 100, 1),
            "abr_entries": abr_entries,
            "sot_entries": renamed_sot_entries,
        })
        consumed_abr.add(an)
        consumed_sot.add(best_match)

    unreconciled_abr = {n: e for n, e in remaining_abr_by_name.items() if n not in consumed_abr}
    unreconciled_sot = {n: e for n, e in remaining_sot_by_name.items() if n not in consumed_sot}
    return buffer, unreconciled_abr, unreconciled_sot


def grafter(matched_list: list, buffer: list) -> list:
 
    from primary_recon import best_date_pairs, signed_day_difference

    grafted = list(matched_list)
    for group in buffer:
        abr_entries = group["abr_entries"]
        sot_entries = group["sot_entries"]
        pairs = best_date_pairs(abr_entries, sot_entries, same_service_required=False)
        for ai, si in pairs:
            a, s = abr_entries[ai], sot_entries[si]
            grafted.append({
                "abr": a,
                "sot": s,
                "day_diff": signed_day_difference(a["Date"], s["Date"]),
                "spelling_match": True,
                "similarity": group["similarity"],
            })
    return grafted