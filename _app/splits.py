"""
splits.py: Derived metrics computation.

Handles:
- Split origin (Distance_Filtered = 0 upward crossing with interpolation)
- Peak velocity (device marker vs computed window)
- Custom splits (interpolated split times, velocities, cumulative times)
- Validation against device splits

All functions are pure and unit-testable.
"""

from typing import Optional, Tuple, Dict, List
import pandas as pd
import numpy as np


def find_zero_crossing(samples_df: pd.DataFrame) -> Optional[float]:
    """
    Find the time when Distance_Filtered first crosses 0 upward.
    Uses linear interpolation between bracketing samples.
    
    Returns time in seconds, or None if no crossing found.
    """
    dist_filt = samples_df["dist_filt_m"].values
    t_s = samples_df["t_s"].values
    
    # Find first upward crossing of 0
    for i in range(len(dist_filt) - 1):
        if dist_filt[i] < 0 and dist_filt[i + 1] >= 0:
            # Linear interpolation
            t0, t1 = t_s[i], t_s[i + 1]
            d0, d1 = dist_filt[i], dist_filt[i + 1]
            
            # d(t) = d0 + (d1 - d0) * (t - t0) / (t1 - t0)
            # d(t) = 0 => (t - t0) = -d0 * (t1 - t0) / (d1 - d0)
            if d1 != d0:
                t_cross = t0 - d0 * (t1 - t0) / (d1 - d0)
                return t_cross
    
    return None


def find_t_reach(samples_df: pd.DataFrame, distance_m: Optional[float]) -> Optional[float]:
    """
    Find the first time when Distance_Filtered reaches target distance.
    
    If distance is never reached, returns time of maximum Distance_Filtered.
    Uses linear interpolation for the first crossing.
    
    Returns time in seconds, or None if samples are empty or distance_m is invalid.
    """
    if distance_m is None or distance_m <= 0 or samples_df.empty:
        return None
    
    dist_filt = samples_df["dist_filt_m"].values
    t_s = samples_df["t_s"].values
    
    # Find first upward crossing of target distance
    for i in range(len(dist_filt) - 1):
        if dist_filt[i] <= distance_m <= dist_filt[i + 1]:
            # Linear interpolation for exact crossing time
            d0, d1 = dist_filt[i], dist_filt[i + 1]
            t0, t1 = t_s[i], t_s[i + 1]
            
            if d1 == d0:
                return float(t0)
            
            alpha = (distance_m - d0) / (d1 - d0)
            t_reach = t0 + alpha * (t1 - t0)
            return float(t_reach)
    
    # Distance never reached: use time of max distance
    max_idx = np.argmax(dist_filt)
    return float(t_s[max_idx])


def get_valid_window_mask(
    samples_df: pd.DataFrame,
    split_origin_t_s: Optional[float],
    t_reach: Optional[float],
) -> np.ndarray:
    """
    Create boolean mask for valid time window.
    
    Valid window: split_origin_t_s <= t <= t_reach
    
    Returns boolean array (same length as samples_df).
    """
    if split_origin_t_s is None or t_reach is None or samples_df.empty:
        return np.ones(len(samples_df), dtype=bool)
    
    t_s = samples_df["t_s"].values
    return (t_s >= split_origin_t_s) & (t_s <= t_reach)


def find_peak_velocity(
    samples_df: pd.DataFrame,
    device_splits_df: pd.DataFrame,
    split_origin_t_s: float,
    distance_m: Optional[float],
) -> Tuple[Optional[float], Optional[float]]:
    """
    Compute peak velocity and distance at which it occurs.
    
    Priority:
    1. Device split marker (row where delta_time_s == 0 and distance > 0)
    2. Max of vel_ms within valid time window [split_origin_t_s, t_reach]
    
    Valid window is defined by time, not distance, to avoid end-effect artifacts.
    
    Returns (peak_v_ms, peak_v_distance_m) or (None, None).
    """
    
    # Check for device marker (delta_time_s == 0, excluding 0m start point)
    if not device_splits_df.empty:
        marker_rows = device_splits_df[
            ((device_splits_df["delta_time_s"] == 0) |
             (device_splits_df["delta_time_s"].isna())) &
            (device_splits_df["split_distance_m"] > 0)  # Exclude starting point at 0m
        ]
        if not marker_rows.empty:
            # Use the device's reported peak (should be max split_velocity_ms)
            max_idx = marker_rows["split_velocity_ms"].idxmax()
            row = marker_rows.loc[max_idx]
            peak_v = row.get("split_velocity_ms")
            peak_d = row.get("split_distance_m")
            if pd.notna(peak_v) and pd.notna(peak_d):
                return float(peak_v), float(peak_d)
    
    # No marker: compute from samples using valid time window
    t_reach = find_t_reach(samples_df, distance_m)
    mask = get_valid_window_mask(samples_df, split_origin_t_s, t_reach)
    
    valid_samples = samples_df[mask]
    
    if valid_samples.empty:
        return None, None
    
    # Find max velocity in this window
    max_idx = valid_samples["vel_ms"].idxmax()
    peak_v = valid_samples.loc[max_idx, "vel_ms"]
    peak_d = valid_samples.loc[max_idx, "dist_filt_m"]
    
    if pd.notna(peak_v) and pd.notna(peak_d):
        return float(peak_v), float(peak_d)
    
    return None, None


def interpolate_at_distance(
    samples_df: pd.DataFrame,
    target_distance: float,
) -> Optional[Tuple[float, float]]:
    """
    Find the time when dist_filt_m reaches target_distance,
    using linear interpolation.
    
    Also handles the endpoint case: if target_distance equals or exceeds the max distance,
    return the sample at maximum distance.
    
    Returns (t_s, vel_ms) at that distance, or (None, None) if distance not reached.
    """
    if samples_df.empty:
        return None, None
    
    dist_filt = samples_df["dist_filt_m"].values
    t_s = samples_df["t_s"].values
    vel_ms = samples_df["vel_ms"].values
    
    # Find max distance (forward progress)
    max_dist = np.max(dist_filt)
    
    # Check if target is at or beyond the maximum distance
    if target_distance >= max_dist - 1e-9:
        # Return the sample at maximum distance
        max_idx = np.argmax(dist_filt)
        return float(t_s[max_idx]), float(vel_ms[max_idx])
    
    # Find bracketing samples
    for i in range(len(dist_filt) - 1):
        if dist_filt[i] <= target_distance <= dist_filt[i + 1]:
            # Linear interpolation
            d0, d1 = dist_filt[i], dist_filt[i + 1]
            t0, t1 = t_s[i], t_s[i + 1]
            v0, v1 = vel_ms[i], vel_ms[i + 1]
            
            if d1 == d0:
                # Degenerate: same distance
                return float(t0), float(v0)
            
            # Interpolation factor
            alpha = (target_distance - d0) / (d1 - d0)
            t_interp = t0 + alpha * (t1 - t0)
            v_interp = v0 + alpha * (v1 - v0)
            
            return float(t_interp), float(v_interp)
    
    return None, None


def compute_custom_splits(
    samples_df: pd.DataFrame,
    split_origin_t_s: float,
    distance_m: Optional[float],
    split_interval_m: Optional[float],
) -> pd.DataFrame:
    """
    Compute custom splits at a given interval.
    
    For each split distance d in [interval_m, 2*interval_m, ...] up to distance_m:
    - Compute cumulative_time(d) = t(d) - split_origin_t_s
    - Compute split_time(d) = cumulative_time(d) - cumulative_time(d - interval)
    - Compute velocity_at(d) = instantaneous velocity at distance d
    - Compute segment_avg_velocity = interval / split_time
    
    INCLUSIVE of distance_m: Final split row is always at exactly distance_m.
    If interval does not divide evenly, still appends a final row at distance_m.
    
    Only uses samples within valid time window [split_origin_t_s, t_reach].
    
    Returns DataFrame with columns:
    [split_distance_m, cumulative_time_s, split_time_s, velocity_at_split_ms, segment_avg_velocity_ms]
    """
    
    if distance_m is None or distance_m <= 0 or split_interval_m is None or split_interval_m <= 0:
        return pd.DataFrame()
    
    # Get valid window
    t_reach = find_t_reach(samples_df, distance_m)
    mask = get_valid_window_mask(samples_df, split_origin_t_s, t_reach)
    valid_samples = samples_df[mask]
    
    if valid_samples.empty:
        return pd.DataFrame()
    
    splits = []
    prev_cumulative_time = 0.0
    split_distances = []
    
    # Generate all split distances up to distance_m
    d = split_interval_m
    while d <= distance_m + 1e-9:  # Small epsilon for floating point comparison
        split_distances.append(min(d, distance_m))  # Cap at distance_m to avoid overshoot
        if d >= distance_m - 1e-9:
            break
        d += split_interval_m
    
    # Ensure final split is exactly at distance_m
    if not split_distances or abs(split_distances[-1] - distance_m) > 1e-9:
        split_distances.append(distance_m)
    
    # Remove duplicates while preserving order
    seen = set()
    unique_distances = []
    for d in split_distances:
        d_rounded = round(d, 9)  # Round to avoid floating point duplicates
        if d_rounded not in seen:
            seen.add(d_rounded)
            unique_distances.append(d)
    
    # Compute splits for each distance
    for target_distance in unique_distances:
        # Find time at this distance using only valid samples
        result = interpolate_at_distance(valid_samples, target_distance)
        if result is None or result == (None, None):
            continue
        
        t_at_d, v_at_d = result
        
        if t_at_d is None or v_at_d is None:
            continue
        
        # Cumulative time from split origin
        cumulative_time = t_at_d - split_origin_t_s
        
        # Split time is the difference from previous split
        if not splits:
            split_time = cumulative_time
        else:
            split_time = cumulative_time - prev_cumulative_time
        
        # Segment average velocity
        if split_time > 0:
            seg_avg_v = split_interval_m / split_time
        else:
            seg_avg_v = None
        
        splits.append({
            "split_distance_m": target_distance,
            "cumulative_time_s": cumulative_time,
            "split_time_s": split_time,
            "velocity_at_split_ms": v_at_d,
            "segment_avg_velocity_ms": seg_avg_v,
        })
        
        prev_cumulative_time = cumulative_time
    
    return pd.DataFrame(splits)


def validate_custom_splits(
    custom_splits_df: pd.DataFrame,
    device_splits_df: pd.DataFrame,
    tolerance_s: float = 0.03,
) -> List[str]:
    """
    Validate computed custom splits against device splits.
    
    Logs warnings if cumulative times differ by more than tolerance_s.
    Returns list of warning messages.
    """
    warnings = []
    
    if device_splits_df.empty or custom_splits_df.empty:
        return warnings
    
    for _, custom_row in custom_splits_df.iterrows():
        split_d = custom_row["split_distance_m"]
        custom_cum_t = custom_row["cumulative_time_s"]
        
        # Find matching device split
        device_match = device_splits_df[
            device_splits_df["split_distance_m"] == split_d
        ]
        
        if not device_match.empty:
            device_cum_t = device_match.iloc[0]["cumulative_time_s"]
            if pd.notna(device_cum_t):
                diff = abs(custom_cum_t - device_cum_t)
                if diff > tolerance_s:
                    warnings.append(
                        f"Custom split at {split_d}m: cumulative time {custom_cum_t:.3f}s "
                        f"differs from device {device_cum_t:.3f}s by {diff:.3f}s"
                    )
    
    return warnings


def check_short_trial(
    samples_df: pd.DataFrame,
    distance_m: Optional[float],
    overshoot_tolerance: float = 0.25,
) -> bool:
    """
    Flag trial as short if filtered distance undershoots stated distance.
    
    Overshoot (run-out past gate) is normal; undershooting is a problem.
    
    Returns True if trial is flagged as short.
    """
    if distance_m is None or distance_m <= 0:
        return False
    
    max_dist_filt = samples_df["dist_filt_m"].max()
    
    # Undershoot: max distance is less than stated distance
    if max_dist_filt < distance_m:
        return True
    
    # Overshoot check: if we exceed distance by more than tolerance, it's suspicious
    # but we don't flag it as short (that's a different issue)
    # So we only flag short, not over.
    
    return False


def compute_trial_metrics(
    samples_df: pd.DataFrame,
    device_splits_df: pd.DataFrame,
    distance_m: Optional[float],
    splits_every_m: Optional[float],
) -> Dict[str, any]:
    """
    Compute all derived metrics for a trial.
    
    Returns dict with:
    - split_origin_t_s
    - peak_v_ms, peak_v_distance_m
    - custom_splits (DataFrame)
    - flag_short_trial
    - validation_warnings (list of strings)
    - device_splits (DataFrame with is_peak_marker set)
    """
    
    # Split origin
    split_origin_t_s = find_zero_crossing(samples_df)
    
    # Mark peak marker in device splits
    device_splits_marked = mark_peak_marker(device_splits_df)
    
    # Peak velocity
    peak_v_ms, peak_v_distance_m = find_peak_velocity(
        samples_df, device_splits_marked, split_origin_t_s or 0, distance_m
    )
    
    # Custom splits (use trial's native interval, or 10m default)
    split_interval = splits_every_m or 10.0
    custom_splits_df = compute_custom_splits(
        samples_df, split_origin_t_s or 0, distance_m, split_interval
    )
    
    # Validation
    warnings = validate_custom_splits(custom_splits_df, device_splits_marked)
    
    # Short trial flag
    flag_short = check_short_trial(samples_df, distance_m)
    
    return {
        "split_origin_t_s": split_origin_t_s,
        "peak_v_ms": peak_v_ms,
        "peak_v_distance_m": peak_v_distance_m,
        "custom_splits": custom_splits_df,
        "device_splits": device_splits_marked,
        "flag_short_trial": 1 if flag_short else 0,
        "validation_warnings": warnings,
    }


def mark_peak_marker(device_splits_df: pd.DataFrame) -> pd.DataFrame:
    """
    Mark peak velocity marker row in device splits.
    
    Sets is_peak_marker = 1 where delta_time_s == 0 AND split_distance_m > 0.
    The 0m origin row (where delta_time_s == 0 and split_distance_m == 0) stays 0.
    
    Returns new DataFrame with is_peak_marker column set.
    """
    if device_splits_df.empty:
        return device_splits_df.copy()
    
    result = device_splits_df.copy()
    
    # Initialize is_peak_marker if not present
    if "is_peak_marker" not in result.columns:
        result["is_peak_marker"] = 0
    
    # Mark peak: delta_time_s == 0 AND split_distance_m > 0
    peak_mask = (
        ((result["delta_time_s"] == 0) | (result["delta_time_s"].isna())) &
        (result["split_distance_m"] > 0)
    )
    
    result.loc[peak_mask, "is_peak_marker"] = 1
    
    return result
