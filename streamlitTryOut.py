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

    if not isinstance(raw_data, list) or not all(isinstance(entry, dict) for entry in raw_data):
        raise ValueError("Invalid JSON format. Expected a list of timestamped dictionaries.")
    #Only save active recipe data
    log = {}
    for entry in raw_data:
        ts, data = list(entry.items())[0]
        recipe_active = data.get("Step Recipe", {}).get("Recipe Active", False)

        if recipe_active is True:
            log[ts] = data

    return log

@st.cache_data(show_spinner=False)
def extract_mfc_data(log_data, timestamps, neighbors=1):
    all_ts = sorted(timestamps)
    valid_indices = []
    for i, ts in enumerate(all_ts):
        entry = log_data[ts]
        recipe_active = entry.get("Step Recipe", {}).get("Recipe Active", False)

        if recipe_active is True:
            for offset in range(neighbors - 1, neighbors + 1):
                idx = i + offset
                if idx < len(all_ts):
                    valid_indices.append(idx)

    valid_indices = sorted(set(valid_indices))
    selected_ts = [all_ts[i] for i in valid_indices]
    rows = []
    #get out data that you want
    for ts in selected_ts:
        entry = log_data[ts]
        source_data = entry.get("Source", {})
        power_data = entry.get("Power Supply", {}) or {}
        pressure_data = entry.get("Throttle", {}) or {}

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
                    "Top Pressure (mTorr)": float(source_data.get("TiO2 Pressure", "0.0 mTorr").replace(" mTorr", "").strip())
                        if isinstance(source_data.get("TiO2 Pressure"), str) else 0.0,
                    "Bottom Pressure (mTorr)": float(pressure_data.get("Bottom Pressure", "0.0"))
                })
            except (KeyError, ValueError, AttributeError):
                continue
    return pd.DataFrame(rows)

try:
    log_data = parse_log_file(uploaded_file)
    run_map = {}

    for ts, entry in log_data.items():
        step_recipe = entry.get("Step Recipe", {})
        run_id = step_recipe.get("Run ID", "Unnamed Run")

        run_map.setdefault(run_id, []).append(ts)

    run_names = sorted(run_map.keys())
    selected_run = st.selectbox("Select Run", run_names)

    if not selected_run:
        st.warning("Please select a valid run.")
        st.stop()

    selected_timestamps = run_map.get(selected_run, [])
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

        chart_data = chart_data.groupby("Gas", group_keys=False).apply(lambda df: df.iloc[::5]).reset_index(drop=True)

        line = alt.Chart(chart_data).mark_line().encode(x="Time:T",y="Read (sccm):Q", color="Gas:N")
        points = alt.Chart(chart_data).mark_point(size=30).encode(x="Time:T",y="Read (sccm):Q", color="Gas:N",
        tooltip=[alt.Tooltip("Time:T", title="Timestamp", format="%H:%M:%S"),alt.Tooltip("Read (sccm):Q", title="Flow Read"),alt.Tooltip("Gas:N", title="Gas")])
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
            voltage_data = voltage_data.groupby("Gas", group_keys=False).apply(lambda df: df.iloc[::5]).reset_index(drop=True)
            line = alt.Chart(voltage_data).mark_line().encode(x="Time:T",y="Voltage:Q",color="Gas:N")
            points = alt.Chart(voltage_data).mark_point(size=30).encode(x="Time:T",y="Voltage:Q",color="Gas:N",
            tooltip=[alt.Tooltip("Time:T", title="Timestamp", format="%H:%M:%S"),alt.Tooltip("Voltage:Q", title="Voltage"),alt.Tooltip("Gas:N", title="Gas")])
            voltage_chart = (line + points).interactive().properties(height=300)
            st.altair_chart(voltage_chart, use_container_width=True)
        #Power
        st.subheader("Forward Power (W)")

        line = alt.Chart(time_data).mark_line().encode(x="Time:T", y="Forward Power (W):Q")
        points = alt.Chart(time_data).mark_point(size=30).encode(x="Time:T", y="Forward Power (W):Q", 
        tooltip=[alt.Tooltip("Time:T", title="Timestamp", format="%H:%M:%S"),alt.Tooltip("Forward Power (W):Q")])
        st.altair_chart((line + points).interactive().properties(height=300), use_container_width=True)
       #Bottom Pressure
        st.subheader("Bottom Pressure (W)")

        line = alt.Chart(time_data).mark_line().encode(x="Time:T", y="Bottom Pressure (mTorr):Q")
        points = alt.Chart(time_data).mark_point(size=30).encode(x="Time:T", y="Bottom Pressure (mTorr):Q", 
        tooltip=[alt.Tooltip("Time:T", title="Timestamp", format="%H:%M:%S"),alt.Tooltip("Bottom Pressure (mTorr):Q")])
        st.altair_chart((line + points).interactive().properties(height=300), use_container_width=True) 
        #Top Pressure
        st.subheader("Top Pressure (W)")

        line = alt.Chart(time_data).mark_line().encode(x="Time:T", y="Top Pressure (mTorr):Q")
        points = alt.Chart(time_data).mark_point(size=30).encode(x="Time:T", y="Top Pressure (mTorr):Q", 
        tooltip=[alt.Tooltip("Time:T", title="Timestamp", format="%H:%M:%S"),alt.Tooltip("Top Pressure (mTorr):Q")])
        st.altair_chart((line + points).interactive().properties(height=300), use_container_width=True) 
except Exception as e:
    st.error("Could not process the uploaded file.")
    st.exception(e)

