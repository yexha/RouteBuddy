"""
Flexible CSV/Excel importer with persistent column mapping.
On first import, detects likely columns and lets user confirm/override the mapping.
Mapping is saved to config and remembered for next time.
"""
import json
import re
from pathlib import Path
from typing import Optional
import pandas as pd


KNOWN_ADDRESS_PATTERNS = re.compile(r'addr|street|location|site|property', re.I)
KNOWN_NAME_PATTERNS = re.compile(r'name|customer|client|last|first', re.I)
KNOWN_NOTES_PATTERNS = re.compile(r'note|comment|remark|gate|warn|special', re.I)


def _guess_column(columns: list[str], pattern: re.Pattern) -> Optional[str]:
    for col in columns:
        if pattern.search(col):
            return col
    return None


def load_file(path: str) -> pd.DataFrame:
    """Load CSV or Excel into a DataFrame."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(p, dtype=str).fillna("")
    elif ext == ".csv":
        # try utf-8 first, fall back to latin-1 for Windows exports
        try:
            return pd.read_csv(p, dtype=str).fillna("")
        except UnicodeDecodeError:
            return pd.read_csv(p, dtype=str, encoding="latin-1").fillna("")
    else:
        raise ValueError(f"Unsupported file type: {ext}. Use .csv, .xlsx, or .xls")


def guess_mapping(columns: list[str]) -> dict[str, Optional[str]]:
    """Return best-guess {field: column_name} mapping."""
    return {
        "address": _guess_column(columns, KNOWN_ADDRESS_PATTERNS),
        "customer_name": _guess_column(columns, KNOWN_NAME_PATTERNS),
        "notes": _guess_column(columns, KNOWN_NOTES_PATTERNS),
    }


def apply_mapping(df: pd.DataFrame, mapping: dict[str, str]) -> list[dict]:
    """
    Apply column mapping to DataFrame, return list of stop dicts.
    Skips rows where address column is blank.
    Raises ValueError with row number for badly malformed rows.
    """
    addr_col = mapping.get("address")
    name_col = mapping.get("customer_name")
    notes_col = mapping.get("notes")

    if not addr_col or addr_col not in df.columns:
        raise ValueError(f"Address column {addr_col!r} not found in file. Available: {list(df.columns)}")

    stops = []
    skipped = []
    for i, row in df.iterrows():
        address = str(row.get(addr_col, "")).strip()
        if not address:
            skipped.append(i + 2)  # +2: 1-indexed + header row
            continue
        stops.append({
            "address": address,
            "customer_name": str(row.get(name_col, "") if name_col and name_col in df.columns else "").strip(),
            "notes": str(row.get(notes_col, "") if notes_col and notes_col in df.columns else "").strip(),
        })

    return stops, skipped


MAPPING_CONFIG_FILE = Path.home() / ".routebuddy" / "column_mapping.json"


def save_mapping(mapping: dict, source_columns: list[str]) -> None:
    MAPPING_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {"mapping": mapping, "source_columns": source_columns}
    MAPPING_CONFIG_FILE.write_text(json.dumps(data, indent=2))


def load_saved_mapping() -> Optional[dict]:
    if MAPPING_CONFIG_FILE.exists():
        try:
            return json.loads(MAPPING_CONFIG_FILE.read_text())
        except Exception:
            return None
    return None
