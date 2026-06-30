"""
parser.py: SprintScope Test Export CSV parser.

Handles:
- Format detection (must start with "# SprintScope Test Export")
- Metadata extraction (lines starting with #)
- Dual-table data parsing (time series + device splits in one row)
- Returns typed dicts and DataFrames for further processing
"""

import hashlib
import re
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import pandas as pd
import numpy as np


def compute_file_hash(file_path: str) -> str:
    """Compute SHA256 hash of file bytes."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        hasher.update(f.read())
    return hasher.hexdigest()


def is_temp_file(filename: str) -> bool:
    """Check if file is a OneDrive temp file or should be ignored."""
    return (
        filename.startswith("~$")
        or filename.endswith(".tmp")
        or filename == ".DS_Store"
    )


def parse_numeric_with_unit(value: str) -> Optional[float]:
    """
    Parse numeric value with optional unit suffix (e.g., '60 m' -> 60.0).
    Returns None if not parseable.
    """
    if not value:
        return None
    
    value = value.strip()
    try:
        # Extract leading numeric part
        match = re.match(r"^([-+]?[0-9]*\.?[0-9]+)", value)
        if match:
            return float(match.group(1))
    except (ValueError, AttributeError):
        pass
    return None


def extract_event_token(athlete_name: str) -> Tuple[str, Optional[str]]:
    """
    Extract trailing event token from athlete name.
    E.g., 'Bandar 400mH' -> ('Bandar', '400mH')
    
    Recognizes: 100m, 200m, 400m, 800m, 1500m, 110mH, 400mH, 60m,
                LJ, TJ, PV, SP, HJ, etc.
    """
    known_events = {
        "100m", "200m", "400m", "800m", "1500m", "60m",
        "110mH", "400mH", "100mH", "300mH",
        "LJ", "TJ", "PV", "SP", "HJ", "DT", "HT", "JT", "WT",
    }
    
    parts = athlete_name.strip().split()
    if not parts:
        return athlete_name, None
    
    last_part = parts[-1]
    if last_part in known_events:
        athlete_clean = " ".join(parts[:-1])
        return athlete_clean, last_part
    
    return athlete_name, None


def parse_metadata(lines: list) -> Dict[str, Any]:
    """
    Parse metadata section (lines starting with # Key:,Value).
    Stop at line that is just '#'.
    Returns dict of parsed metadata.
    """
    metadata = {}
    for line in lines:
        line = line.rstrip("\r\n")
        if line == "#":
            break
        if line.startswith("# "):
            # Format: # Key:,Value
            content = line[2:]  # Remove "# "
            if ":" in content:
                key, value = content.split(":", 1)
                key = key.strip()
                value = value.lstrip(",").strip()
                metadata[key] = value
    
    return metadata


def parse_sprintscope_csv(file_path: str) -> Optional[Dict[str, Any]]:
    """
    Parse a SprintScope Test Export CSV file.
    
    Returns a dict with:
    - 'metadata': dict of parsed metadata
    - 'samples': DataFrame with columns [t_s, dist_raw_m, dist_filt_m, vel_ms, accel_ms2]
    - 'device_splits': DataFrame with columns [split_distance_m, delta_time_s, cumulative_time_s, split_velocity_ms]
    - 'file_hash': SHA256 hash of file bytes
    
    Returns None if file is unrecognized or malformed.
    """
    
    file_path_obj = Path(file_path)
    
    # Check for temp files
    if is_temp_file(file_path_obj.name):
        return None
    
    # Check file size
    if file_path_obj.stat().st_size == 0:
        return None
    
    try:
        # Read entire file
        with open(file_path, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
        
        if not all_lines:
            return None
        
        # Check format signature
        first_line = all_lines[0].rstrip("\r\n")
        if not first_line.startswith("# SprintScope Test Export"):
            return None
        
        # Parse metadata
        metadata = parse_metadata(all_lines)
        
        # Find header line (must match exactly)
        header_idx = None
        expected_header = "Time [s],Distance [m],,Distance_Filtered [m],Velocity [m/s],Acceleration [m/s^2],,Split Distance [m],Delta Time [s],Cumulative Time [s],Split Velocity [m/s]"
        
        for i, line in enumerate(all_lines):
            if line.rstrip("\r\n") == expected_header:
                header_idx = i
                break
        
        if header_idx is None:
            # Log warning but don't crash
            return None
        
        # Parse data rows
        samples_list = []
        device_splits_list = []
        
        for i in range(header_idx + 1, len(all_lines)):
            line = all_lines[i].rstrip("\r\n")
            if not line.strip():
                continue
            
            parts = line.split(",")
            
            # Expected: 11 columns (indices 0-10)
            # 0: Time [s]
            # 1: Distance [m]
            # 2: (empty)
            # 3: Distance_Filtered [m]
            # 4: Velocity [m/s]
            # 5: Acceleration [m/s^2]
            # 6: (empty)
            # 7: Split Distance [m]
            # 8: Delta Time [s]
            # 9: Cumulative Time [s]
            # 10: Split Velocity [m/s]
            
            if len(parts) < 11:
                continue
            
            try:
                # Time series columns
                t_s = float(parts[0])
                dist_raw = float(parts[1]) if parts[1].strip() else 0.0
                dist_filt = float(parts[3]) if parts[3].strip() else 0.0
                vel_ms = float(parts[4]) if parts[4].strip() else 0.0
                accel_ms2 = float(parts[5]) if parts[5].strip() else 0.0
                
                samples_list.append({
                    "t_s": t_s,
                    "dist_raw_m": dist_raw,
                    "dist_filt_m": dist_filt,
                    "vel_ms": vel_ms,
                    "accel_ms2": accel_ms2,
                })
                
                # Device splits columns (only if present and not blank)
                if parts[7].strip():
                    split_dist = float(parts[7])
                    split_dt = float(parts[8]) if parts[8].strip() else None
                    split_cum_t = float(parts[9]) if parts[9].strip() else None
                    split_vel = float(parts[10]) if parts[10].strip() else None
                    
                    device_splits_list.append({
                        "split_distance_m": split_dist,
                        "delta_time_s": split_dt,
                        "cumulative_time_s": split_cum_t,
                        "split_velocity_ms": split_vel,
                    })
            except (ValueError, IndexError):
                # Skip malformed rows
                continue
        
        if not samples_list:
            return None
        
        # Compute file hash
        file_hash = compute_file_hash(file_path)
        
        # Build result
        return {
            "metadata": metadata,
            "samples": pd.DataFrame(samples_list),
            "device_splits": pd.DataFrame(device_splits_list) if device_splits_list else pd.DataFrame(),
            "file_hash": file_hash,
        }
    
    except Exception as e:
        # Quarantine: log but don't crash
        print(f"Error parsing {file_path}: {e}")
        return None


def prepare_trial_record(
    parsed_data: Dict[str, Any],
    file_path: str,
    event_group: str,
) -> Dict[str, Any]:
    """
    Transform parsed CSV data into a trial record for database insertion.
    
    Handles:
    - Athlete name cleaning (extract event token)
    - Numeric metadata parsing (strip units)
    - Distance determination (Section 5 priority)
    - Flags (short trial detection deferred to splits.py)
    
    Returns dict with keys:
    - test_id, athlete_raw, athlete_name, event_token, file_hash
    - test_type, datetime, session_date
    - distance_m, distance_meta_m, distance_source
    - splits_every_m, start_position, surface, footwear, wind, weather, venue
    - zero_offset, filter, filter_params
    - (peak_v_ms, peak_v_distance_m, split_origin_t_s, flag_short_trial are computed by splits.py)
    - source_file, source_filename, event_group, imported_at
    """
    
    metadata = parsed_data["metadata"]
    samples_df = parsed_data["samples"]
    file_hash = parsed_data["file_hash"]
    
    record = {
        "test_id": metadata.get("Test ID", ""),
        "file_hash": file_hash,
        "source_file": file_path,
        "source_filename": Path(file_path).name,
        "event_group": event_group,
    }
    
    # Athlete
    athlete_raw = metadata.get("Athlete", "")
    athlete_clean, event_token = extract_event_token(athlete_raw)
    record["athlete_raw"] = athlete_raw
    record["athlete_name"] = athlete_clean
    record["event_token"] = event_token
    
    # Test metadata
    record["test_type"] = metadata.get("Test Type", "")
    
    # Date parsing
    date_str = metadata.get("Date", "")
    record["datetime"] = date_str  # Store as-is, expect ISO format
    if date_str:
        # Extract date only (YYYY-MM-DD)
        record["session_date"] = date_str.split(" ")[0] if " " in date_str else date_str
    else:
        record["session_date"] = None
    
    # Distance determination (Section 5)
    distance_meta = parse_numeric_with_unit(metadata.get("Distance", ""))
    record["distance_meta_m"] = distance_meta
    
    if distance_meta is not None:
        record["distance_m"] = distance_meta
        record["distance_source"] = "metadata"
    else:
        # Estimate from device splits or filtered distance
        estimated_dist = None
        
        # Try device splits (largest split distance)
        if not parsed_data["device_splits"].empty:
            max_split = parsed_data["device_splits"]["split_distance_m"].max()
            if pd.notna(max_split) and max_split > 0:
                estimated_dist = max_split
        
        # Try filtered distance (largest value, excluding run-out decay)
        if estimated_dist is None and not samples_df.empty:
            max_dist_filt = samples_df["dist_filt_m"].max()
            if max_dist_filt > 0:
                estimated_dist = max_dist_filt
        
        if estimated_dist is not None:
            record["distance_m"] = estimated_dist
            record["distance_source"] = "estimated"
        else:
            record["distance_m"] = None
            record["distance_source"] = "missing"
    
    # Numeric metadata (strip units)
    record["splits_every_m"] = parse_numeric_with_unit(metadata.get("Splits Every", ""))
    record["zero_offset"] = parse_numeric_with_unit(metadata.get("Zero Offset", ""))
    
    # String metadata
    record["start_position"] = metadata.get("Start Position", "")
    record["surface"] = metadata.get("Surface", "")
    record["footwear"] = metadata.get("Footwear", "")
    record["wind"] = metadata.get("Wind", "")
    record["weather"] = metadata.get("Weather", "")
    record["venue"] = metadata.get("Venue", "")
    record["filter"] = metadata.get("Filter", "")
    record["filter_params"] = metadata.get("Filter Params", "")
    
    # Placeholder for fields computed by splits.py
    record["peak_v_ms"] = None
    record["peak_v_distance_m"] = None
    record["split_origin_t_s"] = None
    record["flag_short_trial"] = None
    record["notes"] = ""
    
    return record
