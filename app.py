import streamlit as st
import uuid
import logic
import dxf_plate

# -------------------------------------------------
# SESSION STATE INIT
# -------------------------------------------------
st.session_state.setdefault("estimate_parts", [])
st.session_state.setdefault("edit_part_id", None)
st.session_state.setdefault("edit_part_type", None)

# -------------------------------------------------
# APP HEADER
# -------------------------------------------------
st.set_page_config(layout="wide")
st.title("Manufacturing Estimating Tool")

page = st.sidebar.radio(
    "Navigate",
    ["Structural", "Plate", "Summary"]
)

editing = st.session_state["edit_part_id"] is not None


# -------------------------------------------------
# STRUCTURAL PAGE
# -------------------------------------------------
if page == "Structural":

    st.header("Structural Estimate")

    row = None
    if editing and st.session_state["edit_part_type"] == "Structural":
        row = next(
            r for r in st.session_state["estimate_parts"]
            if r["id"] == st.session_state["edit_part_id"]
        )
        st.warning("Editing existing Structural part — totals will be recalculated")

    part_name = st.text_input(
        "Part Name",
        value=row["Part Name"] if row else ""
    )

    quantity = st.number_input(
        "Quantity",
        min_value=1,
        value=row["Quantity"] if row else 1
    )

    length_in = st.number_input(
        "Length (in)",
        min_value=0.0,
        value=row["Length (in)"] if row else 0.0
    )

    shape = st.text_input(
        "Shape",
        value=row["Shape"] if row else ""
    )

    material = st.selectbox(
        "Material",
        ["A36", "A992"],
        index=["A36", "A992"].index(row["Material"]) if row else 0
    )

    if editing:
        if st.button("Update Structural Part"):
            new_part = logic.calculate_structural_part(
                part_name=part_name,
                quantity=quantity,
                length_in=length_in,
                shape=shape,
                material=material
            )
            new_part["id"] = row["id"]

            st.session_state["estimate_parts"] = [
                new_part if r["id"] == row["id"] else r
                for r in st.session_state["estimate_parts"]
            ]

            st.session_state["edit_part_id"] = None
            st.session_state["edit_part_type"] = None
            st.rerun()

    else:
        if st.button("Add Structural Part"):
            part = logic.calculate_structural_part(
                part_name=part_name,
                quantity=quantity,
                length_in=length_in,
                shape=shape,
                material=material
            )
            part["id"] = str(uuid.uuid4())
            st.session_state["estimate_parts"].append(part)
            st.success("Structural part added")


# -------------------------------------------------
# PLATE PAGE
# -------------------------------------------------
elif page == "Plate":

    st.header("Plate Estimate")

    row = None
    if editing and st.session_state["edit_part_type"] == "Plate":
        row = next(
            r for r in st.session_state["estimate_parts"]
            if r["id"] == st.session_state["edit_part_id"]
        )
        st.warning("Editing existing Plate part — totals will be recalculated")

    part_name = st.text_input(
        "Part Name",
        value=row["Part Name"] if row else ""
    )

    quantity = st.number_input(
        "Quantity",
        min_value=1,
        value=row["Quantity"] if row else 1
    )

    thickness = st.number_input(
        "Thickness (in)",
        min_value=0.0,
        value=row["Thickness (in)"] if row else 0.0
    )

    material = st.selectbox("Material", ["A36"], index=0)

    uploaded_dxf = st.file_uploader("Upload DXF", type=["dxf"])

    if editing:
        if st.button("Update Plate Part"):
            new_part = logic.calculate_plate_part(
                part_name=part_name,
                quantity=quantity,
                thickness=thickness,
                material=material,
                dxf_data=row["DXF Data"]
            )
            new_part["id"] = row["id"]

            st.session_state["estimate_parts"] = [
                new_part if r["id"] == row["id"] else r
                for r in st.session_state["estimate_parts"]
            ]

            st.session_state["edit_part_id"] = None
            st.session_state["edit_part_type"] = None
            st.rerun()

    else:
        if uploaded_dxf and st.button("Add Plate Part"):
            dxf_data = dxf_plate.process_dxf(uploaded_dxf)

            part = logic.calculate_plate_part(
                part_name=part_name,
                quantity=quantity,
                thickness=thickness,
                material=material,
                dxf_data=dxf_data
            )
            part["id"] = str(uuid.uuid4())
            st.session_state["estimate_parts"].append(part)
            st.success("Plate part added")


# -------------------------------------------------
# SUMMARY PAGE
# -------------------------------------------------
elif page == "Summary":

    st.header("Estimate Summary")

    if not st.session_state["estimate_parts"]:
        st.info("No parts added yet.")
    else:

        # ---------------- TOTALS ----------------
        total_labor = sum(p.get("Total Labor Hours", 0) for p in st.session_state["estimate_parts"])
        total_material = sum(p.get("Material Cost", 0) for p in st.session_state["estimate_parts"])
        total_weight = sum(p.get("Weight (lb)", 0) for p in st.session_state["estimate_parts"])

        tcols = st.columns(3)
        tcols[0].metric("Total Labor (hrs)", f"{total_labor:,.2f}")
        tcols[1].metric("Material Cost ($)", f"${total_material:,.2f}")
        tcols[2].metric("Total Weight (lb)", f"{total_weight:,.0f}")

        st.divider()

        # ---------------- PART ROWS ----------------
        for i, row in enumerate(st.session_state["estimate_parts"]):
            cols = st.columns([6, 1, 1, 1])

            with cols[0]:
                st.text(
                    f'{row["Part Name"]} | Qty {row["Quantity"]} | '
                    f'{row["Estimation Type"]}'
                )

            # EDIT
            with cols[1]:
                if st.button("✏️", key=f"edit_{row['id']}"):
                    st.session_state["edit_part_id"] = row["id"]
                    st.session_state["edit_part_type"] = row["Estimation Type"]
                    st.rerun()

            # DUPLICATE
            with cols[2]:
                if st.button("🔁", key=f"dup_{row['id']}"):
                    new_row = row.copy()
                    new_row["id"] = str(uuid.uuid4())
                    new_row["Part Name"] = f'{row["Part Name"]} (Copy)'
                    st.session_state["estimate_parts"].append(new_row)
                    st.rerun()

            # DELETE
            with cols[3]:
                if st.button("🗑", key=f"del_{row['id']}"):
                    st.session_state["estimate_parts"].pop(i)
                    st.rerun()
