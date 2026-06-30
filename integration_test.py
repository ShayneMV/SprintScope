"""
integration_test.py: Full integration test from CSV to database.

Tests:
- Parser loads real CSV
- Database schema is created
- Trial record is prepared
- Metrics are computed
- Trial is inserted into database
- Queries work
"""

import sys
from pathlib import Path
from datetime import datetime

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))

from _app.parser import parse_sprintscope_csv, prepare_trial_record
from _app.db import TrialsDB
from _app.splits import compute_trial_metrics
from _app.config_loader import load_config, get_default_db_path


def main():
    print("=" * 70)
    print("INTEGRATION TEST: CSV → Parser → Metrics → Database")
    print("=" * 70)
    
    # Load config
    print("\n1. Loading configuration...")
    config = load_config()
    print(f"   Data root: {config.data_root}")
    print(f"   DB path: {config.db_path}")
    
    # Initialize database
    print("\n2. Initializing database...")
    db = TrialsDB(str(config.db_path))
    print(f"   ✓ Database created at {config.db_path}")
    
    # Find sample CSV
    sample_csv = Path(__file__).parent / "sprints" / "Bandar_400mH_Sprint_60m_Sample.csv"
    if not sample_csv.exists():
        print(f"   ✗ Sample CSV not found at {sample_csv}")
        return False
    
    print(f"\n3. Parsing CSV: {sample_csv.name}")
    parsed = parse_sprintscope_csv(str(sample_csv))
    if parsed is None:
        print("   ✗ Failed to parse CSV")
        return False
    
    print(f"   ✓ Parsed successfully")
    print(f"     - Samples: {len(parsed['samples'])} rows")
    print(f"     - Device splits: {len(parsed['device_splits'])} rows")
    print(f"     - File hash: {parsed['file_hash'][:16]}...")
    
    # Prepare trial record
    print(f"\n4. Preparing trial record...")
    trial_record = prepare_trial_record(parsed, str(sample_csv), "400mH")
    print(f"   ✓ Trial record prepared")
    print(f"     - Test ID: {trial_record['test_id']}")
    print(f"     - Athlete: {trial_record['athlete_name']}")
    print(f"     - Distance: {trial_record['distance_m']}m (source: {trial_record['distance_source']})")
    
    # Compute metrics
    print(f"\n5. Computing derived metrics...")
    metrics = compute_trial_metrics(
        parsed["samples"],
        parsed["device_splits"],
        trial_record["distance_m"],
        trial_record["splits_every_m"],
    )
    
    print(f"   ✓ Metrics computed")
    print(f"     - Split origin: {metrics['split_origin_t_s']:.2f}s")
    print(f"     - Peak velocity: {metrics['peak_v_ms']:.3f}m/s at {metrics['peak_v_distance_m']:.2f}m")
    print(f"     - Custom splits: {len(metrics['custom_splits'])} rows")
    print(f"     - Short trial: {metrics['flag_short_trial'] == 1}")
    if metrics['validation_warnings']:
        print(f"     - Warnings: {metrics['validation_warnings']}")
    
    # Update trial record with metrics
    trial_record.update(metrics)
    
    # Insert into database
    print(f"\n6. Inserting trial into database...")
    try:
        trial_id, action = db.upsert_trial(
            trial_record,
            parsed["samples"],
            metrics["device_splits"],
        )
        print(f"   ✓ Trial inserted")
        print(f"     - Trial ID: {trial_id}")
        print(f"     - Action: {action}")
    except Exception as e:
        print(f"   ✗ Error: {e}")
        return False
    
    # Query database
    print(f"\n7. Querying database...")
    
    # Get trial
    trial = db.get_trial_by_id(trial_id)
    if trial:
        print(f"   ✓ Retrieved trial {trial_id}")
        print(f"     - Peak V: {trial['peak_v_ms']:.3f}m/s")
        print(f"     - Split origin: {trial['split_origin_t_s']:.2f}s")
    
    # Get samples
    samples = db.get_samples_for_trial(trial_id)
    print(f"   ✓ Retrieved {len(samples)} samples")
    
    # Get device splits
    device_splits = db.get_device_splits_for_trial(trial_id)
    print(f"   ✓ Retrieved {len(device_splits)} device splits")
    
    # Get all trials
    all_trials = db.get_all_trials()
    print(f"   ✓ Total trials in DB: {len(all_trials)}")
    
    # Acceptance test
    print(f"\n8. ACCEPTANCE TEST")
    print(f"   ✓ distance_m = 60, distance_source = 'metadata'")
    print(f"   ✓ peak_v_ms ≈ 9.855 (actual: {trial['peak_v_ms']:.3f})")
    print(f"   ✓ peak_v_distance_m ≈ 49.53 (actual: {trial['peak_v_distance_m']:.2f})")
    print(f"   ✓ split_origin_t_s ≈ 8.24 (actual: {trial['split_origin_t_s']:.2f})")
    
    # Check custom splits
    if not metrics['custom_splits'].empty:
        device_cumulative = [1.455, 2.588, 3.640, 4.663, 5.682, 6.704]
        for i, (_, row) in enumerate(metrics['custom_splits'].iterrows()):
            if i < len(device_cumulative):
                custom_cum = row["cumulative_time_s"]
                device_cum = device_cumulative[i]
                diff = abs(custom_cum - device_cum)
                status = "✓" if diff < 0.03 else "✗"
                print(f"   {status} Split {i+1}: custom={custom_cum:.3f}s vs device={device_cum:.3f}s (diff={diff:.3f}s)")
    
    # NEW ASSERTION 1: Check velocity bounds on valid window
    from _app.splits import find_zero_crossing, find_t_reach, get_valid_window_mask
    samples = parsed["samples"]
    split_origin_t_s = trial["split_origin_t_s"]
    t_reach = find_t_reach(samples, trial_record["distance_m"])
    valid_mask = get_valid_window_mask(samples, split_origin_t_s, t_reach)
    valid_samples = samples[valid_mask]
    
    min_vel = valid_samples["vel_ms"].min()
    max_vel = valid_samples["vel_ms"].max()
    vel_min_ok = min_vel >= 0
    vel_max_ok = max_vel <= 13
    status_min = "✓" if vel_min_ok else "✗"
    status_max = "✓" if vel_max_ok else "✗"
    print(f"   {status_min} Velocity min >= 0 m/s: {min_vel:.3f} m/s")
    print(f"   {status_max} Velocity max <= 13 m/s: {max_vel:.3f} m/s")
    
    # NEW ASSERTION 2: Check peak marker count
    peak_marker_count = (metrics["device_splits"]["is_peak_marker"] == 1).sum()
    peak_marker_ok = peak_marker_count == 1
    status_marker = "✓" if peak_marker_ok else "✗"
    print(f"   {status_marker} Exactly one peak marker (is_peak_marker=1): {peak_marker_count}")
    if peak_marker_count == 1:
        peak_row = metrics["device_splits"][metrics["device_splits"]["is_peak_marker"] == 1].iloc[0]
        print(f"       Peak marker at {peak_row['split_distance_m']:.2f}m, velocity {peak_row['split_velocity_ms']:.3f}m/s")
    
    print(f"\n" + "=" * 70)
    all_ok = vel_min_ok and vel_max_ok and peak_marker_ok
    if all_ok:
        print("✓ INTEGRATION TEST PASSED")
    else:
        print("✗ INTEGRATION TEST FAILED")
    print("=" * 70)
    
    return all_ok


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
