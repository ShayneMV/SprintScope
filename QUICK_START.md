# Quick Start Guide

## 30-Second Setup

1. **Update config.toml** with your data path:
   ```bash
   cd /workspace/laveg_app/_app
   # Edit config.toml: set data_root to your OneDrive path
   ```

2. **Install and run**:
   ```bash
   cd /workspace/laveg_app
   pip install -r requirements.txt
   streamlit run _app/app.py
   ```

3. **Import trials**:
   - Browser opens at http://localhost:8501
   - Click "🔄 Scan for new CSV files" in sidebar
   - Select trials and compare

## Expected Folder Structure

Your data folder must look like this:

```
C:\Users\s.vial\OneDrive - Team Saudi\Documents\Athletics\Laveg\Laveg script\
├── sprints\
│   ├── Trial_001.csv
│   ├── Trial_002.csv
│   └── ...
├── hurdles\
│   ├── Trial_003.csv
│   └── ...
├── _app\                    ← App code lives here
│   ├── app.py
│   ├── parser.py
│   ├── splits.py
│   ├── db.py
│   ├── config_loader.py
│   └── config.toml
├── tests\
├── requirements.txt
├── README.md
└── ...
```

## Configuration

Edit `_app/config.toml`:

```toml
[paths]
# Point this to your data root (parent of event group folders)
data_root = "C:\Users\s.vial\OneDrive - Team Saudi\Documents\Athletics\Laveg\Laveg script"

# Database path (optional, auto-set to %LOCALAPPDATA%\laveg_app\laveg.sqlite)
# db_path = "C:\Users\s.vial\AppData\Local\laveg_app\laveg.sqlite"
```

## Run Tests

```bash
# Unit tests (splits logic)
pytest tests/test_splits.py -v

# Integration test (full workflow)
python integration_test.py
```

Both should show ✓ PASSED.

## Troubleshooting

**"Module not found: _app"**
→ Make sure you're running from `/workspace/laveg_app` directory

**"Database locked"**
→ Close any other instances of the app
→ Check db_path is NOT in a synced folder (OneDrive, Google Drive, etc.)

**"No trials imported"**
→ Check CSV files are in event group subfolders (sprints/, hurdles/, etc.)
→ First line of CSV must be `# SprintScope Test Export`

## What Each File Does

- `app.py` — Streamlit UI (4 tabs, sidebar controls)
- `parser.py` — Reads SprintScope CSV files
- `splits.py` — Computes split origin, peak velocity, custom splits
- `db.py` — SQLite schema and queries
- `config_loader.py` — Reads config.toml, sets defaults
- `config.toml` — Your configuration (edit this!)
- `tests/test_splits.py` — Unit tests (10 tests, all passing)

## Next Steps

1. Run `streamlit run _app/app.py`
2. Scan for CSV files
3. Select athlete and trials
4. Explore the 4 tabs
5. Download results as CSV or PNG

Enjoy! 🏃‍♂️
