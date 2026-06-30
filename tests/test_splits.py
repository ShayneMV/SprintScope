"""
tests/test_splits.py: Unit tests for splits.py

Validates:
- Split origin (Distance_Filtered = 0 crossing)
- Peak velocity (device marker, not raw column max)
- Custom splits at native interval vs device_splits tolerance
"""

import pytest
import pandas as pd
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from _app.parser import parse_sprintscope_csv, prepare_trial_record
from _app.splits import (
    find_zero_crossing,
    find_peak_velocity,
    compute_custom_splits,
    validate_custom_splits,
    check_short_trial,
    compute_trial_metrics,
    interpolate_at_distance,
)


@pytest.fixture
def sample_csv_path():
    """Return path to sample CSV file."""
    return Path(__file__).parent.parent / "sprints" / "Bandar_400mH_Sprint_60m_Sample.csv"


@pytest.fixture
def parsed_sample(sample_csv_path):
    """Parse the sample CSV."""
    parsed = parse_sprintscope_csv(str(sample_csv_path))
    assert parsed is not None, "Sample CSV must parse successfully"
    return parsed


class TestSplitOrigin:
    """Test split_origin_t_s computation (Distance_Filtered = 0 crossing)."""
    
    def test_zero_crossing_exists(self, parsed_sample):
        """Verify that Distance_Filtered crosses 0 in sample data."""
        samples_df = parsed_sample["samples"]
        t_origin = find_zero_crossing(samples_df)
        
        # Acceptance test: split_origin_t_s ~= 8.24
        assert t_origin is not None, "Must find zero crossing"
        assert 8.0 < t_origin < 8.5, f"Split origin should be ~8.24, got {t_origin}"
    
    def test_zero_crossing_interpolation(self, parsed_sample):
        """Verify interpolation accuracy."""
        samples_df = parsed_sample["samples"]
        t_origin = find_zero_crossing(samples_df)
        
        # Find bracketing samples
        dist_filt = samples_df["dist_filt_m"].values
        t_s = samples_df["t_s"].values
        
        # The crossing time should fall between two samples
        distances_at_origin = samples_df[
            (samples_df["t_s"] >= t_origin - 0.01) & 
            (samples_df["t_s"] <= t_origin + 0.01)
        ]["dist_filt_m"]
        
        # At t_origin, distance should be very close to 0
        assert distances_at_origin.min() < 0.1, "Interpolated crossing should be near 0"


class TestPeakVelocity:
    """Test peak velocity computation."""
    
    def test_peak_v_from_device_marker(self, parsed_sample):
        """Verify peak V is taken from device marker (delta_time_s == 0)."""
        samples_df = parsed_sample["samples"]
        device_splits_df = parsed_sample["device_splits"]
        
        t_origin = find_zero_crossing(samples_df)
        peak_v_ms, peak_v_distance_m = find_peak_velocity(
            samples_df, device_splits_df, t_origin or 0, 60.0
        )
        
        # Acceptance test: peak_v_ms ~= 9.855 at peak_v_distance_m ~= 49.53
        assert peak_v_ms is not None, "Must find peak velocity"
        assert 9.5 < peak_v_ms < 10.2, f"Peak V should be ~9.855, got {peak_v_ms}"
        assert peak_v_distance_m is not None
        # Peak should be before finish line (60m)
        assert 45 < peak_v_distance_m < 55, f"Peak should be ~49.53m, got {peak_v_distance_m}"
    
    def test_peak_v_not_raw_max(self, parsed_sample):
        """Verify peak V is NOT the raw column max (which has artifacts > 100 m/s)."""
        samples_df = parsed_sample["samples"]
        
        raw_max = samples_df["vel_ms"].max()
        # Raw data should have spurious high values in run-out
        assert raw_max > 20, "Sample should have some high velocity artifacts"
        
        # But our computed peak should be reasonable
        device_splits_df = parsed_sample["device_splits"]
        t_origin = find_zero_crossing(samples_df)
        peak_v_ms, _ = find_peak_velocity(
            samples_df, device_splits_df, t_origin or 0, 60.0
        )
        
        assert peak_v_ms is not None
        assert peak_v_ms < 12, f"Peak V should be ~10, not {peak_v_ms} (raw max was {raw_max})"


class TestCustomSplits:
    """Test custom split computation."""
    
    def test_custom_splits_generated(self, parsed_sample):
        """Verify custom splits are generated at correct intervals."""
        samples_df = parsed_sample["samples"]
        device_splits_df = parsed_sample["device_splits"]
        
        t_origin = find_zero_crossing(samples_df)
        
        custom_splits = compute_custom_splits(
            samples_df, t_origin or 0, 60.0, 10.0
        )
        
        # Should have 6 splits (10, 20, 30, 40, 50, 60 m)
        assert len(custom_splits) == 6, f"Expected 6 splits at 10m intervals, got {len(custom_splits)}"
        
        # Distances should be exact
        expected_distances = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
        actual_distances = custom_splits["split_distance_m"].tolist()
        assert actual_distances == expected_distances
    
    def test_custom_splits_match_device(self, parsed_sample):
        """Verify custom splits match device splits within tolerance."""
        samples_df = parsed_sample["samples"]
        device_splits_df = parsed_sample["device_splits"]
        
        t_origin = find_zero_crossing(samples_df)
        
        custom_splits = compute_custom_splits(
            samples_df, t_origin or 0, 60.0, 10.0
        )
        
        # Acceptance test: cumulative times should match device within 0.03s
        # Device cumulative times: 1.455 / 2.588 / 3.640 / 4.663 / 5.682 / 6.704
        expected_cumulative = [1.455, 2.588, 3.640, 4.663, 5.682, 6.704]
        
        for i, (_, row) in enumerate(custom_splits.iterrows()):
            if i < len(expected_cumulative):
                cum_t = row["cumulative_time_s"]
                expected = expected_cumulative[i]
                diff = abs(cum_t - expected)
                assert diff < 0.03, (
                    f"Split {i+1} (10m*{i+1}): cumulative time {cum_t:.3f} "
                    f"differs from expected {expected:.3f} by {diff:.3f}s"
                )
    
    def test_velocity_at_split(self, parsed_sample):
        """Verify velocity at split points."""
        samples_df = parsed_sample["samples"]
        
        t_origin = find_zero_crossing(samples_df)
        
        custom_splits = compute_custom_splits(
            samples_df, t_origin or 0, 60.0, 10.0
        )
        
        # Acceptance test: velocity at 10m ~= 8.28 m/s, at 60m ~= 9.08 m/s
        v_at_10m = custom_splits[custom_splits["split_distance_m"] == 10.0]["velocity_at_split_ms"].values
        v_at_60m = custom_splits[custom_splits["split_distance_m"] == 60.0]["velocity_at_split_ms"].values
        
        assert len(v_at_10m) > 0, "Must have velocity at 10m"
        assert len(v_at_60m) > 0, "Must have velocity at 60m"
        
        v_10 = v_at_10m[0]
        v_60 = v_at_60m[0]
        
        # Allow ±0.5 m/s tolerance
        assert 7.8 < v_10 < 8.8, f"Velocity at 10m should be ~8.28, got {v_10}"
        assert 8.5 < v_60 < 9.5, f"Velocity at 60m should be ~9.08, got {v_60}"


class TestInterpolation:
    """Test distance-based interpolation."""
    
    def test_interpolate_at_distance_exists(self, parsed_sample):
        """Verify interpolation works for distances in range."""
        samples_df = parsed_sample["samples"]
        
        # Test a few distances
        for dist in [10.0, 30.0, 50.0]:
            result = interpolate_at_distance(samples_df, dist)
            assert result is not None, f"Must interpolate at {dist}m"
            t_s, v_ms = result
            assert t_s > 0, f"Time at {dist}m must be positive"
            assert 0 < v_ms < 15, f"Velocity at {dist}m must be reasonable, got {v_ms}"


class TestShortTrialFlag:
    """Test short trial detection."""
    
    def test_normal_trial_not_flagged(self, parsed_sample):
        """Verify normal trial (reaches stated distance) is not flagged."""
        samples_df = parsed_sample["samples"]
        
        flag = check_short_trial(samples_df, 60.0)
        assert flag == False, "Normal trial should not be flagged as short"


class TestIntegration:
    """Integration test: full metrics computation."""
    
    def test_full_trial_metrics(self, parsed_sample):
        """Compute all metrics and verify against acceptance test."""
        samples_df = parsed_sample["samples"]
        device_splits_df = parsed_sample["device_splits"]
        
        metrics = compute_trial_metrics(
            samples_df, device_splits_df, 60.0, 10.0
        )
        
        # All critical fields must be present
        assert metrics["split_origin_t_s"] is not None
        assert metrics["peak_v_ms"] is not None
        assert metrics["peak_v_distance_m"] is not None
        assert isinstance(metrics["custom_splits"], pd.DataFrame)
        assert len(metrics["custom_splits"]) > 0
        
        # Acceptance criteria
        assert 8.0 < metrics["split_origin_t_s"] < 8.5
        assert 9.5 < metrics["peak_v_ms"] < 10.2
        assert 45 < metrics["peak_v_distance_m"] < 55
        
        # Warnings should be empty or minimal (validation passes)
        assert isinstance(metrics["validation_warnings"], list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
