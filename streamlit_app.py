# streamlit_app.py
# -*- coding: utf-8 -*-
# xray-steps-parser v1.3 (+ collapse option & separate dynamic columns)

"""
Streamlit – Xray Test Steps Parser (CSV → Flat Table)

Features
- Upload ; (semicolon) separated CSV exported from Jira/Xray
- Detect column: "Custom field (Manual Test Steps)" (case-insensitive contains)
- Parses additional fields: Description, Test Repository Path
- Keeps multiple columns for Labels and Pre-Conditions separate (e.g., Labels, Labels.1)
- Parse JSON array of steps → rows: Issue key, Summary, Step #, Action, Data, Expected Result
- Add "Case #" numbering (per unique Issue key in input order)
- Display interactive table, simple metrics
- Download UTF-8 BOM CSV (Excel-friendly)
- Option to show Issue key, Summary & extra fields only on the first row of each case

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
    """Find the FIRST column whose name contains `needle` (case-insensitive)."""
    needle_low = needle.lower()
    for c in cols:
        if needle_low in c.lower():
            return c
    return ""

def find_multi_cols(cols: List[str], needle: str) -> List[str]:
    """Find ALL columns whose names contain `needle` (case-insensitive)."""
    needle_low = needle.lower()
    return [c for c in cols if needle_low in c.lower()]


def parse_manual_steps_cell(cell: Any) -> List[Dict[str, Any]]:
    """Parse one cell from Manual Test Steps."""
    if not isinstance(cell, str) or not cell.strip():
        return []
    s = cell.strip().replace('\u00a0', ' ')
    try:
        arr = json.loads(s)
    except Exception:
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
    s = re.sub(r"\s+", " ", s, flags=re.UNICODE).strip()
    return s


def build_flat(df: pd.DataFrame, col_map: Dict[str, Any]) -> pd.DataFrame:
    rows = []
    for _, r in df.iterrows():
        # Get single values safely
        key = r.get(col_map['key'], "") if pd.notna(r.get(col_map['key'])) else ""
        summ = r.get(col_map['sum'], "") if pd.notna(r.get(col_map['sum'])) else ""
        desc = r.get(col_map['desc'], "") if pd.notna(r.get(col_map['desc'])) else ""
        repo = r.get(col_map['repo'], "") if pd.notna(r.get(col_map['repo'])) else ""
        
        base_info = {
            "Issue key": key,
            "Summary": summ,
            "Description": desc,
            "Test Repository Path": repo
        }

        # Keep Labels as separate columns
        for lbl_col in col_map['labels']:
            base_info[lbl_col] = r.get(lbl_col, "") if pd.notna(r.get(lbl_col)) else ""

        # Keep Pre-Conditions as separate columns
        for prec_col in col_map['precond']:
            base_info[prec_col] = r.get(prec_col, "") if pd.notna(r.get(prec_col)) else ""

        steps_cell = r.get(col_map['steps'], "") if col_map['steps'] else ""
        steps = parse_manual_steps_cell(steps_cell)
        
        if not steps:
            rows.append({
                **base_info,
                "Step #": None,
                "Action": "",
                "Data": "",
                "Expected Result": "",
            })
        else:
            for s in steps:
                rows.append({
                    **base_info,
                    **s,
                })
                
    flat = pd.DataFrame(rows)

    # Numbering
    order = pd.Categorical(flat["Issue key"], categories=pd.unique(flat["Issue key"]))
    flat = flat.assign(_ord=order)
    uniques = pd.unique(flat["Issue key"]) 
    case_map = {k: i + 1 for i, k in enumerate([u for u in uniques if pd.notna(u) and u != ""])}
    flat.insert(0, "Case #", flat["Issue key"].map(case_map))
    flat.drop(columns=["_ord"], errors="ignore", inplace=True)

    # Dynamic ordered columns to include all separate Labels and Pre-Conditions
    ordered_cols = ["Case #", "Issue key", "Summary", "Description"]
    ordered_cols.extend(col_map['labels'])
    ordered_cols.extend(col_map['precond'])
    ordered_cols.extend(["Test Repository Path", "Step #", "Action", "Data", "Expected Result"])
    
    flat = flat[ordered_cols]
    return flat


def collapse_repeats(df: pd.DataFrame, group_col: str, cols_to_blank: List[str]) -> pd.DataFrame:
    if df.empty or group_col not in df.columns:
        return df
    out = df.copy()
    for _, idx in out.groupby(group_col, sort=False).groups.items():
        if len(idx) > 1:
            out.loc[idx[1:], cols_to_blank] = ""
    return out


def df_to_csv_bom(df: pd.DataFrame, sep: str = ";") -> bytes:
    csv_str = df.to_csv(index=False, sep=sep, encoding="utf-8-sig")
    return csv_str.encode("utf-8-sig")

# ---------------------------
# UI
# ---------------------------

st.set_page_config(page_title="Xray Steps Parser", page_icon="✅", layout="wide")
st.title("Xray Test Steps Parser")
st.caption("CSV (noktalı virgül ; ile ayrılmış) → Ayrıştırılmış step tablosu + Case numaraları ve Ayrı Ek Sütunlar")

uploaded = st.file_uploader("CSV yükle (Jira'dan export edilmiş, ; ile ayrılmış)", type=["csv"])

if uploaded is None:
    st.info("Örnek: Jira 'Export → CSV (All fields)' çıktısı. Sütun: 'Custom field (Manual Test Steps)'.")
    st.stop()

# Read CSV
try:
    df_raw = pd.read_csv(uploaded, sep=";", dtype=str, low_memory=False)
except Exception:
    df_raw = pd.read_csv(uploaded, dtype=str, low_memory=False)

st.success(f"Yüklendi: {len(df_raw)} satır, {len(df_raw.columns)} sütun")

# Detect columns dynamically
cols_list = df_raw.columns.tolist()
col_map = {
    'steps': find_col(cols_list, "Manual Test Steps"),
    'key': find_col(cols_list, "Issue key") or find_col(cols_list, "Key"),
    'sum': find_col(cols_list, "Summary"),
    'desc': find_col(cols_list, "Description"),
    'repo': find_col(cols_list, "Test Repository Path"),
    'labels': find_multi_cols(cols_list, "Labels"),
    'precond': find_multi_cols(cols_list, "Pre-Conditions association")
}

missing = []
if not col_map['steps']: missing.append("Manual Test Steps")
if not col_map['key']: missing.append("Issue key")
if not col_map['sum']: missing.append("Summary")

if missing:
    st.error("Zorunlu eksik sütun(lar): " + ", ".join(missing))
    st.stop()

with st.expander("Sütun eşlemesi (otomatik algılandı)"):
    st.write({
        "Manual Test Steps": col_map['steps'],
        "Issue key": col_map['key'],
        "Summary": col_map['sum'],
        "Description": col_map['desc'] or "(Bulunamadı)",
        "Test Repository Path": col_map['repo'] or "(Bulunamadı)",
        "Labels Sütunları": col_map['labels'] if col_map['labels'] else "(Bulunamadı)",
        "Pre-Conditions Sütunları": col_map['precond'] if col_map['precond'] else "(Bulunamadı)"
    })

collapse_opt = st.checkbox("Üst veri (Issue key, Summary, Labels vb.) sadece ilk satırda görünsün", value=True)

# Build the flat structure
flat = build_flat(df_raw, col_map)

# Apply collapse including dynamic columns
if collapse_opt:
    cols_to_blank = ["Issue key", "Summary", "Description", "Test Repository Path"]
    cols_to_blank.extend(col_map['labels'])
    cols_to_blank.extend(col_map['precond'])
    flat = collapse_repeats(flat, group_col="Issue key", cols_to_blank=cols_to_blank)

left, right = st.columns(2)
with left:
    st.metric("Toplam Case", flat["Issue key"].replace("", pd.NA).nunique())
with right:
    st.metric("Toplam Step", (flat["Step #"].notna()).sum())

st.subheader("Ayrıştırılmış Test Adımları")
st.dataframe(flat, use_container_width=True)

colA, colB = st.columns(2)
with colA:
    st.download_button(
        label="CSV indir (UTF-8 BOM, ; ile)",
        data=df_to_csv_bom(flat, sep=";"),
        file_name="manual_test_steps_numbered_utf8.csv",
        mime="text/csv",
    )
with colB:
    st.download_button(
        label="CSV indir (UTF-8 BOM, , ile)",
        data=df_to_csv_bom(flat, sep=","),
        file_name="manual_test_steps_numbered_utf8_comma.csv",
        mime="text/csv",
    )
