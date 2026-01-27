import io
import os
import hmac
import datetime
import uuid
from typing import Dict, Any, List

import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import pandas as pd

import logic
from dxf_plate import parse_dxf_plate_single_part_geometry, render_part_thumbnail_data_uri

APP_TITLE = "Estimating Calculator"


# ============================================================
# Session state
# ============================================================
def _init_state() -> None:
    st.session_state.setdefault("authenticated", False)
    st.session_state.setdefault("estimate_parts", [])
    st.session_state.setdefault("plate_yield_results", {})
    st.session_state.setdefault("structural_yield_results", {})
    st.session_state.setdefault("edit_part_id", None)
    st.session_state.setdefault("edit_part_type", None)


# ============================================================
# Auth
# ============================================================
def _get_password_from_secrets_or_env() -> str:
    if "auth" in st.secrets and "password" in st.secrets["auth"]:
        return str(st.secrets["auth"]["password"])
    return os.getenv("ESTIMATOR_APP_PASSWORD", "")


def require_auth() -> None:
    password = _get_password_from_secrets_or_env()
    if not password:
        st.session_state["authenticated"] = True
        return

    if st.session_state.get("authenticated"):
        return

    st.title(APP_TITLE)
    with st.form("login"):
        entered = st.text_input("Password", type="password")
        ok = st.form_submit_button("Enter")
    if ok:
        if hmac.compare_digest(entered, password):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Incorrect password")
    st.stop()


# ============================================================
# Helpers
# ============================================================
def _add_part(part: Dict[str, Any]) -> None:
    part["id"] = str(uuid.uuid4())
    st.session_state["estimate_parts"].append(part)


def _clear_estimate() -> None:
    st.session_state["estimate_parts"] = []
    st.session_state["plate_yield_results"] = {}
    st.session_state["structural_yield_results"] = {}


# ============================================================
# Summary totals (UNCHANGED)
# ============================================================
def _compute_totals(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    totals = {
        "gross_weight": 0.0,
        "fit_time": 0.0,
        "saw_time": 0.0,
        "laser_time": 0.0,
        "kinetic_time": 0.0,
        "drill_time": 0.0,
        "bend_time": 0.0,
        "weld_time_hr": 0.0,
        "weld_wire_lbs": 0.0,
    }

    for r in rows:
        totals["gross_weight"] += float(r.get("Total Gross Weight (lbs)", 0) or 0)
        totals["fit_time"] += float(r.get("Total Fit Time (min)", 0) or 0)
        totals["saw_time"] += float(r.get("Total Cutting Time (min)", 0) or 0)
        totals["laser_time"] += float(r.get("Total Burning Time (min)", 0) or 0) if r.get("Burn Machine Type") == "Laser" else 0
        totals["kinetic_time"] += float(r.get("Total Burning Time (min)", 0) or 0) if r.get("Burn Machine Type") == "Kinetic" else 0
        totals["drill_time"] += float(r.get("Total Drilling Time (min)", 0) or 0)
        totals["bend_time"] += float(r.get("Total Bend Time (min)", 0) or 0)
        totals["weld_time_hr"] += float(r.get("Total Weld Time (hours)", 0) or 0)
        totals["weld_wire_lbs"] += float(r.get("Total Weld Wire (lbs)", 0) or 0)

    return totals


# ============================================================
# Summary Page (UPDATED – safe)
# ============================================================
def page_summary() -> None:
    st.header("Summary")

    rows = st.session_state["estimate_parts"]
    if not rows:
        st.info("No parts yet.")
        return

    totals = _compute_totals(rows)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total gross weight (lbs)", f"{totals['gross_weight']:.2f}")
    c2.metric("Fit time (min)", f"{totals['fit_time']:.2f}")
    c3.metric("Weld time (hr)", f"{totals['weld_time_hr']:.2f}")
    c4.metric("Weld wire (lbs)", f"{totals['weld_wire_lbs']:.2f}")

    st.divider()
    st.subheader("Estimate line items")

    for i, row in enumerate(rows):
        cols = st.columns([6, 1, 1])

        with cols[0]:
            st.text(
                f"{row.get('Part Name','')} | "
                f"Qty {row.get('Quantity',1)} | "
                f"{row.get('Estimation Type','')}"
            )

        with cols[1]:
            if st.button("🔁", key=f"dup_{row['id']}"):
                new_row = row.copy()
                new_row["id"] = str(uuid.uuid4())
                new_row["Part Name"] = f"{row.get('Part Name','')} (Copy)"
                rows.append(new_row)
                st.rerun()

        with cols[2]:
            if st.button("🗑", key=f"del_{row['id']}"):
                rows.pop(i)
                st.rerun()

    st.divider()

    csv_bytes = pd.DataFrame(rows).to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download CSV",
        data=csv_bytes,
        file_name=f"estimate_{datetime.datetime.now():%Y%m%d_%H%M%S}.csv",
        mime="text/csv",
    )


# ============================================================
# MAIN
# ============================================================
def main() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    _init_state()
    require_auth()

    logic.load_aisc_database(logic.AISC_CSV_FILENAME)

    with st.sidebar:
        st.title(APP_TITLE)
        page = st.radio("Go to", ["Plate", "Structural", "Welding", "Summary"])
        st.write(f"Items: **{len(st.session_state['estimate_parts'])}**")
        if st.button("Clear estimate"):
            _clear_estimate()
            st.rerun()

    if page == "Summary":
        page_summary()
    elif page == "Plate":
        page_plate()       # unchanged
    elif page == "Structural":
        page_structural()  # unchanged
    elif page == "Welding":
        page_welding()     # unchanged


if __name__ == "__main__":
    main()
