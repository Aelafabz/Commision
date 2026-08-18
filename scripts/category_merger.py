from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

DEFAULT_COMMISSION_RATE = 0.10

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


def load_dictionary(path: str | Path) -> dict[str, str]:
    path = Path(path)
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return {str(k): str(v) for k, v in data.items() if k is not None}
    except Exception:
        return {}


def _reorder_columns(df: pd.DataFrame) -> pd.DataFrame:
    ordered = [c for c in COLUMN_ORDER if c in df.columns]
    fixed = {"Patient Name", "TOTAL", "Commission %", "Commission Amount", "Date Range"}
    extras = sorted(c for c in df.columns if c not in COLUMN_ORDER and c not in fixed)
    lead = [c for c in ("Patient Name",) if c in df.columns]
    trail = [c for c in ("TOTAL", "Commission %", "Commission Amount", "Date Range") if c in df.columns]
    return df[lead + ordered + extras + trail]


class Condensor:
    
    def __init__(self, dictionary_path: str | Path | None = None, dictionary: dict[str, str] | None = None):
        self.dictionary = dictionary if dictionary is not None else load_dictionary(dictionary_path or "")
        self._data: pd.DataFrame | None = None

    def read_dictionary(self, dictionary_path: str | Path) -> dict[str, str]:
        self.dictionary = load_dictionary(dictionary_path)
        return self.dictionary

    def load_data(
        self,
        df: pd.DataFrame,
        service_column: str = "Service",
        amount_column: str = "Amount",
        patient_column: str = "Patient Name",
    ) -> pd.DataFrame:
        if df is None or df.empty:
            self._data = pd.DataFrame(columns=[patient_column, service_column, amount_column, "Category"])
            return self._data
        data = df.copy()
        data["Category"] = data[service_column].map(self.dictionary).fillna("Other")
        data = data.rename(columns={service_column: "Service", amount_column: "Amount", patient_column: "Patient Name"})
        self._data = data
        return self._data

    def list_condensor(
        self,
        date_label: str = "",
        commission_rate: float = DEFAULT_COMMISSION_RATE,
    ) -> pd.DataFrame:
        if self._data is None or self._data.empty:
            return pd.DataFrame(columns=["Patient Name", "TOTAL", "Commission %", "Commission Amount", "Date Range"])

        pivot = self._data.pivot_table(
            index="Patient Name",
            columns="Category",
            values="Amount",
            aggfunc="sum",
            fill_value=0,
        ).reset_index()

        value_cols = [c for c in pivot.columns if c != "Patient Name"]
        pivot["TOTAL"] = pivot[value_cols].sum(axis=1)
        pivot["Date Range"] = date_label or ""
        pivot["Commission %"] = f"{commission_rate * 100:.1f}%"
        pivot["Commission Amount"] = pivot["TOTAL"] * commission_rate

        return _reorder_columns(pivot)