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
from _app.splits import compute_trial_metrics, find_zero_crossing, find_t_reach, get_valid_window_mask, compute_custom_splits
from _app.comparison import (
    check_comparability,
    filter_comparable_trials,
    build_split_matrix_mode_a,
    build_split_matrix_mode_b,
    get_trial_conditions_row,
    format_matrix_for_display,
)


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
st.sidebar.header("Comparison Mode")

# Comparison mode selector
comparison_mode = st.sidebar.radio(
    "Select comparison mode",
    ["Mode A: Athlete Progression", "Mode B: Athlete Comparison"],
    help="Mode A: One athlete over time. Mode B: Multiple athletes."
)

# Split interval control (applies to both modes)
split_interval = st.sidebar.selectbox(
    "Split Interval (m)",
    [5, 10, 20, 50],
    index=1,  # Default to 10m
)

# Event group selector
event_groups = db.get_event_groups()
if not event_groups:
    st.sidebar.warning("No event groups found in database. Import trials first.")
    selected_trial_ids = []
else:
    selected_event = st.sidebar.selectbox("Event Group", ["All"] + event_groups)
    if selected_event == "All":
        selected_event = None
    
    # Mode-specific selection
    if "Mode A" in comparison_mode:
        # MODE A: One athlete, multiple trials
        st.sidebar.subheader("Mode A: Athlete Progression")
        
        # Get athletes for event
        if selected_event:
            athletes = db.get_athletes_by_event(selected_event)
        else:
            all_trials = db.get_all_trials()
            athletes = sorted(all_trials["athlete_name"].unique().tolist()) if not all_trials.empty else []
        
        if not athletes:
            st.sidebar.warning("No athletes found.")
            selected_trial_ids = []
        else:
            selected_athlete = st.sidebar.selectbox("Select athlete", athletes)
            
            # Get trials for this athlete
            athlete_trials = db.get_trials_by_athlete(selected_athlete, event_group=selected_event)
            
            if athlete_trials.empty:
                st.sidebar.info("No trials for this athlete.")
                selected_trial_ids = []
            else:
                # Sort by date
                athlete_trials = athlete_trials.sort_values("session_date", ascending=False)
                
                # Create trial labels
                trial_list = []
                trial_ids = []
                for _, row in athlete_trials.iterrows():
                    date_str = row["session_date"] or "No date"
                    distance = f"{row['distance_m']:.0f}m" if row["distance_m"] else "?"
                    start_pos = row["start_position"] or "?"
                    peak_v = f"{row['peak_v_ms']:.2f}m/s" if row["peak_v_ms"] else "?"
                    flag = "⚠️" if row["flag_short_trial"] == 1 else ""
                    
                    label = f"{date_str} - {distance}/{start_pos} - {peak_v} {flag}".strip()
                    trial_list.append(label)
                    trial_ids.append(row["trial_id"])
                
                # Multi-select trials
                selected_labels = st.sidebar.multiselect(
                    "Select trials for this athlete",
                    trial_list,
                    default=trial_list[:1] if trial_list else [],
                    help="All must share the same distance and start position."
                )
                
                selected_trial_ids = [trial_ids[trial_list.index(label)] for label in selected_labels]
    
    else:
        # MODE B: Multiple athletes, one trial each
        st.sidebar.subheader("Mode B: Athlete Comparison")
        
        # Get athletes for event
        if selected_event:
            athletes = db.get_athletes_by_event(selected_event)
        else:
            all_trials = db.get_all_trials()
            athletes = sorted(all_trials["athlete_name"].unique().tolist()) if not all_trials.empty else []
        
        if not athletes or len(athletes) < 2:
            st.sidebar.warning("Need at least 2 athletes for Mode B.")
            selected_trial_ids = []
        else:
            # Multi-select athletes
            selected_athletes = st.sidebar.multiselect(
                "Select athletes to compare",
                athletes,
                min_selections=2,
                help="Select 2 or more athletes."
            )
            
            if len(selected_athletes) < 2:
                st.sidebar.info("Select at least 2 athletes.")
                selected_trial_ids = []
            else:
                # Selection rule
                selection_rule = st.sidebar.radio(
                    "Representative trial selection",
                    ["Best (fastest)", "Latest (most recent)", "Manual pick"],
                    help="Rule for choosing one trial per athlete."
                )
                
                selected_trial_ids = []
                
                for athlete_name in selected_athletes:
                    athlete_trials = db.get_trials_by_athlete(athlete_name, event_group=selected_event)
                    
                    if athlete_trials.empty:
                        st.sidebar.warning(f"No trials for {athlete_name}")
                        continue
                    
                    if selection_rule == "Best (fastest)":
                        # Choose trial with highest peak_v at same distance
                        # First get the most common distance
                        most_common_distance = athlete_trials["distance_m"].mode()
                        if len(most_common_distance) > 0:
                            same_dist = athlete_trials[athlete_trials["distance_m"] == most_common_distance[0]]
                            chosen = same_dist.loc[same_dist["peak_v_ms"].idxmax()]
                        else:
                            chosen = athlete_trials.loc[athlete_trials["peak_v_ms"].idxmax()]
                        selected_trial_ids.append(chosen["trial_id"])
                    
                    elif selection_rule == "Latest (most recent)":
                        # Choose most recent trial
                        latest = athlete_trials.sort_values("session_date", ascending=False).iloc[0]
                        selected_trial_ids.append(latest["trial_id"])
                    
                    else:  # Manual pick
                        # Show options for manual selection
                        athlete_trials = athlete_trials.sort_values("session_date", ascending=False)
                        trial_list = []
                        trial_ids_list = []
                        for _, row in athlete_trials.iterrows():
                            date_str = row["session_date"] or "No date"
                            distance = f"{row['distance_m']:.0f}m" if row["distance_m"] else "?"
                            peak_v = f"{row['peak_v_ms']:.2f}m/s" if row["peak_v_ms"] else "?"
                            label = f"{date_str} - {distance} - {peak_v}"
                            trial_list.append(label)
                            trial_ids_list.append(row["trial_id"])
                        
                        chosen_label = st.sidebar.selectbox(
                            f"Pick trial for {athlete_name}",
                            trial_list
                        )
                        chosen_idx = trial_list.index(chosen_label)
                        selected_trial_ids.append(trial_ids_list[chosen_idx])

# Scan for new files
st.sidebar.header("Import")
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
if not selected_trial_ids:
    st.info("Select trials from the sidebar to begin comparison.")
    st.write("""
    ### Comparison Modes
    
    **Mode A - Athlete Progression**
    - Select one athlete and multiple trials at the same distance
    - Visualize progression over time with date-ordered overlay plot
    - View split matrices organized by session date
    - Track conditions and metrics by trial date
    
    **Mode B - Athlete Comparison**
    - Select 2+ athletes to compare
    - Choose one representative trial per athlete (best, latest, or manual)
    - All trials must be at the same distance for valid comparison
    - View athlete-keyed split matrices and peak velocity comparison
    """)

elif "Mode A" in comparison_mode:
    # MODE A: Athlete Progression
    st.header("Mode A: Athlete Progression")
    
    selected_trials = db.get_trials_by_ids(selected_trial_ids)
    
    # Check comparability
    is_comparable, comp_message = check_comparability(selected_trials)
    st.info(comp_message)
    
    if not is_comparable:
        # Filter to comparable trials
        reference_trial = selected_trials.iloc[0]
        comparable_trials, excluded_ids = filter_comparable_trials(selected_trials, reference_trial)
        
        if excluded_ids:
            excluded_info = []
            for trial_id in excluded_ids:
                trial = selected_trials[selected_trials["trial_id"] == trial_id].iloc[0]
                excluded_info.append(f"- {trial['session_date']} at {trial['distance_m']:.0f}m from {trial['start_position']}")
            
            st.warning(f"⚠️ {len(excluded_ids)} trial(s) excluded (not comparable):\n\n" + "\n".join(excluded_info))
            selected_trials = comparable_trials
            selected_trial_ids = comparable_trials["trial_id"].tolist()
    
    if not selected_trials.empty:
        # Sort by date
        selected_trials = selected_trials.sort_values("session_date")
        
        # Create tabs
        tab_overlay, tab_splits_cum, tab_splits_vel, tab_conditions, tab_trend = st.tabs(
            ["Overlay Plot", "Split Times", "Split Velocities", "Conditions", "Trend"]
        )
        
        with tab_overlay:
            st.subheader("Velocity Profile Overlay - Mode A (Chronological)")
            
            # Build overlay plot
            fig = go.Figure()
            
            for _, trial in selected_trials.iterrows():
                trial_id = trial["trial_id"]
                samples = db.get_samples_for_trial(trial_id)
                
                if samples.empty:
                    continue
                
                # Apply time-based valid window
                distance_m = trial["distance_m"]
                split_origin_t_s = trial["split_origin_t_s"]
                t_reach = find_t_reach(samples, distance_m)
                valid_mask = get_valid_window_mask(samples, split_origin_t_s, t_reach)
                samples_valid = samples[valid_mask]
                
                # Create trace with date label
                label = trial["session_date"] or "No date"
                
                fig.add_trace(go.Scatter(
                    x=samples_valid["dist_filt_m"],
                    y=samples_valid["vel_ms"],
                    mode="lines",
                    name=label,
                    line=dict(width=2),
                ))
                
                # Mark peak velocity
                if trial["peak_v_ms"] and trial["peak_v_distance_m"]:
                    fig.add_trace(go.Scatter(
                        x=[trial["peak_v_distance_m"]],
                        y=[trial["peak_v_ms"]],
                        mode="markers",
                        marker=dict(size=10, symbol="star", color="gold"),
                        name=f"Peak {label}",
                        showlegend=False,
                    ))
            
            fig.update_layout(
                title="Velocity vs. Filtered Distance (Chronologically Ordered)",
                xaxis_title="Filtered Distance (m)",
                yaxis_title="Velocity (m/s)",
                hovermode="x unified",
                height=600,
                template="plotly_dark",
            )
            st.plotly_chart(fig, use_container_width=True)
        
        with tab_splits_cum:
            st.subheader(f"Cumulative Split Times at {split_interval}m Intervals")
            
            # Build Mode A matrix
            cum_matrix, vel_matrix = build_split_matrix_mode_a(
                selected_trials,
                db,
                split_interval,
            )
            
            if not cum_matrix.empty:
                st.dataframe(cum_matrix.style.format("{:.3f}"), use_container_width=True)
                st.caption("Rows: Split distances | Columns: Session dates (chronological)")
                
                # Highlight fastest time per row
                best_per_row = cum_matrix.min(axis=1)
                st.write(f"**Fastest times per split**: {', '.join([f'{d:.0f}m: {t:.3f}s' for d, t in best_per_row.items()])}")
                
                # Download
                csv_str = cum_matrix.to_csv()
                st.download_button(
                    "📥 Download Split Times as CSV",
                    csv_str,
                    f"mode_a_split_times_{split_interval}m.csv",
                    "text/csv",
                )
            else:
                st.warning("No split data available.")
        
        with tab_splits_vel:
            st.subheader(f"Velocity at Split ({split_interval}m Intervals)")
            
            cum_matrix, vel_matrix = build_split_matrix_mode_a(
                selected_trials,
                db,
                split_interval,
            )
            
            if not vel_matrix.empty:
                st.dataframe(vel_matrix.style.format("{:.2f}"), use_container_width=True)
                st.caption("Rows: Split distances | Columns: Session dates (chronological)")
                
                # Highlight fastest velocity per row
                best_per_row = vel_matrix.max(axis=1)
                st.write(f"**Fastest velocities per split**: {', '.join([f'{d:.0f}m: {v:.2f}m/s' for d, v in best_per_row.items()])}")
                
                # Download
                csv_str = vel_matrix.to_csv()
                st.download_button(
                    "📥 Download Split Velocities as CSV",
                    csv_str,
                    f"mode_a_split_velocities_{split_interval}m.csv",
                    "text/csv",
                )
            else:
                st.warning("No velocity data available.")
        
        with tab_conditions:
            st.subheader("Trial Conditions")
            
            # Show conditions for each trial
            for _, trial in selected_trials.iterrows():
                with st.expander(f"📋 {trial['session_date']} - {trial['distance_m']:.0f}m"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**Peak Velocity**: {trial['peak_v_ms']:.2f} m/s at {trial['peak_v_distance_m']:.1f}m")
                        st.write(f"**Split Origin**: {trial['split_origin_t_s']:.2f} s")
                    with col2:
                        st.write(f"**Wind**: {trial.get('wind', 'N/A')}")
                        st.write(f"**Surface**: {trial.get('surface', 'N/A')}")
                    
                    st.write(f"**Footwear**: {trial.get('footwear', 'N/A')}")
                    st.write(f"**Venue**: {trial.get('venue', 'N/A')}")
                    st.write(f"**Notes**: {trial.get('notes', '(none)')}")
        
        with tab_trend:
            st.subheader("Development Trend Over Time")
            
            # Metric selector
            metric = st.selectbox(
                "Select metric",
                ["peak_v_ms", "split_time_10m", "split_time_30m", "split_time_60m"],
                format_func=lambda x: {"peak_v_ms": "Peak Velocity", "split_time_10m": "10m Time", "split_time_30m": "30m Time", "split_time_60m": "60m Time"}.get(x, x)
            )
            
            # Build trend data
            trend_data = []
            for _, trial in selected_trials.iterrows():
                trial_id = trial["trial_id"]
                
                if metric == "peak_v_ms":
                    value = trial["peak_v_ms"]
                else:
                    # Compute split time
                    samples = db.get_samples_for_trial(trial_id)
                    if not samples.empty:
                        split_dist = int(metric.split("_")[2])
                        split_origin_t_s = trial["split_origin_t_s"]
                        t_reach = find_t_reach(samples, split_dist)
                        valid_mask = get_valid_window_mask(samples, split_origin_t_s, t_reach)
                        valid_samples = samples[valid_mask]
                        splits = compute_custom_splits(valid_samples, split_origin_t_s or 0, split_dist, split_dist)
                        value = splits["cumulative_time_s"].iloc[-1] if not splits.empty else None
                    else:
                        value = None
                
                if value is not None:
                    trend_data.append({"Date": trial["session_date"], "Value": value})
            
            if trend_data:
                trend_df = pd.DataFrame(trend_data).sort_values("Date")
                
                fig = px.line(
                    trend_df,
                    x="Date",
                    y="Value",
                    markers=True,
                    title=f"Trend: {['Peak Velocity', '10m Time', '30m Time', '60m Time'][['peak_v_ms', 'split_time_10m', 'split_time_30m', 'split_time_60m'].index(metric)]}",
                )
                fig.update_layout(height=400, template="plotly_dark")
                st.plotly_chart(fig, use_container_width=True)
                
                # Stats
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Latest", f"{trend_df['Value'].iloc[-1]:.2f}")
                with col2:
                    best = trend_df['Value'].max() if "peak" in metric else trend_df['Value'].min()
                    st.metric("Best", f"{best:.2f}")
                with col3:
                    change = trend_df['Value'].iloc[-1] - trend_df['Value'].iloc[0]
                    st.metric("Change", f"{change:+.2f}")
            else:
                st.info("No trend data available.")

else:
    # MODE B: Athlete Comparison
    st.header("Mode B: Athlete Comparison")
    
    selected_trials = db.get_trials_by_ids(selected_trial_ids)
    
    # Check comparability
    is_comparable, comp_message = check_comparability(selected_trials)
    st.info(comp_message)
    
    if not is_comparable:
        # Filter to comparable trials
        reference_trial = selected_trials.iloc[0]
        comparable_trials, excluded_ids = filter_comparable_trials(selected_trials, reference_trial)
        
        if excluded_ids:
            excluded_info = []
            for trial_id in excluded_ids:
                trial = selected_trials[selected_trials["trial_id"] == trial_id].iloc[0]
                excluded_info.append(f"- {trial['athlete_name']} {trial['distance_m']:.0f}m from {trial['start_position']}")
            
            st.warning(f"⚠️ {len(excluded_ids)} trial(s) excluded (not comparable):\n\n" + "\n".join(excluded_info))
            selected_trials = comparable_trials
            selected_trial_ids = comparable_trials["trial_id"].tolist()
    
    if not selected_trials.empty:
        # Create tabs
        tab_overlay, tab_splits_cum, tab_splits_vel, tab_info = st.tabs(
            ["Overlay Plot", "Split Times", "Split Velocities", "Trial Info"]
        )
        
        with tab_overlay:
            st.subheader("Velocity Profile Overlay - Mode B (Athlete Comparison)")
            
            # Build overlay plot
            fig = go.Figure()
            
            for _, trial in selected_trials.iterrows():
                trial_id = trial["trial_id"]
                samples = db.get_samples_for_trial(trial_id)
                
                if samples.empty:
                    continue
                
                # Apply time-based valid window
                distance_m = trial["distance_m"]
                split_origin_t_s = trial["split_origin_t_s"]
                t_reach = find_t_reach(samples, distance_m)
                valid_mask = get_valid_window_mask(samples, split_origin_t_s, t_reach)
                samples_valid = samples[valid_mask]
                
                # Create trace with athlete label
                label = trial["athlete_name"]
                
                fig.add_trace(go.Scatter(
                    x=samples_valid["dist_filt_m"],
                    y=samples_valid["vel_ms"],
                    mode="lines",
                    name=label,
                    line=dict(width=2.5),
                ))
                
                # Mark peak velocity
                if trial["peak_v_ms"] and trial["peak_v_distance_m"]:
                    fig.add_trace(go.Scatter(
                        x=[trial["peak_v_distance_m"]],
                        y=[trial["peak_v_ms"]],
                        mode="markers",
                        marker=dict(size=10, symbol="star", color="gold"),
                        name=f"Peak {label}",
                        showlegend=False,
                    ))
            
            fig.update_layout(
                title="Velocity vs. Filtered Distance (Athlete Comparison)",
                xaxis_title="Filtered Distance (m)",
                yaxis_title="Velocity (m/s)",
                hovermode="x unified",
                height=600,
                template="plotly_dark",
            )
            st.plotly_chart(fig, use_container_width=True)
        
        with tab_splits_cum:
            st.subheader(f"Cumulative Split Times at {split_interval}m Intervals")
            
            # Build Mode B matrix
            cum_matrix, vel_matrix, athlete_info = build_split_matrix_mode_b(
                selected_trials,
                db,
                split_interval,
            )
            
            if not cum_matrix.empty:
                st.dataframe(cum_matrix.style.format("{:.3f}"), use_container_width=True)
                st.caption("Rows: Split distances | Columns: Athletes (each column = one chosen trial)")
                
                # Highlight fastest time per row
                best_per_row = cum_matrix.min(axis=1)
                st.write(f"**Fastest times per split**: {', '.join([f'{d:.0f}m: {t:.3f}s' for d, t in best_per_row.items()])}")
                
                # Download
                csv_str = cum_matrix.to_csv()
                st.download_button(
                    "📥 Download Split Times as CSV",
                    csv_str,
                    f"mode_b_split_times_{split_interval}m.csv",
                    "text/csv",
                )
            else:
                st.warning("No split data available.")
        
        with tab_splits_vel:
            st.subheader(f"Velocity at Split ({split_interval}m Intervals)")
            
            cum_matrix, vel_matrix, athlete_info = build_split_matrix_mode_b(
                selected_trials,
                db,
                split_interval,
            )
            
            if not vel_matrix.empty:
                st.dataframe(vel_matrix.style.format("{:.2f}"), use_container_width=True)
                st.caption("Rows: Split distances | Columns: Athletes (each column = one chosen trial)")
                
                # Highlight fastest velocity per row
                best_per_row = vel_matrix.max(axis=1)
                st.write(f"**Fastest velocities per split**: {', '.join([f'{d:.0f}m: {v:.2f}m/s' for d, v in best_per_row.items()])}")
                
                # Download
                csv_str = vel_matrix.to_csv()
                st.download_button(
                    "📥 Download Split Velocities as CSV",
                    csv_str,
                    f"mode_b_split_velocities_{split_interval}m.csv",
                    "text/csv",
                )
            else:
                st.warning("No velocity data available.")
        
        with tab_info:
            st.subheader("Comparison Trial Info")
            
            # Show athlete info
            for _, trial in selected_trials.iterrows():
                with st.expander(f"👤 {trial['athlete_name']}"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**Peak Velocity**: {trial['peak_v_ms']:.2f} m/s")
                        st.write(f"**Peak Distance**: {trial['peak_v_distance_m']:.1f} m")
                    with col2:
                        st.write(f"**Test Date**: {trial['session_date']}")
                        st.write(f"**Distance**: {trial['distance_m']:.0f} m")
                    
                    st.write(f"**Conditions**: {trial.get('wind', 'N/A')} wind, {trial.get('surface', 'N/A')} surface")

