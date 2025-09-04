# streamlit_app.py
# -*- coding: utf-8 -*-
# xray-steps-parser v1.0 (+ collapse option)

"""
Streamlit – Xray Test Steps Parser (CSV → Flat Table)

Features
- Upload ; (semicolon) separated CSV exported from Jira/Xray
- Detect column: "Custom field (Manual Test Steps)" (case-insensitive contains)
- Parse JSON array of steps → rows: Issue key, Summary, Step #, Action, Data, Expected Result
- Add "Case #" numbering (per unique Issue key in input order)
- Display interactive table, simple metrics
- Download UTF-8 BOM CSV (Excel-friendly)
- (New) Option to show Issue key & Summary only on the first row of each case

Run
  streamlit run streamlit_app.py

Requires
  pip install streamlit pandas
"""

import io
import json
import re
from typing import List, Dict, Any

import pandas as pd
import streamlit as st

# ---------------------------
# Helpers
# ---------------------------

def find_col(cols: List[str], needle: str) -> str:
    """Find a column whose name contains `needle` (case-insensitive)."""
    needle_low = needle.lower()
    for c in cols:
        if needle_low in c.lower():
            return c
    return ""


def parse_manual_steps_cell(cell: Any) -> List[Dict[str, Any]]:
    """Parse one cell from Manual Test Steps.
    Expected JSON like: [ {"index":1, "fields":{"Action":"...","Data":"...","Expected Result":"..."}}, ... ]
    Returns list of dicts with keys: Step #, Action, Data, Expected Result
    """
    if not isinstance(cell, str) or not cell.strip():
        return []
    # Some exports may include stray whitespace or non-breaking space
    s = cell.strip().replace('\u00a0', ' ')
    try:
        arr = json.loads(s)
    except Exception:
        # Some instances may use single quotes → try a relaxed fix
        try:
            s_relaxed = s.replace("'", '"')
            arr = json.loads(s_relaxed)
        except Exception:
            return []

    out = []
    if isinstance(arr, list):
        for item in arr:
            fields = item.get("fields", {}) if isinstance(item, dict) else {}
            action = fields.get("Action", "")
            data = fields.get("Data", "")
            expected = fields.get("Expected Result", "")
            out.append({
                "Step #": item.get("index"),
                "Action": _clean_text(action),
                "Data": _clean_text(data),
                "Expected Result": _clean_text(expected),
            })
    return out


def _clean_text(x: Any) -> str:
    s = str(x) if x is not None else ""
    # collapse whitespace
    s = re.sub(r"\s+", " ", s, flags=re.UNICODE).strip()
    return s


def build_flat(df: pd.DataFrame, col_steps: str, col_key: str, col_sum: str) -> pd.DataFrame:
    rows = []
    for _, r in df.iterrows():
        key = r.get(col_key)
        summ = r.get(col_sum)
        steps = parse_manual_steps_cell(r.get(col_steps))
        if not steps:
            rows.append({
                "Issue key": key,
                "Summary": summ,
                "Step #": None,
                "Action": "",
                "Data": "",
                "Expected Result": "",
            })
        else:
            for s in steps:
                rows.append({
                    "Issue key": key,
                    "Summary": summ,
                    **s,
                })
    flat = pd.DataFrame(rows)

    # Case # numbering by first appearance order of Issue key
    order = pd.Categorical(flat["Issue key"], categories=pd.unique(flat["Issue key"]))
    flat = flat.assign(_ord=order)
    uniques = pd.unique(flat["Issue key"])  # preserves order
    case_map = {k: i + 1 for i, k in enumerate([u for u in uniques if pd.notna(u)])}
    flat.insert(0, "Case #", flat["Issue key"].map(case_map))
    flat.drop(columns=["_ord"], errors="ignore", inplace=True)

    # Ensure consistent column order
    flat = flat[["Case #", "Issue key", "Summary", "Step #", "Action", "Data", "Expected Result"]]
    return flat


def collapse_repeats(df: pd.DataFrame, group_col: str, cols_to_blank: List[str]) -> pd.DataFrame:
    """Within each group (e.g., Issue key), blank out repeated cols after the first row."""
    if df.empty or group_col not in df.columns:
        return df
    out = df.copy()
    # sort=False keeps original input order
    for _, idx in out.groupby(group_col, sort=False).groups.items():
        if len(idx) > 1:
            out.loc[idx[1:], cols_to_blank] = ""
    return out


def df_to_csv_bom(df: pd.DataFrame, sep: str = ";") -> bytes:
    csv_str = df.to_csv(index=False, sep=sep, encoding="utf-8-sig")
    # to_csv already returns str; ensure bytes with BOM preserved
    return csv_str.encode("utf-8-sig")

# ---------------------------
# UI
# ---------------------------

st.set_page_config(page_title="Xray Steps Parser", page_icon="✅", layout="wide")
st.title("Xray Test Steps Parser")
st.caption("CSV (noktalı virgül ; ile ayrılmış) → Ayrıştırılmış step tablosu + Case numaraları")

uploaded = st.file_uploader("CSV yükle (Jira'dan export edilmiş, ; ile ayrılmış)", type=["csv"])

if uploaded is None:
    st.info("Örnek: Jira 'Export → CSV (All fields)' çıktısı. Sütun: 'Custom field (Manual Test Steps)'.")
    st.stop()

# Read CSV (semicolon by default)
try:
    df_raw = pd.read_csv(uploaded, sep=";", dtype=str, low_memory=False)
except Exception:
    # Try auto-sep fallback
    df_raw = pd.read_csv(uploaded, dtype=str, low_memory=False)

st.success(f"Yüklendi: {len(df_raw)} satır, {len(df_raw.columns)} sütun")

# Detect columns
col_steps = find_col(df_raw.columns.tolist(), "Manual Test Steps")
col_key = find_col(df_raw.columns.tolist(), "Issue key") or find_col(df_raw.columns.tolist(), "Key")
col_sum = find_col(df_raw.columns.tolist(), "Summary")

missing = []
if not col_steps:
    missing.append("Manual Test Steps")
if not col_key:
    missing.append("Issue key")
if not col_sum:
    missing.append("Summary")

if missing:
    st.error("Eksik sütun(lar): " + ", ".join(missing))
    st.stop()

with st.expander("Sütun eşlemesi (otomatik algılandı)"):
    st.write({
        "Manual Test Steps": col_steps,
        "Issue key": col_key,
        "Summary": col_sum,
    })

# Option: collapse repeated key/summary
collapse_opt = st.checkbox("Issue key ve Summary sadece ilk satırda görünsün", value=True)

# Build flat table
flat = build_flat(df_raw, col_steps, col_key, col_sum)

# Apply collapse (affects both table and downloads)
if collapse_opt:
    flat = collapse_repeats(flat, group_col="Issue key", cols_to_blank=["Issue key", "Summary"])

# Simple metrics
left, right = st.columns(2)
with left:
    st.metric("Toplam Case", flat["Issue key"].replace("", pd.NA).nunique())
with right:
    st.metric("Toplam Step", (flat["Step #"].notna()).sum())

st.subheader("Ayrıştırılmış Test Adımları")
st.dataframe(flat, use_container_width=True)

# Downloads
colA, colB = st.columns(2)
with colA:
    st.download_button(
        label="CSV indir (UTF-8 BOM, ; ile)",
        data=df_to_csv_bom(flat, sep=";"),
        file_name="manual_test_steps_numbered_utf8.csv",
        mime="text/csv",
    )
with colB:
    # Optional: also provide comma-separated for non-TR tools
    st.download_button(
        label="CSV indir (UTF-8 BOM, , ile)",
        data=df_to_csv_bom(flat, sep=","),
        file_name="manual_test_steps_numbered_utf8_comma.csv",
        mime="text/csv",
    )

st.caption("Not: CSV, Excel uyumu için UTF-8 BOM ile kaydedilir. Case #, inputtaki Issue key sırasına göre atanır. "
           "‘Issue key & Summary’ çökertme seçeneği hem tabloda hem de indirilen CSV’de uygulanır.")
