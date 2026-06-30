"""
comparison.py: Comparison modes for laser velocity analysis.

Handles:
- Mode A: Athlete progression (one athlete over time)
- Mode B: Athlete comparison (multiple athletes)
- Comparability guards (distance + start_position matching)
- Split matrices (cumulative time and velocity at split)
- Trial condition display rows
"""

from typing import Dict, List, Tuple, Optional
import pandas as pd
import numpy as np
from _app.splits import find_zero_crossing, find_t_reach, get_valid_window_mask, compute_custom_splits


def check_comparability(trials_df: pd.DataFrame) -> Tuple[bool, str]:
    """
    Check if trials are comparable (same distance + start_position).
    
    Returns (is_comparable, message).
    """
    if trials_df.empty:
        return False, "No trials selected."
    
    if len(trials_df) == 1:
        return True, f"Single trial: {trials_df.iloc[0]['distance_m']:.0f}m from {trials_df.iloc[0]['start_position']}"
    
    # Check distance consistency
    distances = trials_df["distance_m"].unique()
    if len(distances) > 1:
        dist_str = ", ".join([f"{d:.0f}m" for d in sorted(distances)])
        return False, f"⚠️ Mixed distances: {dist_str}. Must be same distance."
    
    # Check start_position consistency
    positions = trials_df["start_position"].dropna().unique()
    if len(positions) > 1:
        pos_str = ", ".join(positions)
        return False, f"⚠️ Mixed start positions: {pos_str}. Must be same position."
    
    start_pos = positions[0] if len(positions) > 0 else "Unknown"
    distance = distances[0]
    
    return True, f"Comparable trials: {distance:.0f}m from {start_pos}"


def filter_comparable_trials(all_trials_df: pd.DataFrame, reference_trial: pd.Series) -> Tuple[pd.DataFrame, List[int]]:
    """
    Filter trials to only those matching reference trial's distance + start_position.
    
    Returns (comparable_trials, excluded_trial_ids).
    """
    if all_trials_df.empty:
        return pd.DataFrame(), []
    
    ref_distance = reference_trial["distance_m"]
    ref_position = reference_trial["start_position"]
    
    comparable_mask = (all_trials_df["distance_m"] == ref_distance) & (all_trials_df["start_position"] == ref_position)
    comparable = all_trials_df[comparable_mask]
    
    excluded_ids = all_trials_df[~comparable_mask]["trial_id"].tolist()
    
    return comparable, excluded_ids


def build_split_matrix_mode_a(
    trials_df: pd.DataFrame,
    db,
    split_interval_m: float,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Build split matrices for Mode A (athlete progression over time).
    
    Rows = split distances
    Columns = session dates (chronological)
    Cells = cumulative time
    
    Returns (cumulative_time_matrix, velocity_at_split_matrix).
    """
    if trials_df.empty:
        return pd.DataFrame(), pd.DataFrame()
    
    # Sort by session_date
    trials_sorted = trials_df.sort_values("session_date").reset_index(drop=True)
    
    # Collect splits for each trial
    all_splits = []
    trial_labels = []
    
    for _, trial in trials_sorted.iterrows():
        trial_id = trial["trial_id"]
        session_date = trial["session_date"]
        
        # Get samples
        samples = db.get_samples_for_trial(trial_id)
        if samples.empty:
            continue
        
        # Compute splits using valid window
        split_origin_t_s = trial["split_origin_t_s"]
        t_reach = find_t_reach(samples, trial["distance_m"])
        valid_mask = get_valid_window_mask(samples, split_origin_t_s, t_reach)
        valid_samples = samples[valid_mask]
        
        splits = compute_custom_splits(
            valid_samples,
            split_origin_t_s or 0,
            trial["distance_m"],
            split_interval_m,
        )
        
        if not splits.empty:
            splits["session_date"] = session_date
            splits["trial_id"] = trial_id
            all_splits.append(splits)
            trial_labels.append((session_date, trial_id))
    
    if not all_splits:
        return pd.DataFrame(), pd.DataFrame()
    
    # Combine splits
    combined = pd.concat(all_splits, ignore_index=True)
    
    # Build cumulative time matrix: rows = distance, columns = date
    cum_time_matrix = combined.pivot_table(
        index="split_distance_m",
        columns="session_date",
        values="cumulative_time_s",
        aggfunc="first"
    )
    
    # Build velocity at split matrix: rows = distance, columns = date
    vel_matrix = combined.pivot_table(
        index="split_distance_m",
        columns="session_date",
        values="velocity_at_split_ms",
        aggfunc="first"
    )
    
    # Add trial metadata row
    # This will be displayed separately
    
    return cum_time_matrix, vel_matrix


def build_split_matrix_mode_b(
    trials_df: pd.DataFrame,
    db,
    split_interval_m: float,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict]:
    """
    Build split matrices for Mode B (athlete comparison).
    
    Rows = split distances
    Columns = athlete names (each = their chosen trial)
    Cells = cumulative time
    
    Returns (cumulative_time_matrix, velocity_at_split_matrix, trial_info_dict).
    """
    if trials_df.empty:
        return pd.DataFrame(), pd.DataFrame(), {}
    
    # Collect splits for each athlete's trial
    all_splits = []
    athlete_info = {}
    
    for _, trial in trials_df.iterrows():
        athlete_name = trial["athlete_name"]
        trial_id = trial["trial_id"]
        
        # Get samples
        samples = db.get_samples_for_trial(trial_id)
        if samples.empty:
            continue
        
        # Compute splits using valid window
        split_origin_t_s = trial["split_origin_t_s"]
        t_reach = find_t_reach(samples, trial["distance_m"])
        valid_mask = get_valid_window_mask(samples, split_origin_t_s, t_reach)
        valid_samples = samples[valid_mask]
        
        splits = compute_custom_splits(
            valid_samples,
            split_origin_t_s or 0,
            trial["distance_m"],
            split_interval_m,
        )
        
        if not splits.empty:
            splits["athlete_name"] = athlete_name
            splits["trial_id"] = trial_id
            all_splits.append(splits)
            
            athlete_info[athlete_name] = {
                "trial_id": trial_id,
                "date": trial["session_date"],
                "peak_v": trial["peak_v_ms"],
            }
    
    if not all_splits:
        return pd.DataFrame(), pd.DataFrame(), {}
    
    # Combine splits
    combined = pd.concat(all_splits, ignore_index=True)
    
    # Build cumulative time matrix: rows = distance, columns = athlete
    cum_time_matrix = combined.pivot_table(
        index="split_distance_m",
        columns="athlete_name",
        values="cumulative_time_s",
        aggfunc="first"
    )
    
    # Build velocity at split matrix: rows = distance, columns = athlete
    vel_matrix = combined.pivot_table(
        index="split_distance_m",
        columns="athlete_name",
        values="velocity_at_split_ms",
        aggfunc="first"
    )
    
    return cum_time_matrix, vel_matrix, athlete_info


def get_trial_conditions_row(trial: pd.Series) -> Dict[str, str]:
    """
    Extract trial conditions for display.
    
    Returns dict with wind, surface, footwear, etc.
    """
    return {
        "Wind": trial.get("wind", "N/A"),
        "Surface": trial.get("surface", "N/A"),
        "Footwear": trial.get("footwear", "N/A"),
        "Venue": trial.get("venue", "N/A"),
    }


def format_matrix_for_display(matrix_df: pd.DataFrame, format_str: str = ".3f") -> pd.DataFrame:
    """
    Format matrix values for display (e.g., ".3f" for 3 decimal places).
    """
    if matrix_df.empty:
        return matrix_df
    
    # Round numeric columns
    formatted = matrix_df.copy()
    for col in formatted.columns:
        if pd.api.types.is_numeric_dtype(formatted[col]):
            formatted[col] = formatted[col].apply(lambda x: f"{x:{format_str}}" if pd.notna(x) else "")
    
    return formatted
