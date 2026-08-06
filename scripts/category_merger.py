"""
Category merger: condense individual service rows into per-doctor category
totals (with an optional per-date breakdown) and apply a commission rate
looked up from configs/commission.json.

The Condensor class is designed to run on both fully reconciled and partially
unreconciled datasets.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

try:
    from service_analyzer import COLUMN_ORDER, DEFAULT_CATEGORIES, reorder_columns
except ImportError:
    COLUMN_ORDER = [
        "Consultation",
        "Laboratory",
        "X-ray",
        "Ultrasound",
        "ECG",
        "Echocardiography",
        "Nursing & Procedures",
        "Supplies",
    ]
    DEFAULT_CATEGORIES = {}

    def reorder_columns(pivot):
        ordered = [c for c in COLUMN_ORDER if c in pivot.columns]
        extras = [c for c in pivot.columns if c not in COLUMN_ORDER and c != "TOTAL"]
        total = ["TOTAL"] if "TOTAL" in pivot.columns else []
        return pivot[ordered + extras + total]


DEFAULT_DICTIONARY = PROJECT_ROOT / "configs" / "dictionary.json"
DEFAULT_COMMISSION_CONFIG = PROJECT_ROOT / "configs" / "commission.json"


class Condensor:
    """
    Read service categories, load transaction rows, and produce per-doctor
    category summaries with an applied commission rate.
    """

    def __init__(
        self,
        dictionary_path: str | Path | None = None,
        commission_path: str | Path | None = None,
    ):
        self.dictionary_path = Path(dictionary_path or DEFAULT_DICTIONARY)
        self.commission_path = Path(commission_path or DEFAULT_COMMISSION_CONFIG)
        self.category_map: dict[str, str] = {}
        self.commission_map: dict[str, float] = {}
        self.data: pd.DataFrame = pd.DataFrame()
        self.buffer: pd.DataFrame = pd.DataFrame()

    # ------------------------------------------------------------------ #
    # Config loading
    # ------------------------------------------------------------------ #
    def read_dictionary(self, path: str | Path | None = None) -> dict[str, str]:
        """Load service→category mapping from JSON."""
        dict_path = Path(path or self.dictionary_path)
        if not dict_path.exists():
            self.category_map = dict(DEFAULT_CATEGORIES)
            return self.category_map

        with dict_path.open(encoding="utf-8") as f:
            raw = json.load(f)
        self.category_map = {str(k): str(v) for k, v in raw.items()}
        self.category_map.update(DEFAULT_CATEGORIES)
        return self.category_map

    def read_commission_config(self, path: str | Path | None = None) -> dict[str, float]:
        """
        Load per-doctor commission rates from JSON.

        Expected shape:
            { "Dr. Jane Doe": 10, "Dr. John Roe": 7.5, "default": 5 }

        Values are treated as percentages (10 == 10%). Missing file, an
        unparsable file, or a doctor not present (and no "default" key)
        simply means that doctor's commission stays null downstream - this
        never raises.
        """
        conf_path = Path(path or self.commission_path)
        if not conf_path.exists():
            self.commission_map = {}
            return self.commission_map

        try:
            with conf_path.open(encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError):
            self.commission_map = {}
            return self.commission_map

        self.commission_map = {str(k): float(v) for k, v in raw.items() if v is not None}
        return self.commission_map

    def _commission_pct_for(self, doctor: str) -> float | None:
        if doctor in self.commission_map:
            return self.commission_map[doctor]
        return self.commission_map.get("default")

    # ------------------------------------------------------------------ #
    # Data loading
    # ------------------------------------------------------------------ #
    def load_data(
        self,
        source: str | Path | pd.DataFrame,
        *,
        buffer: str | Path | pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """
        Load main dataset from Excel path or DataFrame.

        Expected columns (aliases accepted):
          Doctor Name, Service, Amount, SoT Date (or Abronal Date / Date)
        """
        if isinstance(source, pd.DataFrame):
            self.data = source.copy()
        else:
            path = Path(source)
            if path.suffix.lower() == ".json":
                state = json.loads(path.read_text(encoding="utf-8"))
                rows = state.get("matched_rows", [])
                self.data = pd.DataFrame(rows)
            else:
                self.data = self._read_excel_workbook(path)

        if buffer is not None:
            if isinstance(buffer, pd.DataFrame):
                self.buffer = buffer.copy()
            else:
                buf_path = Path(buffer)
                if buf_path.exists():
                    self.buffer = self._read_excel_workbook(buf_path)
                else:
                    self.buffer = pd.DataFrame()

        self._normalize_columns()
        return self.data

    def _read_excel_workbook(self, path: Path) -> pd.DataFrame:
        xl = pd.ExcelFile(path)
        frames = []
        for sheet in xl.sheet_names:
            df = pd.read_excel(xl, sheet)
            if df.empty:
                continue
            # Drop any pre-existing "Abronal Source" column to avoid duplicates on concat
            df = df.drop(columns=["Abronal Source"], errors="ignore")
            df["Abronal Source"] = sheet
            frames.append(df)
        return pd.concat(frames, ignore_index=True) if frames else pd.read_excel(path)

    def _normalize_columns(self) -> None:
        rename = {}
        for col in self.data.columns:
            lower = str(col).lower()
            target = None
            if lower in ("doctor name", "doctor_name", "physician", "physician name", "abronal source"):
                target = "Doctor Name"
            elif lower == "service":
                target = "Service"
            elif lower == "amount":
                target = "Amount"
            elif lower in ("sot date", "abronal date", "date"):
                target = "SoT Date"

            # Only rename if target doesn't already exist (avoid duplicate columns)
            if target and target not in self.data.columns:
                rename[col] = target

        if rename:
            self.data = self.data.rename(columns=rename)

        if "SoT Date" in self.data.columns:
            self.data["SoT Date"] = pd.to_datetime(self.data["SoT Date"], errors="coerce").dt.date
        if "Category" not in self.data.columns and "Service" in self.data.columns:
            self.data["Category"] = self.data["Service"].map(self.category_map).fillna("Other")

        if "Abronal Source" in self.data.columns and "Doctor Name" in self.data.columns:
            self.data["Doctor Name"] = self.data["Doctor Name"].fillna(self.data["Abronal Source"])
            self.data = self.data.drop(columns=["Abronal Source"])

        if not self.buffer.empty:
            for col in ("Doctor Name", "Service", "Amount", "SoT Date"):
                if col not in self.buffer.columns:
                    for c in self.buffer.columns:
                        if str(c).lower().replace("_", " ") == col.lower():
                            self.buffer = self.buffer.rename(columns={c: col})
            if "Category" not in self.buffer.columns and "Service" in self.buffer.columns:
                self.buffer["Category"] = self.buffer["Service"].map(self.category_map).fillna("Other")

            if "Abronal Source" in self.buffer.columns and "Doctor Name" in self.buffer.columns:
                self.buffer["Doctor Name"] = self.buffer["Doctor Name"].fillna(self.buffer["Abronal Source"])
                self.buffer = self.buffer.drop(columns=["Abronal Source"])

        for frame in ("data", "buffer"):
            df = getattr(self, frame)
            if "Patient Name" in df.columns:
                setattr(self, frame, df.drop(columns=["Patient Name"]))

    # ------------------------------------------------------------------ #
    # Summary building
    # ------------------------------------------------------------------ #
    def doctor_summary(self, *, group_by_date: bool = True) -> pd.DataFrame:
        """
        Pivot services into "<Category> Total" columns summed per doctor
        (optionally broken out by date), then append Total, Commission %,
        and Commission columns.
        """
        frames = [self.data]
        if not self.buffer.empty:
            frames.append(self.buffer)
        combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

        # Remove any duplicate columns that might have been created
        combined = combined.loc[:, ~combined.columns.duplicated(keep="first")]

        empty_cols = ["Doctor Name", "TOTAL", "Commission %", "Commission"]
        if combined.empty or "Doctor Name" not in combined.columns:
            return pd.DataFrame(columns=empty_cols)

        if "Category" not in combined.columns:
            combined["Category"] = combined["Service"].map(self.category_map).fillna("Other")

        index_cols = ["Doctor Name"]
        if group_by_date and "SoT Date" in combined.columns:
            combined["Date"] = combined["SoT Date"]
            index_cols = ["Date", "Doctor Name"]

        pivot = combined.pivot_table(
            index=index_cols,
            columns="Category",
            values="Amount",
            aggfunc="sum",
            fill_value=0,
        ).reset_index()

        category_cols = [c for c in pivot.columns if c not in index_cols]
        ordered = [c for c in COLUMN_ORDER if c in category_cols]
        extras = sorted(c for c in category_cols if c not in COLUMN_ORDER)
        amount_cols = ordered + extras

        # Rename category columns to "<Category> Total"
        pivot = pivot.rename(columns={c: f"{c} Total" for c in amount_cols})
        total_cols = [f"{c} Total" for c in amount_cols]

        pivot["TOTAL"] = pivot[total_cols].sum(axis=1) if total_cols else 0

        pct = pivot["Doctor Name"].map(self._commission_pct_for)
        pivot["Commission %"] = pct
        pivot["Commission"] = pivot["TOTAL"] * (pct / 100.0)
        # Where no rate is configured, keep both columns null rather than 0
        no_rate = pct.isna()
        pivot.loc[no_rate, "Commission"] = None

        final_cols = index_cols + total_cols + ["TOTAL", "Commission %", "Commission"]
        pivot = pivot[final_cols]

        sort_cols = (["Date"] if "Date" in pivot.columns else []) + ["TOTAL"]
        ascending = ([True] if "Date" in pivot.columns else []) + [False]
        return pivot.sort_values(sort_cols, ascending=ascending).reset_index(drop=True)

    def write_summary(self, output_path: str | Path) -> Path:
        """Write the per-doctor commission summary to a single Excel sheet."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        summary = self.doctor_summary(group_by_date=False)

        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            summary.to_excel(writer, sheet_name="Doctor Summary", index=False)

            raw = pd.concat([self.data, self.buffer], ignore_index=True) if not self.buffer.empty else self.data
            raw.to_excel(writer, sheet_name="Raw Data", index=False)

        return output_path


def run_category_merger(
    matched_path: str,
    output_path: str,
    *,
    dictionary_path: str | None = None,
    commission_path: str | None = None,
    unreconciled_path: str | None = None,
    log_fn=print,
) -> Path:
    """Convenience wrapper: condense matched (+ optional unreconciled) data."""
    condensor = Condensor(dictionary_path, commission_path)
    condensor.read_dictionary()
    log_fn(f"  Loaded {len(condensor.category_map)} service categories")

    condensor.read_commission_config()
    if condensor.commission_map:
        log_fn(f"  Loaded commission rates for {len(condensor.commission_map)} doctor(s)")
    else:
        log_fn("  No commission.json found (or empty) - Commission columns will be null")

    condensor.load_data(matched_path, buffer=unreconciled_path or pd.DataFrame())
    log_fn(f"  Loaded {len(condensor.data)} matched rows")
    if not condensor.buffer.empty:
        log_fn(f"  Loaded {len(condensor.buffer)} unreconciled rows into buffer")

    result = condensor.write_summary(output_path)
    log_fn(f"  Doctor commission summary written: {result}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge services into per-doctor category totals with commission")
    parser.add_argument("--input", required=True, help="Matched Excel workbook or secondary_state.json")
    parser.add_argument("--out", required=True, help="Output summary Excel path")
    parser.add_argument(
        "--dictionary",
        default=str(DEFAULT_DICTIONARY),
        help="Service→category dictionary JSON",
    )
    parser.add_argument(
        "--commission-config",
        default=str(DEFAULT_COMMISSION_CONFIG),
        help="Doctor→commission %% dictionary JSON (configs/commission.json)",
    )
    parser.add_argument(
        "--unreconciled",
        help="Optional Still_Unreconciled.xlsx to include in a separate buffer pass",
    )
    parser.add_argument(
        "--buffer-sheet",
        action="store_true",
        help="When --unreconciled is set, write a second summary for unreconciled-only data",
    )
    args = parser.parse_args()

    try:
        run_category_merger(
            args.input,
            args.out,
            dictionary_path=args.dictionary,
            commission_path=args.commission_config,
            unreconciled_path=args.unreconciled,
        )
        if args.buffer_sheet and args.unreconciled:
            buffer_out = str(Path(args.out).with_stem(Path(args.out).stem + "_unreconciled"))
            c = Condensor(args.dictionary, args.commission_config)
            c.read_dictionary()
            c.read_commission_config()
            c.load_data(args.unreconciled)
            c.write_summary(buffer_out)
            print(f"Unreconciled-only summary: {buffer_out}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())