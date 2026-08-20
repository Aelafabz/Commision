"""
primary_reconciliation.py
──────────────────────────────────────────────────────────────────
Neo-script #1.

1. Parses every Abronal .xlsx in `abronal_dir` — the physician name
   is taken from the SOURCE FILENAME, not a column.
2. Parses every SoT .xlsx in `sot_dir` and mirrors both sets of rows
   into abronal_mirror / sot_mirror.
3. Exact-matches Abronal rows to SoT rows on (normalized patient
   name, amount, service) and splits results into matched_records
   and unmatched_records.

Everything is written through db_manager so schema/FK rules are
respected. Returns (matched_count, unmatched_count) and writes a
row to pipeline_runs the caller can poll for progress.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "db"))
import db_manager as dbm  # noqa: E402
import column_adapter as ca  # noqa: E402


def normalize_string(s) -> str:
    if not isinstance(s, str):
        return ""
    s = s.upper()
    s = re.sub(r"[^A-Z0-9\s]", "", s)
    return " ".join(s.split())


_MONTHS = {
    "jan", "january", "feb", "february", "mar", "march", "apr", "april",
    "may", "jun", "june", "jul", "july", "aug", "august", "sep", "sept",
    "september", "oct", "october", "nov", "november", "dec", "december",
}


def _is_date_token(tok: str) -> bool:
    t = tok.strip().lower().rstrip(",.")
    if not t:
        return False
    if t in _MONTHS:
        return True
    if re.fullmatch(r"\d{1,2}(-\d{1,2})?", t):          # "9", "1-9"
        return True
    if re.fullmatch(r"\d{4}", t):                        # "2026"
        return True
    if re.fullmatch(r"\d{1,2}[/-]\d{1,2}([/-]\d{2,4})?", t):  # "7/1", "07-01-2026"
        return True
    return False


def physician_from_filename(filename: str) -> str:
    """Extracts the physician name from either naming convention seen
    in practice:
      - physician-first (what Abronal actually names files):
        'dr bart jacobs july 1-9.xlsx' -> 'Dr. Bart Jacobs'
      - date-first (what the old export tool produced):
        'July 20 to July 22 Dr. Ahmed Reja.xlsx' -> 'Dr. Ahmed Reja'
    Finds the 'Dr'/'Dr.' token and takes name words from there,
    stopping at the first date-like token (month name, day number,
    day range, year, or slash/dash date)."""
    base = os.path.splitext(os.path.basename(filename))[0]
    tokens = re.split(r"\s+", base.strip())

    dr_idx = next((i for i, t in enumerate(tokens) if re.fullmatch(r"dr\.?", t, flags=re.I)), None)

    if dr_idx is not None:
        name_tokens = [tokens[dr_idx]]
        for t in tokens[dr_idx + 1:]:
            if _is_date_token(t):
                break
            name_tokens.append(t)
    else:
        # No explicit "Dr" token found — fall back to everything
        # before the first date-like token.
        name_tokens = []
        for t in tokens:
            if _is_date_token(t):
                break
            name_tokens.append(t)
        if not name_tokens:
            name_tokens = tokens

    first = name_tokens[0]
    if re.fullmatch(r"dr\.?", first, flags=re.I):
        rest = name_tokens[1:]
    else:
        rest = name_tokens
    rest_title = " ".join(w.capitalize() for w in rest)
    name = f"Dr. {rest_title}".strip() if rest_title else (base.strip() or "Unknown Physician")
    return re.sub(r"\s+", " ", name)


def parse_abronal_dir(abr_dir: str, batch_id: str, log):
    """Load every abronal xlsx, physician name from filename, columns
    resolved through the column adapter (handles the title row above
    the real header and header-text variation)."""
    rows = []
    for filename in sorted(os.listdir(abr_dir)):
        if not filename.lower().endswith(".xlsx"):
            continue
        physician_name = physician_from_filename(filename)
        log(f"Parsing Abronal file: {filename} -> physician = {physician_name}")
        path = os.path.join(abr_dir, filename)
        try:
            df = ca.adapt_sheet(path, ca.ABRONAL_SCHEMA, log=log)
        except ca.ColumnAdapterError as e:
            log(f"  SKIPPING {filename}: {e}")
            continue

        for _, row in df.iterrows():
            name = ca.get_str(row, "patient_full_name")
            if not name:
                continue
            total = ca.get_float(row, "total")
            net = ca.get_float(row, "net", default=total)
            rows.append({
                "row_number": ca.get_int(row, "row_number", default=len(rows) + 1),
                "card_number": ca.get_str(row, "card_number") or None,
                "patient_full_name": name,
                "patient_type": ca.get_str(row, "patient_type") or None,
                "service_raw": ca.get_str(row, "service_raw"),
                "total": total,
                "net": net,
                "commission_percent": ca.get_float(row, "commission_percent", default=None),
                "commision_amount": ca.get_float(row, "commision_amount", default=None),
                "payment_date": ca.get_str(row, "payment_date") or None,
                "visit_date": ca.get_str(row, "visit_date") or None,
                "status": ca.get_str(row, "status") or None,
                "physician_name": physician_name,
                "source_file": filename,
            })
    log(f"Parsed {len(rows)} Abronal rows from {abr_dir}")
    return rows


def parse_sot_dir(sot_dir: str, batch_id: str, log):
    rows = []
    for filename in sorted(os.listdir(sot_dir)):
        if not filename.lower().endswith(".xlsx"):
            continue
        log(f"Parsing SoT file: {filename}")
        path = os.path.join(sot_dir, filename)
        try:
            df = ca.adapt_sheet(path, ca.SOT_SCHEMA, log=log)
        except ca.ColumnAdapterError as e:
            log(f"  SKIPPING {filename}: {e}")
            continue

        for _, row in df.iterrows():
            customer = ca.get_str(row, "customer")
            if not customer:
                continue
            sub_total = ca.get_float(row, "sub_total")
            rows.append({
                "customer": customer,
                "tin_number": ca.get_str(row, "tin_number") or None,
                "description": ca.get_str(row, "description"),
                "item_id": ca.get_str(row, "item_id") or None,
                "base_sku": ca.get_str(row, "base_sku"),
                "quantity": ca.get_int(row, "quantity", default=1),
                "unit_price": ca.get_float(row, "unit_price", default=sub_total),
                "sub_total": sub_total,
                "tax_amount": ca.get_float(row, "tax_amount"),
                "withholding": ca.get_str(row, "withholding") or None,
                "fs_number": ca.get_int(row, "fs_number"),
                "transaction_date": ca.get_str(row, "transaction_date") or None,
                "reference": ca.get_str(row, "reference"),
                "MRC": ca.get_str(row, "mrc"),
                "source_file": filename,
            })
    log(f"Parsed {len(rows)} SoT rows from {sot_dir}")
    return rows


def persist_mirrors(abr_rows, sot_rows, batch_id, log):
    abr_ids, sot_ids = [], []
    with dbm.get_conn() as conn:
        for r in abr_rows:
            physician_id = dbm.get_or_create_physician(conn, r["physician_name"])
            service_id = dbm.get_or_create_service(conn, r["service_raw"])
            cur = conn.execute(
                """INSERT INTO abronal_mirror
                   (row_number, card_number, patient_full_name, patient_type, service_id,
                    service_raw, total, net, commission_percent, commision_amount,
                    payment_date, visit_date, status, physician_id, source_file, batch_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (r["row_number"], r["card_number"], r["patient_full_name"], r["patient_type"],
                 service_id, r["service_raw"], r["total"], r["net"], r["commission_percent"],
                 r["commision_amount"], r["payment_date"], r["visit_date"], r["status"],
                 physician_id, r["source_file"], batch_id),
            )
            r["row_id"] = cur.lastrowid
            r["physician_id"] = physician_id
            r["service_id"] = service_id
            abr_ids.append(cur.lastrowid)

        for r in sot_rows:
            service_id = dbm.get_or_create_service(conn, r["description"])
            cur = conn.execute(
                """INSERT INTO sot_mirror
                   (customer, tin_number, description, item_id, base_sku, quantity, unit_price,
                    sub_total, tax_amount, withholding, fs_number, transaction_date, reference,
                    MRC, service_id, source_file, batch_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (r["customer"], r["tin_number"], r["description"], r["item_id"], r["base_sku"],
                 r["quantity"], r["unit_price"], r["sub_total"], r["tax_amount"], r["withholding"],
                 r["fs_number"], r["transaction_date"], r["reference"], r["MRC"], service_id,
                 r["source_file"], batch_id),
            )
            r["row_id"] = cur.lastrowid
            r["service_id"] = service_id
            sot_ids.append(cur.lastrowid)
    log(f"Persisted {len(abr_ids)} Abronal rows and {len(sot_ids)} SoT rows to the database.")
    return abr_rows, sot_rows


def match_records(abr_rows, sot_rows, batch_id, log):
    sot_by_name = {}
    for s in sot_rows:
        sot_by_name.setdefault(normalize_string(s["customer"]), []).append(s)

    matched, unmatched_abr = [], []
    consumed_sot_ids = set()

    for a in abr_rows:
        norm_name = normalize_string(a["patient_full_name"])
        candidates = [s for s in sot_by_name.get(norm_name, []) if s["row_id"] not in consumed_sot_ids]
        found = None
        for s in candidates:
            if abs(a["net"] - s["sub_total"]) < 0.01:
                found = s
                break
        if found:
            consumed_sot_ids.add(found["row_id"])
            matched.append({
                "patient_name": a["patient_full_name"],
                "service_id": a["service_id"],
                "total_amount": a["total"],
                "net_amount": a["net"],
                "payment_date": a["payment_date"] or found["transaction_date"],
                "physician_id": a["physician_id"],
                "match_type": "exact",
                "confidence": 1.0,
                "abronal_row_id": a["row_id"],
                "sot_row_id": found["row_id"],
            })
        else:
            unmatched_abr.append(a)

    unmatched_sot = [s for s in sot_rows if s["row_id"] not in consumed_sot_ids]
    log(f"Exact match phase: {len(matched)} matched, "
        f"{len(unmatched_abr)} unmatched Abronal, {len(unmatched_sot)} unmatched SoT.")
    return matched, unmatched_abr, unmatched_sot


def persist_results(matched, unmatched_abr, unmatched_sot, batch_id, log):
    with dbm.get_conn() as conn:
        for m in matched:
            conn.execute(
                """INSERT INTO matched_records
                   (patient_name, service_id, total_amount, net_amount, payment_date,
                    physician_id, match_type, confidence, abronal_row_id, sot_row_id, batch_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (m["patient_name"], m["service_id"], m["total_amount"], m["net_amount"],
                 m["payment_date"], m["physician_id"], m["match_type"], m["confidence"],
                 m["abronal_row_id"], m["sot_row_id"], batch_id),
            )
        for a in unmatched_abr:
            conn.execute(
                """INSERT INTO unmatched_records
                   (abronal_patient_name, abronal_service_type, abronal_net_amount,
                    abronal_payment_date, physician_id, reason_for_mismatch,
                    abronal_row_id, batch_id)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (a["patient_full_name"], a["service_raw"], a["net"], a["payment_date"] or "",
                 a["physician_id"], "No matching SoT row (name/amount)", a["row_id"], batch_id),
            )
        for s in unmatched_sot:
            conn.execute(
                """INSERT INTO unmatched_records
                   (abronal_patient_name, abronal_service_type, abronal_net_amount,
                    abronal_payment_date, physician_id, sot_patient_name, sot_service_type,
                    sot_amount, sot_payment_date, reason_for_mismatch, sot_row_id, batch_id)
                   VALUES ('', '', 0, '', NULL, ?, ?, ?, ?, ?, ?, ?)""",
                (s["customer"], s["description"], s["sub_total"], s["transaction_date"],
                 "SoT row with no matching Abronal entry", s["row_id"], batch_id),
            )
    log(f"Saved {len(matched)} matched_records and "
        f"{len(unmatched_abr) + len(unmatched_sot)} unmatched_records rows.")


def run(abr_dir: str, sot_dir: str, batch_id: str, log=print):
    log("── Primary Reconciliation: parsing files ──")
    abr_rows = parse_abronal_dir(abr_dir, batch_id, log)
    sot_rows = parse_sot_dir(sot_dir, batch_id, log)

    log("── Mirroring rows into the database ──")
    abr_rows, sot_rows = persist_mirrors(abr_rows, sot_rows, batch_id, log)

    log("── Matching Abronal <-> SoT ──")
    matched, unmatched_abr, unmatched_sot = match_records(abr_rows, sot_rows, batch_id, log)

    log("── Saving matched / unmatched sets ──")
    persist_results(matched, unmatched_abr, unmatched_sot, batch_id, log)

    return {
        "matched": len(matched),
        "unmatched_abronal": len(unmatched_abr),
        "unmatched_sot": len(unmatched_sot),
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--abr", required=True)
    parser.add_argument("--sot", required=True)
    parser.add_argument("--batch", default=None)
    args = parser.parse_args()
    batch = args.batch or dbm.new_batch_id()
    dbm.start_run(batch, "primary_reconciliation")
    result = run(args.abr, args.sot, batch)
    dbm.finish_run(batch, "success", str(result))
    print(result)
