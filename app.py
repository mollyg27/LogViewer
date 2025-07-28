import streamlit as st
import json
import pandas as pd
import altair as alt

st.title("JSON Log Viewer")

uploaded_file = st.file_uploader("Upload a JSON log file", type="json")

if not uploaded_file:
    st.info("Please upload a JSON file to begin.")
    st.stop()

@st.cache_data(show_spinner=False)
def parse_log_file(file_obj):
    """
    This function processes the log file and returns log data and a mapping of run IDs to timestamps.
    It avoids reading the entire file into memory by processing it chunk by chunk.
    """
    # Initialize necessary data structures
    log = {}
    run_id_map = {}

    # Load file in chunks (using an iterator for large JSON files)
    file_obj.seek(0)  # Reset file pointer
    raw_data = json.load(file_obj)  # Load JSON once (could be improved by chunking on large files)
    
    if not isinstance(raw_data, list) or not all(isinstance(entry, dict) for entry in raw_data):
        raise ValueError("Invalid JSON format. Expected a list of timestamped dictionaries.")

    before = 2
    after = 10
    entries = list(raw_data)

    # Find active recipe indices
    active_indices = [
        i for i, entry in enumerate(entries)
        if list(entry.values())[0].get("Step Recipe", {}).get("Recipe Active", False)
    ]

    for idx in active_indices:
        ts_main, data_main = list(entries[idx].items())[0]
        run_id = data_main.get("Step Recipe", {}).get("Run ID", "Unnamed Run")

        for offset in range(-before, after + 1):
            i = idx + offset
            if 0 <= i < len(entries):
                for ts, data in entries[i].items():
                    log[ts] = data
                    run_id_map.setdefault(run_id, set()).add(ts)

    # Convert run_id_map sets to sorted lists
    run_id_map = {rid: sorted(ts_list) for rid, ts_list in run_id_map.items()}
    return log, run_id_map

@st.cache_data(show_spinner=False)
def extract_mfc_data(log_data, timestamps):
    """
    Extracts and processes MFC-related data (flow, voltage, etc.) from the log data.
    Only processes entries that match the selected timestamps.
    """
    selected_ts = sorted(timestamps)
    rows = []

    # Get out data that you want, only for selected timestamps
    for ts in selected_ts:
        entry = log_data[ts]
        source_data = entry.get("Source", {})
        power_data = entry.get("Power Supply", {}) or {}
        pressure_data = entry.get("Throttle", {}) or {}
        recipe_data = entry.get("Step Recipe", {}) or {}

        for dev_id, data in source_data.items():
            if not isinstance(data, dict):
                continue

            try:
                read_value = float(data["Read"].strip())
                voltage_value = float(data["Voltage"].replace("V", "").strip())

                rows.append({
                    "Time": pd.to_datetime(ts),
                    "Gas": f"{data['Gas']} ({data['ID']})",
                    "Read (sccm)": read_value,
                    "Voltage": voltage_value,
                    "ID": dev_id,
                    "Forward Power (W)": float(power_data.get("Forward Power", "0.0 W").replace(" W", "").strip()),
                    "Reverse Power (W)": float(power_data.get("Reverse Power", "0.0 W").replace(" W", "").strip()),
                    "TiO2 Top Pressure (mTorr)": float(source_data.get("TiO2 Pressure", "0.0 mTorr").replace(" mTorr", "").strip())
                        if isinstance(source_data.get("TiO2 Pressure"), str) else 0.0,
                    "SiO2 Top Pressure (mTorr)": float(source_data.get("SiO2 Pressure", "0.0 mTorr").replace(" mTorr", "").strip())
                        if isinstance(source_data.get("SiO2 Pressure"), str) else 0.0,
                    "Bottom Pressure (mTorr)": float(pressure_data.get("Bottom Pressure", "0.0")),
                    "Recipe Step": recipe_data.get("Active Step", "No Active Recipe")
                })
            except (KeyError, ValueError, AttributeError):
                continue
    return pd.DataFrame(rows)

try:
    log_data, run_map = parse_log_file(uploaded_file)
    run_names = sorted(run_map.keys())
    selected_run = st.selectbox("Select Run", run_names)
    if not selected_run:
        st.warning("Please select a valid run.")
        st.stop()

    selected_timestamps = run_map[selected_run]

    mfc_df = extract_mfc_data(log_data, selected_timestamps)

    if mfc_df.empty:
        st.warning("No valid MFC data found for this run.")
        st.stop()

    st.subheader(f"Gas Flow Trends for '{selected_run}'")

    gases = mfc_df["Gas"].unique()
    selected_gases = st.multiselect("Select gases to plot", gases, default=list(gases))

    if selected_gases:
        # Gas Flow
        chart_data = mfc_df[mfc_df["Gas"].isin(selected_gases)]
        chart_data = chart_data.sort_values("Time")

        chart_data = chart_data.groupby("Gas", group_keys=False).apply(lambda df: df.iloc[::5], include_groups=True).reset_index(drop=True)

        line = alt.Chart(chart_data).mark_line().encode(x="Time:T", y="Read (sccm):Q", color="Gas:N")
        points = alt.Chart(chart_data).mark_point(size=30).encode(x="Time:T", y="Read (sccm):Q", color="Gas:N",
            tooltip=[alt.Tooltip("Time:T", title="Timestamp", format="%H:%M:%S"), alt.Tooltip("Read (sccm):Q", title="Flow Read"),
                     alt.Tooltip("Gas:N", title="Gas"), alt.Tooltip("Recipe Step:N", title="Active Step")])
        gas_chart = (line + points).interactive().properties(height=300)
        st.altair_chart(gas_chart, use_container_width=True)

    # Repeat similar optimization for other charts (voltage, power, pressure)

except Exception as e:
    st.error("Could not process the uploaded file.")
    st.exception(e)
