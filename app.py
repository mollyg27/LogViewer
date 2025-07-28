import streamlit as st
import json
import pandas as pd
import altair as alt

st.title("JSON Log Viewer")

uploaded_file = st.file_uploader("Upload a JSON log file", type="json")

if not uploaded_file:
    st.info("Please upload a JSON file to begin.")
    st.stop()
#When file is uploaded
@st.cache_data(show_spinner=False)
def parse_log_file(file_obj):
    raw_data = json.load(file_obj)
    st.write('done loading file')

    if not isinstance(raw_data, list) or not all(isinstance(entry, dict) for entry in raw_data):
        raise ValueError("Invalid JSON format. Expected a list of timestamped dictionaries.")

    before = 2
    after = 10
    entries = list(raw_data)

    log = {}
    run_id_map = {}  # run_id -> list of timestamps

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
    selected_ts = sorted(timestamps)
    rows = []
    #get out data that you want
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

    for ts, entry in log_data.items():
        step_recipe = entry.get("Step Recipe", {})
        run_id = step_recipe.get("Run ID", "Unnamed Run")

        run_map.setdefault(run_id, []).append(ts)
    if not selected_run:
        st.warning("Please select a valid run.")
        st.stop()

    selected_timestamps = run_map[selected_run]
    if not selected_timestamps:
        st.warning("No timestamps found for selected run.")
        st.stop()

    mfc_df = extract_mfc_data(log_data, selected_timestamps)

    if mfc_df.empty:
        st.warning("No valid MFC data found for this run.")
        st.stop()

    st.subheader(f"Gas Flow Trends for '{selected_run}'")

    gases = mfc_df["Gas"].unique()
    selected_gases = st.multiselect("Select gases to plot", gases, default=list(gases))
    #voltage and Power seperated by gas
    if selected_gases:
        #Gas Flow
        chart_data = mfc_df[mfc_df["Gas"].isin(selected_gases)]
        chart_data = chart_data.sort_values("Time")

        chart_data = chart_data.groupby("Gas", group_keys=False).apply(lambda df: df.iloc[::5], include_groups=True).reset_index(drop=True)

        line = alt.Chart(chart_data).mark_line().encode(x="Time:T",y="Read (sccm):Q", color="Gas:N")
        points = alt.Chart(chart_data).mark_point(size=30).encode(x="Time:T",y="Read (sccm):Q", color="Gas:N",
        tooltip=[alt.Tooltip("Time:T", title="Timestamp", format="%H:%M:%S"),alt.Tooltip("Read (sccm):Q", title="Flow Read"),alt.Tooltip("Gas:N", title="Gas"),alt.Tooltip("Recipe Step:N", title = "Active Step")])
        gas_chart = (line + points).interactive().properties(height=300)
        st.altair_chart(gas_chart, use_container_width=True)
        st.subheader("Voltage (%)")
        #Voltage
        voltage_data = mfc_df[mfc_df["Gas"].isin(selected_gases)].copy()
        time_data = mfc_df.groupby("Time", as_index=False).first()
        if voltage_data.empty:
            st.warning("No voltage data available for selected gases.")
        else:
            voltage_data = voltage_data.sort_values("Time")
            voltage_data = voltage_data.groupby("Gas", group_keys=False).apply(lambda df: df.iloc[::5], include_groups=True).reset_index(drop=True)
            line = alt.Chart(voltage_data).mark_line().encode(x="Time:T",y="Voltage:Q",color="Gas:N")
            points = alt.Chart(voltage_data).mark_point(size=30).encode(x="Time:T",y="Voltage:Q",color="Gas:N",
            tooltip=[alt.Tooltip("Time:T", title="Timestamp", format="%H:%M:%S"),alt.Tooltip("Voltage:Q", title="Voltage"),alt.Tooltip("Gas:N", title="Gas"),alt.Tooltip("Recipe Step:N", title = "Active Step")])
            voltage_chart = (line + points).interactive().properties(height=300)
            st.altair_chart(voltage_chart, use_container_width=True)
        #Power
        st.subheader("Forward Power (W)")
        line = alt.Chart(time_data).mark_line().encode(x="Time:T", y="Forward Power (W):Q")
        points = alt.Chart(time_data).mark_point(size=30).encode(x="Time:T", y="Forward Power (W):Q", 
        tooltip=[alt.Tooltip("Time:T", title="Timestamp", format="%H:%M:%S"),alt.Tooltip("Forward Power (W):Q"),alt.Tooltip("Recipe Step:N", title = "Active Step")])
        st.altair_chart((line + points).interactive().properties(height=300), use_container_width=True)
       #Bottom Pressure
        st.subheader("Bottom Pressure (W)")

        line = alt.Chart(time_data).mark_line().encode(x="Time:T", y="Bottom Pressure (mTorr):Q")
        points = alt.Chart(time_data).mark_point(size=30).encode(x="Time:T", y="Bottom Pressure (mTorr):Q", 
        tooltip=[alt.Tooltip("Time:T", title="Timestamp", format="%H:%M:%S"),alt.Tooltip("Bottom Pressure (mTorr):Q"),alt.Tooltip("Recipe Step:N", title = "Active Step")])
        st.altair_chart((line + points).interactive().properties(height=300), use_container_width=True) 
        #Top Pressure (TiO2 AND SIO2)
        st.subheader("SIO2 Top Pressure (W)")

        line = alt.Chart(time_data).mark_line().encode(x="Time:T", y="SiO2 Top Pressure (mTorr):Q")
        points = alt.Chart(time_data).mark_point(size=30).encode(x="Time:T", y="SiO2 Top Pressure (mTorr):Q", 
        tooltip=[alt.Tooltip("Time:T", title="Timestamp", format="%H:%M:%S"),alt.Tooltip("SiO2 Top Pressure (mTorr):Q"),alt.Tooltip("Recipe Step:N", title = "Active Step")])
        st.altair_chart((line + points).interactive().properties(height=300), use_container_width=True) 
        st.subheader("TiO2 Top Pressure (W)")

        line = alt.Chart(time_data).mark_line().encode(x="Time:T", y="TiO2 Top Pressure (mTorr):Q")
        points = alt.Chart(time_data).mark_point(size=30).encode(x="Time:T", y="TiO2 Top Pressure (mTorr):Q", 
        tooltip=[alt.Tooltip("Time:T", title="Timestamp", format="%H:%M:%S"),alt.Tooltip("TiO2 Top Pressure (mTorr):Q"),alt.Tooltip("Recipe Step:N", title = "Active Step")])
        st.altair_chart((line + points).interactive().properties(height=300), use_container_width=True) 
except Exception as e:
    st.error("Could not process the uploaded file.")
    st.exception(e)
