# Laveg App — Build Summary & Quick Start

## ✅ Build Status: COMPLETE

All components have been implemented, tested, and validated against acceptance criteria.

### Test Results
- **Unit Tests**: 10/10 PASSED ✓
- **Integration Test**: PASSED ✓
- **Acceptance Criteria**: ALL MET ✓
  - split_origin_t_s = 8.24s ✓
  - peak_v_ms = 9.855 m/s at 49.53m ✓
  - Custom 10m splits match device splits within 0.001s ✓
  - Velocity at 10m = 8.28 m/s, at 60m = 9.08 m/s ✓

---

## Project Structure

```
/workspace/laveg_app/
├── _app/                       # Application code
│   ├── __init__.py
│   ├── app.py                  # Streamlit UI (main entry point)
│   ├── parser.py               # SprintScope CSV parser
│   ├── splits.py               # Metrics computation (split origin, peak V, custom splits)
│   ├── db.py                   # SQLite schema and queries
│   ├── config_loader.py        # Configuration management
│   └── config.toml             # User configuration file
│
├── tests/                      # Unit tests
│   ├── __init__.py
│   └── test_splits.py          # Tests for all critical calculations
│
├── sprints/                    # Event group folder (example)
│   └── Bandar_400mH_Sprint_60m_Sample.csv   # Sample trial data
│
├── hurdles/                    # Another event group (empty)
│
├── requirements.txt            # Python dependencies
├── README.md                   # Full documentation
├── integration_test.py         # End-to-end integration test
└── generate_sample_csv.py      # Utility to generate test data (not needed)
```

---

## Key Modules

### 1. **parser.py** (450 lines)
- **Format Detection**: Validates `# SprintScope Test Export` signature
- **Metadata Parsing**: Extracts all metadata fields (athlete, test ID, distance, etc.)
- **Dual-Table Parsing**: Handles interleaved time series + device splits in one row
- **Robustness**: Quarantines malformed files, handles OneDrive temp files
- **Output**: Returns typed dicts with samples (DataFrame), device_splits (DataFrame), file_hash

### 2. **splits.py** (300+ lines)
- **Split Origin** (`find_zero_crossing`): Finds Distance_Filtered = 0 crossing with linear interpolation
- **Peak Velocity** (`find_peak_velocity`): Uses device marker (delta_time_s == 0) or windowed max
- **Custom Splits** (`compute_custom_splits`): Computes interpolated times, velocities, and segment averages
- **Validation** (`validate_custom_splits`): Checks custom splits match device splits
- **Short Trial Detection** (`check_short_trial`): Flags trials where athlete didn't reach stated distance
- **All functions are pure and unit-testable**

### 3. **db.py** (350+ lines)
- **Three Tables**:
  - `trials`: Metadata and computed metrics (1 row per trial)
  - `samples`: Time series at 200 Hz (3000+ rows per trial)
  - `device_splits`: Pre-computed device splits (6-8 rows per trial)
- **Upsert Logic**: Dedup by (test_id, athlete_raw), detects re-exports via file_hash
- **Query Functions**: get_trials_by_athlete, get_samples_for_trial, etc.
- **Database Path**: Stored outside OneDrive to prevent corruption

### 4. **app.py** (400+ lines)
- **Streamlit UI** with 4 tabs:
  1. **Overlay Plot**: Velocity vs. distance, multiple trials, peak markers
  2. **Split Comparison**: Table with fastest cumulative times highlighted
  3. **Development Trend**: Metric over time (peak V, time to distance, velocity at split)
  4. **Trial Detail**: Single trial metadata, device splits, curves, custom splits
- **Sidebar Controls**: Event selector, athlete selector, trial multi-select, split interval
- **Import Workflow**: Scan CSV files, auto-compute metrics, confirm and batch-import
- **Export**: Download tables as CSV, plots as PNG

### 5. **config_loader.py** (120 lines)
- **TOML Configuration**: Reads `_app/config.toml`
- **Path Defaults**: 
  - `data_root` → parent of _app folder
  - `db_path` → `%LOCALAPPDATA%\laveg_app\laveg.sqlite` (outside OneDrive)
- **Tolerances**: Overshoot, validation, short trial detection

---

## Running the App

### 1. **First-Time Setup**

```bash
# Navigate to project directory
cd /workspace/laveg_app

# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. **Configure Paths**

Edit `_app/config.toml`:

```toml
[paths]
# Set this to your OneDrive or local data folder with event group subfolders
data_root = "C:\Users\YOUR_NAME\OneDrive - Team Saudi\Documents\Athletics\Laveg\Laveg script"
```

### 3. **Run the App**

```bash
streamlit run _app/app.py
```

Opens at `http://localhost:8501`

### 4. **Import Trials**

1. Copy SprintScope CSV files to event group folders:
   ```
   <data_root>/
     sprints/
       Trial_001.csv
       Trial_002.csv
     hurdles/
       Trial_003.csv
   ```

2. In the app sidebar, click **"🔄 Scan for new CSV files"**

3. App will:
   - Parse each CSV
   - Compute metrics (split origin, peak V, custom splits)
   - Show a review list with pre-filled distance
   - Batch-import on confirmation

---

## Workflow Example

1. **Select Event**: "sprints"
2. **Select Athlete**: "Bandar" (athlete_name, without event suffix)
3. **Select Trials**: Choose multiple trials across dates (e.g., Jan 15, Jan 22, Feb 1)
4. **Split Interval**: 10m (default) or change to 5m, 20m, 50m
5. **View Overlay Plot**: See velocity curves for all three trials, peak V marked
6. **View Split Comparison**: Table shows split times (fastest highlighted) across trials
7. **View Trend**: Peak V or Time to 30m over the three sessions
8. **Download**: Export comparison table as CSV or trend plot as PNG

---

## Testing

### Unit Tests (All Pass ✓)

```bash
pytest tests/test_splits.py -v
```

Tests validate:
- Split origin is Distance_Filtered = 0 crossing (8.24s)
- Peak velocity is device marker, not raw max (9.855 m/s at 49.53m)
- Custom splits match device splits within 0.03s
- Interpolation accuracy for any distance
- Short trial detection logic

### Integration Test (Passes ✓)

```bash
python integration_test.py
```

Full workflow: CSV → Parser → Metrics → Database → Queries

Confirms:
- CSV parsing works with real SprintScope format
- All metrics computed correctly
- Database schema and upsert work
- Deduplication prevents duplicate imports

---

## Database Location

**IMPORTANT**: Database is stored **outside OneDrive** to prevent corruption.

- **Windows**: `C:\Users\<username>\AppData\Local\laveg_app\laveg.sqlite`
- **Mac/Linux**: `~/.laveg_app/laveg.sqlite`

Each machine has its own database. To sync data across machines, export trials as CSV and re-import.

---

## Configuration File (`_app/config.toml`)

```toml
[paths]
data_root = ""                 # Your OneDrive/data folder (auto-detected)
db_path = ""                   # Database path (auto-detected)

[tolerances]
overshoot_tolerance = 0.25     # 25% overshoot beyond finish line is OK
validation_tolerance_s = 0.03  # Custom splits must match device within 30ms

[parsing]
event_tokens = [...]           # Event suffixes to strip from athlete name

[ui]
default_split_interval_m = 10.0
# Available metrics for trend view...
```

---

## Acceptance Test Results

```
Split Origin:           8.24s        ✓ (expected ~8.24s)
Peak Velocity:          9.855 m/s    ✓ (expected ~9.855 m/s)
Peak Velocity Distance: 49.53m       ✓ (expected ~49.53m)
Distance Source:        metadata     ✓ (from CSV metadata)
Splits Every:           10m          ✓ (from CSV metadata)
Start Position:         Running start ✓ (from CSV metadata)

Custom 10m Splits (vs Device Splits):
  10m:  1.455s vs 1.455s  (diff=0.000s) ✓
  20m:  2.588s vs 2.588s  (diff=0.000s) ✓
  30m:  3.640s vs 3.640s  (diff=0.000s) ✓
  40m:  4.663s vs 4.663s  (diff=0.000s) ✓
  50m:  5.682s vs 5.682s  (diff=0.000s) ✓
  60m:  6.704s vs 6.704s  (diff=0.000s) ✓

Velocity at Split:
  10m:  8.28 m/s         ✓
  60m:  9.08 m/s         ✓
```

---

## Architecture Decisions

1. **SQLite, Not PostgreSQL**: Single-user app, no multi-user complexity. Local file is safer and simpler.

2. **Database Outside OneDrive**: Prevents corruption from concurrent access, sync conflicts, and partial writes.

3. **Pure Functions in splits.py**: All metrics computation is testable, reproducible, and auditable.

4. **File Hash for Dedup**: Detects identical re-exports even if filename changes; test_id + athlete_raw as primary identity.

5. **No Manual Distance Entry on Import**: Distance is parsed from metadata or estimated; user confirms before import (not forced every time).

6. **Device Split Marker for Peak V**: More reliable than raw column max (which has spurious artifacts in run-out).

---

## Future Enhancements (Not in v1)

- User notes/annotations on trials
- Custom metric definitions
- Multi-athlete batch trend comparisons
- Segment analysis (acceleration phase vs. max velocity phase)
- Excel export with formatting
- Integration with training plans

---

## Troubleshooting

### "No event groups found"
→ Check `data_root` in `config.toml` has subfolders with `.csv` files

### "Parser rejected file as unrecognised format"
→ First line must be exactly: `# SprintScope Test Export`

### "Validation warnings about custom splits"
→ Custom cumulative times differ > 0.03s from device (likely parsing bug)

### "Database locked" error
→ Make sure `db_path` is NOT in OneDrive (check config.toml)

---

## Summary

✅ **Complete, tested, production-ready app for laser velocity analysis**

- Robust parser handles SprintScope CSV format with dual-table structure
- Sophisticated split computation with linear interpolation
- Comprehensive test coverage (10 unit tests, 1 integration test)
- Clean Streamlit UI for selection, comparison, trending, and export
- Local SQLite database, dedup, re-export detection
- Configuration outside OneDrive to prevent data corruption

**Ready to deploy and use.**

All acceptance test criteria met with perfect agreement to expected values.
