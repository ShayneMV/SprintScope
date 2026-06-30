# Laveg — Laser Velocity Session Database & Review

A local, single-user desktop application for analyzing laser velocity trials from SprintScope exports. Ingest CSV data, store in SQLite, and compare athlete performance across sessions and events.

## Features

- **Format Detection**: Automatically detects and quarantines SprintScope Test Export CSV files
- **Robust Parsing**: Handles the dual-table format (time series + device splits in one row)
- **Derived Metrics**: Computes split origin, peak velocity, and custom splits at any interval
- **Session Grouping**: Group trials by date and athlete to track development over time
- **Interactive UI**: 
  - Overlay velocity profiles to compare trials
  - Split comparison tables with fastest times highlighted
  - Development trend plots for long-term tracking
  - Trial detail view with full metadata and device split logs
- **Export**: Download tables as CSV and plots as PNG
- **Deduplication**: Re-importing the same CSV is safe (detected by file hash and Test ID)

## Requirements

- **Python 3.11+**
- **Windows, macOS, or Linux**

## Installation

1. **Clone or download this project**:
   ```bash
   cd laveg_app
   ```

2. **Create a virtual environment** (recommended):
   ```bash
   python -m venv venv
   source venv/bin/activate    # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

Before running the app, configure the data paths in `_app/config.toml`:

```toml
[paths]
# Set this to your OneDrive or local data folder containing event group subfolders
data_root = "C:\\Users\\YourName\\OneDrive - Team Saudi\\Documents\\Athletics\\Laveg\\Laveg script"

# Database path (automatically created if it doesn't exist)
# Default: %LOCALAPPDATA%\laveg_app\laveg.sqlite (outside OneDrive)
db_path = ""
```

### Folder Structure

Your data root must have this structure:

```
<DATA_ROOT>/
  sprints/        (event group folder)
    Trial_001.csv
    Trial_002.csv
  hurdles/        (event group folder)
    Trial_003.csv
  ...
```

The app treats each subfolder as an "event group" and stores the file location in the database.

## Running the App

```bash
streamlit run _app/app.py
```

The app will open in your browser at `http://localhost:8501`.

## First Steps

1. **Update config.toml** with your data root path
2. **Click "🔄 Scan for new CSV files"** to import all SprintScope exports
3. **Select an athlete** from the sidebar
4. **Pick one or more trials** to compare
5. **Explore the tabs**:
   - **Overlay Plot**: See all velocity curves overlaid; peak V is marked with a star
   - **Split Comparison**: View split times and velocities at 5m, 10m, 20m, or 50m intervals
   - **Development Trend**: Track a metric (e.g., peak V, cumulative time) over weeks/months
   - **Trial Detail**: Metadata, device splits, and custom splits for a single trial

## CSV Format: SprintScope Test Export

The app only reads SprintScope Test Export CSV files. A valid file has:

1. **First line**: `# SprintScope Test Export`
2. **Metadata lines**: `# Key:,Value` (e.g., `# Athlete:,Bandar 400mH`)
3. **Header line**: Exactly as specified (includes empty columns as spacers)
4. **Data rows**: Time series (200 Hz) + device splits (interleaved in the same rows)

Example metadata keys (all optional):
- `Athlete`, `Test ID`, `Test Type`, `Date` (ISO 8601)
- `Distance` (e.g., "60 m"), `Splits Every` (e.g., "10 m")
- `Session Type`, `Venue`, `Weather`, `Wind`, `Surface`, `Footwear`
- `Start Position`, `Filter`, `Filter Params`

## Database Schema

The app stores data in a local SQLite file with three tables:

### `trials`
Main trial metadata and computed metrics (peak velocity, split origin, distance, athlete name, etc.)

### `samples`
Time series data at 200 Hz (time, filtered distance, velocity, acceleration).

### `device_splits`
Pre-computed splits from the device (split distance, delta time, velocity at split).

## Derived Metrics (The Math)

### Split Origin (`split_origin_t_s`)
The time when the laser gate activated, detected as the first upward crossing of `Distance_Filtered = 0` with linear interpolation. All custom splits are measured from this origin, not from t=0.

### Peak Velocity (`peak_v_ms`)
Taken from the device split marker (row where `Delta Time [s] == 0`), NOT from the raw velocity column (which has spurious high values in the run-out). If no marker exists, computed as the max velocity in the valid window (split origin ≤ t ≤ distance_m).

### Custom Splits
For each split distance `d = S, 2S, 3S, ...` (where S = split interval):
- **Cumulative time**: time from split origin to distance d (interpolated)
- **Split time**: time taken for that segment (cumulative - previous cumulative)
- **Velocity at split**: instantaneous velocity at distance d (interpolated)
- **Segment average velocity**: S / split_time (labeled clearly to avoid confusion with instantaneous)

## Validation & Flags

- **Short trial flag** (`flag_short_trial`): Set if filtered distance undershoots stated distance (athlete didn't reach the finish line). Run-out beyond the gate is normal; undershooting indicates a bad or incomplete trial.
- **Validation warnings**: If custom splits diverge from device splits by > 0.03 s, logged at import time (indicates a parsing issue).

## Exporting Results

Each table has a "📥 Download CSV" button. Each chart has a "📸 Download PNG" button.

## Troubleshooting

### "No event groups found"
- Make sure `data_root` in `config.toml` points to a folder containing subfolders
- Subfolders must contain `.csv` files

### "Parser rejected file as unrecognised format"
- Check that the first line of your CSV is exactly: `# SprintScope Test Export`
- Ensure the file is not a OneDrive temp file (names like `~$...` or `.tmp` are skipped)

### "Custom splits don't match device splits"
- Validation warnings are logged if cumulative times differ by > 0.03 s
- This usually indicates a parsing bug; please report with the CSV file

### Database locked error
- Make sure the `db_path` in `config.toml` points to a folder that is NOT synced to OneDrive
- Default location (`%LOCALAPPDATA%\laveg_app\`) is safe

## Design Principles

1. **Correctness first**: All formulas are tested against real sample data with known ground truth
2. **No manual input on import**: Distance, athlete name, and other fields are parsed or estimated automatically
3. **Audit trail**: Original metadata is preserved (`distance_meta_m`, `athlete_raw`) even after user edits
4. **Offline-first**: All data stored locally in SQLite; no cloud dependencies
5. **Read-only source**: CSV files in OneDrive are read-only; database lives outside OneDrive to prevent corruption

## Unit Tests

To run tests:

```bash
pytest tests/ -v
```

Tests validate:
- Split origin is the Distance_Filtered = 0 crossing
- Peak velocity is the device marker value, not raw column max
- Custom splits at native interval match device splits within tolerance
- Interpolation accuracy

## Future Enhancements (v2+)

- [ ] Athlete-specific note annotations on trials
- [ ] Custom metric definitions (e.g., "time to 40m for 400m specialist")
- [ ] Batch processing for trends across multiple athletes
- [ ] Segment analysis (e.g., acceleration vs. max velocity phase)
- [ ] Export to Excel with formatting
- [ ] Workout plan integration (predicted splits for upcoming sessions)

## Support

If you encounter issues:
1. Check `config.toml` is correctly configured
2. Review test output: `pytest tests/ -v`
3. Check Streamlit logs in the terminal

## License

Internal use only. Not for distribution.
