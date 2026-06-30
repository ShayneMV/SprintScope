"""
app.py: Streamlit UI for Laveg laser velocity analysis.

Main entry point. Run with: streamlit run _app/app.py
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from pathlib import Path
from datetime import datetime

from _app.config_loader import load_config
from _app.db import TrialsDB
from _app.parser import parse_sprintscope_csv, prepare_trial_record
from _app.splits import compute_trial_metrics


# Configuration and initialization
st.set_page_config(page_title="Laveg - Laser Velocity Analysis", layout="wide")

@st.cache_resource
def init_app():
    """Initialize app: load config and database."""
    config = load_config()
    db = TrialsDB(str(config.db_path))
    return config, db


config, db = init_app()

# Validate configuration
warnings = config.validate()
if warnings:
    for warning in warnings:
        st.warning(warning)

st.title("Laveg — Laser Velocity Session Database & Review")

# Sidebar controls
st.sidebar.header("Selection")

# Event group selector
event_groups = db.get_event_groups()
if not event_groups:
    st.sidebar.warning("No event groups found in database. Import trials first.")
    selected_event = None
else:
    selected_event = st.sidebar.selectbox("Event Group", ["All"] + event_groups)
    if selected_event == "All":
        selected_event = None

# Athlete selector
if selected_event:
    athletes = db.get_athletes_by_event(selected_event)
else:
    # Get all unique athletes
    all_trials = db.get_all_trials()
    athletes = sorted(all_trials["athlete_name"].unique().tolist()) if not all_trials.empty else []

if not athletes:
    st.sidebar.warning("No athletes found.")
    selected_athlete = None
else:
    selected_athlete = st.sidebar.selectbox("Athlete", athletes)

# Trial/session selector
if selected_athlete:
    athlete_trials = db.get_trials_by_athlete(selected_athlete, event_group=selected_event)
    
    if not athlete_trials.empty:
        # Group trials by session_date
        trial_trials = athlete_trials.sort_values("session_date", ascending=False)
        
        # Create display labels: date - test_type - distance - peak_v
        trial_list = []
        trial_ids = []
        
        for _, row in trial_trials.iterrows():
            date_str = row["session_date"] or "No date"
            test_type = row["test_type"] or "Unknown"
            distance = f"{row['distance_m']:.0f}m" if row["distance_m"] else "Unknown distance"
            peak_v = f"{row['peak_v_ms']:.2f}m/s" if row["peak_v_ms"] else "No peak"
            
            # Flag for short trials
            flag = "⚠️ SHORT" if row["flag_short_trial"] == 1 else ""
            
            label = f"{date_str} - {test_type} - {distance} - {peak_v} {flag}".strip()
            trial_list.append(label)
            trial_ids.append(row["trial_id"])
        
        # Multi-select trials
        include_flagged = st.sidebar.checkbox("Include flagged (short) trials", value=False)
        if not include_flagged:
            # Filter out flagged trials
            filtered_trials = []
            filtered_ids = []
            for trial_id, label in zip(trial_ids, trial_list):
                trial = athlete_trials[athlete_trials["trial_id"] == trial_id].iloc[0]
                if trial["flag_short_trial"] != 1:
                    filtered_trials.append(label)
                    filtered_ids.append(trial_id)
            trial_list = filtered_trials
            trial_ids = filtered_ids
        
        selected_trials_labels = st.sidebar.multiselect("Select trials to compare", trial_list, default=trial_list[:1] if trial_list else [])
        
        # Map labels back to trial IDs
        selected_trial_ids = [trial_ids[trial_list.index(label)] for label in selected_trials_labels]
    else:
        selected_trial_ids = []
        st.sidebar.info("No trials for this athlete.")
else:
    selected_trial_ids = []

# Split interval control
split_interval = st.sidebar.selectbox(
    "Split Interval (m)",
    [5, 10, 20, 50],
    index=1,  # Default to 10m
)

# Scan for new files
if st.sidebar.button("🔄 Scan for new CSV files"):
    st.sidebar.info("Scanning for new files...")
    
    # Scan data root for CSV files
    csv_files = list(config.data_root.rglob("*.csv"))
    imported_count = 0
    skipped_count = 0
    errors = []
    
    for csv_file in csv_files:
        # Get event group (parent folder name)
        event_group = csv_file.parent.name
        
        # Parse file
        parsed = parse_sprintscope_csv(str(csv_file))
        if parsed is None:
            errors.append(f"Unrecognized format: {csv_file.name}")
            continue
        
        # Prepare trial record
        trial_record = prepare_trial_record(parsed, str(csv_file), event_group)
        
        # Compute derived metrics
        metrics = compute_trial_metrics(
            parsed["samples"],
            parsed["device_splits"],
            trial_record["distance_m"],
            trial_record["splits_every_m"],
        )
        
        # Update trial record with computed metrics
        trial_record.update(metrics)
        
        # Upsert to database (use marked device_splits from metrics)
        try:
            trial_id, action = db.upsert_trial(
                trial_record,
                parsed["samples"],
                metrics["device_splits"],
            )
            
            if action == "inserted":
                imported_count += 1
            elif action == "skipped":
                skipped_count += 1
        except Exception as e:
            errors.append(f"Error importing {csv_file.name}: {e}")
    
    st.sidebar.success(f"Imported {imported_count} new trials, skipped {skipped_count} duplicates.")
    if errors:
        for error in errors:
            st.sidebar.warning(error)

# Main content area
if selected_trial_ids:
    # Get trial data
    selected_trials = db.get_trials_by_ids(selected_trial_ids)
    
    # Create tabs
    tab_overlay, tab_splits, tab_trend, tab_detail = st.tabs(
        ["Overlay Plot", "Split Comparison", "Development Trend", "Trial Detail"]
    )
    
    with tab_overlay:
        st.subheader("Velocity Profile Overlay")
        st.write("Velocity vs. Filtered Distance for selected trials")
        
        # Import valid window functions
        from _app.splits import find_zero_crossing, find_t_reach, get_valid_window_mask
        
        # Build overlay plot
        fig = go.Figure()
        
        for trial_id in selected_trial_ids:
            trial = selected_trials[selected_trials["trial_id"] == trial_id].iloc[0]
            samples = db.get_samples_for_trial(trial_id)
            
            if samples.empty:
                continue
            
            # Apply time-based valid window instead of distance-based clipping
            distance_m = trial["distance_m"]
            split_origin_t_s = trial["split_origin_t_s"]
            t_reach = find_t_reach(samples, distance_m)
            valid_mask = get_valid_window_mask(samples, split_origin_t_s, t_reach)
            samples_valid = samples[valid_mask]
            
            # Create trace
            label = f"{trial['session_date']} - {trial['test_type']}"
            if trial["flag_short_trial"] == 1:
                label += " (SHORT)"
            
            dash = "dash" if trial["flag_short_trial"] == 1 else "solid"
            
            fig.add_trace(go.Scatter(
                x=samples_valid["dist_filt_m"],
                y=samples_valid["vel_ms"],
                mode="lines",
                name=label,
                line=dict(dash=dash),
            ))
            
            # Mark peak velocity
            if trial["peak_v_ms"] and trial["peak_v_distance_m"]:
                fig.add_trace(go.Scatter(
                    x=[trial["peak_v_distance_m"]],
                    y=[trial["peak_v_ms"]],
                    mode="markers",
                    marker=dict(size=8, symbol="star"),
                    name=f"Peak ({trial['peak_v_distance_m']:.1f}m)",
                    showlegend=False,
                ))
        
        fig.update_layout(
            title="Velocity vs. Filtered Distance",
            xaxis_title="Filtered Distance (m)",
            yaxis_title="Velocity (m/s)",
            hovermode="x unified",
            height=500,
        )
        st.plotly_chart(fig, use_container_width=True)
        
        # Download PNG button
        st.write("TODO: Download PNG button")
    
    with tab_splits:
        st.subheader("Split Comparison Table")
        st.write(f"Custom splits at {split_interval}m interval")
        
        # Build comparison table: rows = distances, columns = trials (grouped by split_time, cum_time, velocity)
        try:
            # Collect custom splits for all selected trials
            trial_splits = {}
            for trial_id in selected_trial_ids:
                trial = selected_trials[selected_trials["trial_id"] == trial_id].iloc[0]
                samples = db.get_samples_for_trial(trial_id)
                
                if samples.empty:
                    continue
                
                # Compute custom splits using splits module
                from _app.splits import compute_custom_splits, find_zero_crossing
                t_origin = find_zero_crossing(samples)
                splits = compute_custom_splits(
                    samples,
                    t_origin or 0,
                    trial["distance_m"],
                    split_interval,
                )
                
                if not splits.empty:
                    trial_splits[trial_id] = {
                        "label": f"{trial['session_date']} - {trial['test_type']}",
                        "splits": splits,
                    }
            
            if trial_splits:
                # Build comparison DataFrame
                comparison_data = []
                
                # Get all unique split distances
                all_distances = set()
                for trial_data in trial_splits.values():
                    all_distances.update(trial_data["splits"]["split_distance_m"].tolist())
                
                all_distances = sorted(list(all_distances))
                
                for distance in all_distances:
                    row = {"Split (m)": distance}
                    
                    # Find fastest cumulative time at this distance
                    fastest_cum_t = float('inf')
                    
                    for trial_id, trial_data in trial_splits.items():
                        splits_df = trial_data["splits"]
                        dist_row = splits_df[splits_df["split_distance_m"] == distance]
                        
                        if not dist_row.empty:
                            cum_t = dist_row.iloc[0]["cumulative_time_s"]
                            split_t = dist_row.iloc[0]["split_time_s"]
                            vel_split = dist_row.iloc[0]["velocity_at_split_ms"]
                            
                            row[f"{trial_data['label']} - Time"] = f"{cum_t:.3f}s"
                            row[f"{trial_data['label']} - Split"] = f"{split_t:.3f}s"
                            row[f"{trial_data['label']} - Vel"] = f"{vel_split:.2f}m/s"
                            
                            fastest_cum_t = min(fastest_cum_t, cum_t)
                    
                    # Mark fastest
                    if fastest_cum_t != float('inf'):
                        for trial_id, trial_data in trial_splits.items():
                            splits_df = trial_data["splits"]
                            dist_row = splits_df[splits_df["split_distance_m"] == distance]
                            if not dist_row.empty:
                                cum_t = dist_row.iloc[0]["cumulative_time_s"]
                                if abs(cum_t - fastest_cum_t) < 0.001:
                                    time_col = f"{trial_data['label']} - Time"
                                    if time_col in row:
                                        row[time_col] = f"🔥 {row[time_col]}"
                    
                    comparison_data.append(row)
                
                comparison_df = pd.DataFrame(comparison_data)
                st.dataframe(comparison_df, use_container_width=True)
                
                # Download CSV button
                csv_str = comparison_df.to_csv(index=False)
                st.download_button(
                    label="📥 Download Comparison as CSV",
                    data=csv_str,
                    file_name=f"split_comparison_{split_interval}m.csv",
                    mime="text/csv",
                )
            else:
                st.info("No custom splits computed.")
        
        except Exception as e:
            st.error(f"Error building split table: {e}")
            import traceback
            st.write(traceback.format_exc())
    
    with tab_trend:
        st.subheader("Development Trend")
        
        # Metric selector
        metric = st.selectbox(
            "Metric",
            list(config.available_metrics.keys()),
            format_func=lambda x: config.available_metrics.get(x, x)
        )
        
        try:
            # Collect metric values for all selected trials
            trend_data = []
            
            for trial_id in selected_trial_ids:
                trial = selected_trials[selected_trials["trial_id"] == trial_id].iloc[0]
                samples = db.get_samples_for_trial(trial_id)
                
                if samples.empty:
                    continue
                
                # Compute metric value based on selection
                from _app.splits import compute_custom_splits, find_zero_crossing, interpolate_at_distance
                
                t_origin = find_zero_crossing(samples)
                
                metric_value = None
                
                if metric == "peak_v_ms":
                    metric_value = trial["peak_v_ms"]
                elif metric.startswith("cumulative_time_"):
                    # Extract distance from metric name (e.g., "cumulative_time_50m" -> 50)
                    distance_str = metric.split("_")[-1]  # "50m"
                    distance_val = float(distance_str.rstrip("m"))
                    
                    result = interpolate_at_distance(samples, distance_val)
                    if result:
                        t_at_d, _ = result
                        metric_value = t_at_d - (t_origin or 0)
                
                elif metric.startswith("velocity_at_"):
                    # Extract distance from metric name
                    distance_str = metric.split("_")[-1]  # "50m"
                    distance_val = float(distance_str.rstrip("m"))
                    
                    result = interpolate_at_distance(samples, distance_val)
                    if result:
                        _, v_at_d = result
                        metric_value = v_at_d
                
                if metric_value is not None:
                    trend_data.append({
                        "Date": trial["session_date"],
                        "Trial ID": trial_id,
                        "Test Type": trial["test_type"],
                        "Metric": metric_value,
                    })
            
            if trend_data:
                trend_df = pd.DataFrame(trend_data)
                trend_df["Date"] = pd.to_datetime(trend_df["Date"])
                trend_df = trend_df.sort_values("Date")
                
                # Plot trend
                fig = px.line(
                    trend_df,
                    x="Date",
                    y="Metric",
                    hover_data=["Test Type"],
                    markers=True,
                    title=f"Trend: {config.available_metrics.get(metric, metric)}",
                )
                fig.update_yaxes(title_text=config.available_metrics.get(metric, metric))
                st.plotly_chart(fig, use_container_width=True)
                
                # Summary stats
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Latest", f"{trend_df['Metric'].iloc[-1]:.2f}")
                with col2:
                    st.metric("Best", f"{trend_df['Metric'].max():.2f}")
                with col3:
                    change = trend_df['Metric'].iloc[-1] - trend_df['Metric'].iloc[0]
                    st.metric("Change", f"{change:+.2f}")
                
                # Download button
                csv_str = trend_df.to_csv(index=False)
                st.download_button(
                    label="📥 Download Trend Data as CSV",
                    data=csv_str,
                    file_name=f"trend_{metric}.csv",
                    mime="text/csv",
                )
            else:
                st.info("No data for selected metric.")
        
        except Exception as e:
            st.error(f"Error computing trend: {e}")
            import traceback
            st.write(traceback.format_exc())
    
    with tab_detail:
        st.subheader("Trial Detail")
        
        # Single trial selector
        trial_options = {f"{t['session_date']} - {t['test_type']}": t["trial_id"] for _, t in selected_trials.iterrows()}
        selected_detail_trial_label = st.selectbox("Select trial", list(trial_options.keys()))
        selected_detail_trial_id = trial_options[selected_detail_trial_label]
        
        detail_trial = selected_trials[selected_trials["trial_id"] == selected_detail_trial_id].iloc[0]
        
        # Metadata block
        st.write("#### Metadata")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.write(f"**Athlete**: {detail_trial['athlete_name']}")
            st.write(f"**Date**: {detail_trial['session_date']}")
            st.write(f"**Test Type**: {detail_trial['test_type']}")
        with col2:
            st.write(f"**Distance**: {detail_trial['distance_m']:.1f} m")
            st.write(f"**Peak V**: {detail_trial['peak_v_ms']:.2f} m/s at {detail_trial['peak_v_distance_m']:.1f} m")
            st.write(f"**Split Origin**: {detail_trial['split_origin_t_s']:.2f} s")
        with col3:
            st.write(f"**Surface**: {detail_trial['surface']}")
            st.write(f"**Wind**: {detail_trial['wind']}")
            st.write(f"**Notes**: {detail_trial['notes'] or '(none)'}")
        
        # Device split table
        st.write("#### Device Splits")
        device_splits = db.get_device_splits_for_trial(selected_detail_trial_id)
        if not device_splits.empty:
            st.dataframe(device_splits, use_container_width=True)
        else:
            st.info("No device splits recorded.")
        
        # Velocity-distance curve
        st.write("#### Velocity Profile")
        samples = db.get_samples_for_trial(selected_detail_trial_id)
        if not samples.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=samples["dist_filt_m"],
                y=samples["vel_ms"],
                mode="lines",
                name="Velocity",
                fill="tozeroy",
            ))
            fig.update_layout(
                xaxis_title="Filtered Distance (m)",
                yaxis_title="Velocity (m/s)",
                height=400,
            )
            st.plotly_chart(fig, use_container_width=True)
        
        # Custom split table
        st.write("#### Custom Splits (at selected interval)")
        try:
            samples = db.get_samples_for_trial(selected_detail_trial_id)
            if not samples.empty:
                from _app.splits import compute_custom_splits, find_zero_crossing
                
                t_origin = find_zero_crossing(samples)
                custom_splits = compute_custom_splits(
                    samples,
                    t_origin or 0,
                    detail_trial["distance_m"],
                    split_interval,
                )
                
                if not custom_splits.empty:
                    # Format and display
                    display_splits = custom_splits.copy()
                    display_splits["split_distance_m"] = display_splits["split_distance_m"].apply(lambda x: f"{x:.1f}m")
                    display_splits["cumulative_time_s"] = display_splits["cumulative_time_s"].apply(lambda x: f"{x:.3f}s")
                    display_splits["split_time_s"] = display_splits["split_time_s"].apply(lambda x: f"{x:.3f}s")
                    display_splits["velocity_at_split_ms"] = display_splits["velocity_at_split_ms"].apply(lambda x: f"{x:.2f}m/s")
                    display_splits["segment_avg_velocity_ms"] = display_splits["segment_avg_velocity_ms"].apply(lambda x: f"{x:.2f}m/s" if pd.notna(x) else "N/A")
                    
                    display_splits.columns = ["Split Distance", "Cumulative Time", "Split Time", "Velocity at Split", "Avg Segment Velocity"]
                    
                    st.dataframe(display_splits, use_container_width=True)
                    
                    # Download button
                    csv_str = custom_splits.to_csv(index=False)
                    st.download_button(
                        label="📥 Download Custom Splits as CSV",
                        data=csv_str,
                        file_name=f"custom_splits_{selected_detail_trial_id}_{split_interval}m.csv",
                        mime="text/csv",
                    )
                else:
                    st.info("No custom splits computed for this trial.")
        except Exception as e:
            st.error(f"Error computing custom splits: {e}")

else:
    st.info("Select trials from the sidebar to view comparisons.")
    st.write("""
    ### Getting Started
    
    1. Use the **Scan for new CSV files** button to import SprintScope exports from your data folders
    2. Select an athlete and trial(s) from the sidebar
    3. View velocity profiles, compare splits, and track development over time
    
    ### Features
    - **Overlay Plot**: Compare velocity profiles across multiple trials
    - **Split Comparison**: View split times and velocities at chosen intervals
    - **Development Trend**: Track how metrics improve over time
    - **Trial Detail**: Deep dive into a single trial with full metadata and tables
    """)
