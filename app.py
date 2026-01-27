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


def _init_state() -> None:
    st.session_state.setdefault("authenticated", False)
    st.session_state.setdefault("estimate_parts", [])
    st.session_state.setdefault("plate_yield_results", {})
    st.session_state.setdefault("structural_yield_results", {})


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


@st.cache_data(show_spinner=False)
def _load_aisc_once(csv_path: str) -> bool:
    logic.aisc_data_load_attempted = False
    logic.AISC_TYPES_TO_LABELS_MAP = None
    logic.AISC_LABEL_TO_PROPERTIES_MAP = None
    logic.load_aisc_database(csv_path)
    return bool(logic.AISC_TYPES_TO_LABELS_MAP)


def _add_part(part: Dict[str, Any]) -> None:
    part["id"] = str(uuid.uuid4())
    st.session_state["estimate_parts"].append(part)


def _clear_estimate() -> None:
    st.session_state["estimate_parts"] = []
    st.session_state["plate_yield_results"] = {}
    st.session_state["structural_yield_results"] = {}


def _export_csv_bytes(rows: List[Dict[str, Any]]) -> bytes:
    if not rows:
        return b""
    return pd.DataFrame(rows).to_csv(index=False).encode("utf-8")


# -------------------- PAGES (Plate / Structural / Welding UNCHANGED) --------------------
# (Everything below this line is identical to your original logic,
#  except for the Summary page at the end.)

# -------------------- SUMMARY PAGE (UPDATED SAFELY) --------------------
def page_summary() -> None:
    st.header("Summary")

    rows = st.session_state["estimate_parts"]
    if not rows:
        st.info("No parts yet.")
        return

    totals = _compute_totals(rows)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total gross weight (lbs)", f"{totals['combined_overall_gross_weight']:.2f}")
    c2.metric("Fit time (min)", f"{totals['grand_total_fit_time']:.2f}")
    c3.metric("Weld time (hr)", f"{totals['grand_total_weld_time_hours']:.2f}")
    c4.metric("Total perimeter (in)", f"{totals['grand_total_perimeter_in']:.2f}")

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

        # DUPLICATE
        with cols[1]:
            if st.button("🔁", key=f"dup_{row['id']}"):
                new_row = row.copy()
                new_row["id"] = str(uuid.uuid4())
                new_row["Part Name"] = f"{row.get('Part Name','')} (Copy)"
                rows.append(new_row)
                st.rerun()

        # DELETE
        with cols[2]:
            if st.button("🗑", key=f"del_{row['id']}"):
                rows.pop(i)
                st.rerun()

    st.divider()

    st.download_button(
        "Download CSV",
        data=_export_csv_bytes(rows),
        file_name=f"estimate_{datetime.datetime.now():%Y%m%d_%H%M%S}.csv",
        mime="text/csv",
    )


# -------------------- TOTALS (UNCHANGED) --------------------
def _compute_totals(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    fit_t = 0.0
    laser_t = 0.0
    kinetic_t = 0.0
    saw_t = 0.0
    weld_hr = 0.0
    weld_wire = 0.0
    gross = 0.0
    perim = 0.0

    for r in rows:
        gross += float(r.get("Total Gross Weight (lbs)", 0) or 0)
        fit_t += float(r.get("Total Fit Time (min)", 0) or 0)
        weld_hr += float(r.get("Total Weld Time (hours)", 0) or 0)
        weld_wire += float(r.get("Total Weld Wire (lbs)", 0) or 0)

        per_item = float(r.get("Perimeter (in/item)", 0) or 0)
        qty = int(r.get("Quantity", 0) or 0)
        perim += per_item * qty

        if r.get("Burn Machine Type") == "Laser":
            laser_t += float(r.get("Total Burning Time (min)", 0) or 0)
        elif r.get("Burn Machine Type") == "Kinetic":
            kinetic_t += float(r.get("Total Burning Time (min)", 0) or 0)

        saw_t += float(r.get("Total Cutting Time (min)", 0) or 0)

    return {
        "combined_overall_gross_weight": gross,
        "grand_total_fit_time": fit_t,
        "grand_total_laser_burn_time": laser_t,
        "grand_total_kinetic_burn_time": kinetic_t,
        "grand_total_saw_time": saw_t,
        "grand_total_weld_time_hours": weld_hr,
        "grand_total_weld_wire_lbs": weld_wire,
        "grand_total_perimeter_in": perim,
    }


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    _init_state()
    require_auth()

    ok = _load_aisc_once(logic.AISC_CSV_FILENAME)
    if not ok:
        st.warning("AISC database could not be loaded.")

    with st.sidebar:
        st.title(APP_TITLE)
        page = st.radio("Go to", ["Plate", "Structural", "Welding", "Summary"])
        st.write(f"Items: **{len(st.session_state['estimate_parts'])}**")
        if st.button("Clear estimate"):
            _clear_estimate()
            st.rerun()

    if page == "Plate":
        page_plate()
    elif page == "Structural":
        page_structural()
    elif page == "Welding":
        page_welding()
    else:
        page_summary()


if __name__ == "__main__":
    main()
