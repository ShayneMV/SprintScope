"""
Generate a realistic sample SprintScope CSV file for testing.
This creates Bandar_400mH_Sprint_60m_Sample.csv with data matching acceptance test criteria.
"""

import csv
from datetime import datetime
import math

# Parameters to match acceptance test
SPLIT_ORIGIN_T = 8.24  # seconds
PEAK_V = 9.855  # m/s
PEAK_V_DISTANCE = 49.53  # meters
DISTANCE_M = 60.0  # meters

# Device split cumulative times (at 10m intervals)
DEVICE_CUMULATIVE_TIMES = [1.455, 2.588, 3.640, 4.663, 5.682, 6.704]

# Realistic velocity profile for a 60m sprint
def generate_velocity_profile(t_s):
    """
    Generate realistic velocity for time t_s (absolute file time).
    - t < 8.24: pre-gate phase, velocity ramps from 0
    - t >= 8.24: gate phase, smooth acceleration to peak ~9.855 at ~49.53m
    """
    if t_s < SPLIT_ORIGIN_T:
        # Pre-gate: ramping up from standing start
        t_rel = t_s
        return min(4.5, t_rel * 0.6)  # accelerate to ~4.5 m/s
    else:
        # Post-gate: gate phase
        t_rel = t_s - SPLIT_ORIGIN_T
        # Velocity profile: ramp to peak at ~5.06s (when distance ~49.53m)
        # Peak ~9.855, then slight decay
        if t_rel < 5.1:
            # Acceleration phase
            v = 2.0 + 7.0 * (1 - math.exp(-t_rel / 1.5))
            return min(PEAK_V, v)
        else:
            # Deceleration / plateau phase
            v = PEAK_V - 0.1 * (t_rel - 5.1) ** 1.2
            return max(8.0, v)


def generate_distance_profile(samples_list):
    """
    Integrate velocity to get distance.
    """
    dt = 0.005  # 200 Hz
    
    distances_raw = [0.0]
    distances_filt = []
    
    # Pre-gate phase (negative distance, approaching gate)
    for i, (t, _, _, v, _) in enumerate(samples_list):
        if t < SPLIT_ORIGIN_T:
            distances_raw.append(distances_raw[-1] + v * dt)
        else:
            break
    
    # Post-gate: distance resets to 0 at split origin
    # Device splits at: 10, 20, 30, 40, 50, 60
    d = 0.0
    for i, (t, _, _, v, _) in enumerate(samples_list):
        if t >= SPLIT_ORIGIN_T:
            d += v * dt
        distances_raw.append(d)
    
    # Filtered distance (light smoothing, similar to raw)
    distances_filt = [d * 0.99 + 0.01 * (distances_raw[max(0, i-2)] if i > 0 else 0) 
                      for i, d in enumerate(distances_raw)]
    
    return distances_raw, distances_filt


# Generate time series at 200 Hz
dt = 0.005
num_samples = int(20.0 / dt)  # 20 seconds of data
samples = []

for i in range(num_samples):
    t = i * dt
    v = generate_velocity_profile(t)
    accel = 0.0  # Simplified; normally computed from v derivative
    samples.append((t, 0.0, 0.0, v, accel))  # Will fill distances next

# Compute distances
distances_raw, distances_filt = generate_distance_profile(samples)

# Update samples with distances
samples_updated = []
for i, (t, _, _, v, a) in enumerate(samples):
    d_raw = distances_raw[i] if i < len(distances_raw) else 0
    d_filt = distances_filt[i] if i < len(distances_filt) else 0
    samples_updated.append((t, d_raw, d_filt, v, a))

samples = samples_updated

# Device splits (one per 10m, delta_time=0 for peak marker)
device_splits = [
    (10.0, 0.0, DEVICE_CUMULATIVE_TIMES[0], 8.28),  # delta_time=0 marks peak? No, peak is at 49.53m
    (20.0, 0.0, DEVICE_CUMULATIVE_TIMES[1], 7.5),
    (30.0, 0.0, DEVICE_CUMULATIVE_TIMES[2], 8.0),
    (40.0, 0.0, DEVICE_CUMULATIVE_TIMES[3], 8.5),
    (50.0, 0.0, DEVICE_CUMULATIVE_TIMES[4], 9.8),   # Near peak
    (60.0, 0.0, DEVICE_CUMULATIVE_TIMES[5], 9.08),
]

# Actually, delta_time == 0 marks the peak marker row
# Find the closest sample to peak and create a marker
peak_marker_split = (PEAK_V_DISTANCE, 0.0, 
                     DEVICE_CUMULATIVE_TIMES[-1] * (PEAK_V_DISTANCE / 60.0),  # approx
                     PEAK_V)

# CSV structure
metadata = {
    "Athlete": "Bandar 400mH",
    "Test ID": "TEST_20240115_001",
    "Test Type": "60m Sprint",
    "Date": "2024-01-15 10:30:00",
    "Session Type": "Competition",
    "Venue": "Track",
    "Weather": "Clear",
    "Wind": "-0.2",
    "Surface": "Synthetic",
    "Footwear": "Spikes",
    "Zero Offset": "0.0",
    "Orth. Offset": "0.0",
    "Filter": "Butterworth",
    "Filter Params": "4Hz",
    "Distance": "60 m",
    "Splits Every": "10 m",
    "Start Position": "Running start",
}

# Write CSV
output_path = "/workspace/laveg_app/sprints/Bandar_400mH_Sprint_60m_Sample.csv"

import os
os.makedirs("/workspace/laveg_app/sprints", exist_ok=True)
os.makedirs("/workspace/laveg_app/hurdles", exist_ok=True)

with open(output_path, 'w', newline='', encoding='utf-8') as f:
    # Format signature (REQUIRED)
    f.write("# SprintScope Test Export\n")
    
    # Metadata section
    for key, value in metadata.items():
        f.write(f"# {key}:,{value}\n")
    f.write("#\n")
    
    # Data header
    f.write("Time [s],Distance [m],,Distance_Filtered [m],Velocity [m/s],Acceleration [m/s^2],,Split Distance [m],Delta Time [s],Cumulative Time [s],Split Velocity [m/s]\n")
    
    # Data rows
    split_idx = 0
    for i, (t, d_raw, d_filt, v, a) in enumerate(samples):
        # Time series columns
        row = [f"{t:.3f}", f"{d_raw:.4f}", "", f"{d_filt:.4f}", f"{v:.6f}", f"{a:.6f}", ""]
        
        # Device splits (only first few rows)
        if split_idx < len(device_splits) and i < 50:  # Only first ~50 rows have splits
            split_d, split_dt, split_cum_t, split_v = device_splits[split_idx]
            row.extend([f"{split_d:.2f}", f"{split_dt:.3f}", f"{split_cum_t:.3f}", f"{split_v:.6f}"])
            split_idx += 1
        else:
            row.extend(["", "", "", ""])
        
        f.write(",".join(row) + "\n")

print(f"Sample CSV created at {output_path}")
