"""
db.py: SQLite database schema and ingestion logic.

Handles:
- Schema creation (trials, samples, device_splits tables)
- Upsert logic (dedup by test_id + athlete_raw, hash check)
- Query functions for the UI
- Connection management
"""

import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Tuple, Any
import pandas as pd
from contextlib import contextmanager


class TrialsDB:
    """SQLite database for laser velocity trials."""
    
    def __init__(self, db_path: str):
        """Initialize database connection."""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.create_schema()
    
    @contextmanager
    def get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def create_schema(self):
        """Create database schema if not exists."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Trials table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trials (
                    trial_id INTEGER PRIMARY KEY,
                    test_id TEXT NOT NULL,
                    file_hash TEXT NOT NULL,
                    source_file TEXT,
                    source_filename TEXT,
                    event_group TEXT,
                    athlete_raw TEXT NOT NULL,
                    athlete_name TEXT,
                    event_token TEXT,
                    test_type TEXT,
                    datetime TEXT,
                    session_date TEXT,
                    distance_m REAL,
                    distance_meta_m REAL,
                    distance_source TEXT,
                    splits_every_m REAL,
                    start_position TEXT,
                    surface TEXT,
                    footwear TEXT,
                    wind TEXT,
                    weather TEXT,
                    venue TEXT,
                    zero_offset REAL,
                    filter TEXT,
                    filter_params TEXT,
                    peak_v_ms REAL,
                    peak_v_distance_m REAL,
                    split_origin_t_s REAL,
                    flag_short_trial INTEGER,
                    notes TEXT,
                    imported_at TEXT,
                    UNIQUE(test_id, athlete_raw)
                )
            """)
            
            # Samples table (time series at 200 Hz)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS samples (
                    trial_id INTEGER NOT NULL,
                    t_s REAL NOT NULL,
                    dist_raw_m REAL,
                    dist_filt_m REAL,
                    vel_ms REAL,
                    accel_ms2 REAL,
                    FOREIGN KEY (trial_id) REFERENCES trials(trial_id) ON DELETE CASCADE
                )
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_samples_trial_time 
                ON samples(trial_id, t_s)
            """)
            
            # Device splits table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS device_splits (
                    trial_id INTEGER NOT NULL,
                    split_distance_m REAL,
                    delta_time_s REAL,
                    cumulative_time_s REAL,
                    split_velocity_ms REAL,
                    is_peak_marker INTEGER,
                    FOREIGN KEY (trial_id) REFERENCES trials(trial_id) ON DELETE CASCADE
                )
            """)
            
            conn.commit()
    
    def upsert_trial(
        self,
        trial_record: Dict[str, Any],
        samples_df: pd.DataFrame,
        device_splits_df: pd.DataFrame,
    ) -> Tuple[int, str]:
        """
        Insert or update a trial record.
        
        Returns (trial_id, action) where action is "inserted" or "updated" or "skipped" (duplicate, same hash).
        
        Raises ValueError if (test_id, athlete_raw) exists with different file_hash (re-export).
        """
        
        test_id = trial_record["test_id"]
        athlete_raw = trial_record["athlete_raw"]
        file_hash = trial_record["file_hash"]
        
        # Fields that are stored in the database
        db_fields = {
            'test_id', 'file_hash', 'source_file', 'source_filename', 'event_group',
            'athlete_raw', 'athlete_name', 'event_token', 'test_type', 'datetime',
            'session_date', 'distance_m', 'distance_meta_m', 'distance_source',
            'splits_every_m', 'start_position', 'surface', 'footwear', 'wind',
            'weather', 'venue', 'zero_offset', 'filter', 'filter_params',
            'peak_v_ms', 'peak_v_distance_m', 'split_origin_t_s', 'flag_short_trial',
            'notes', 'imported_at', 'trial_id',
        }
        
        # Filter trial_record to only include DB fields
        filtered_record = {k: v for k, v in trial_record.items() if k in db_fields}
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Check if trial already exists
            cursor.execute(
                "SELECT trial_id, file_hash FROM trials WHERE test_id = ? AND athlete_raw = ?",
                (test_id, athlete_raw),
            )
            existing = cursor.fetchone()
            
            if existing:
                existing_id, existing_hash = existing
                if existing_hash == file_hash:
                    # Identical file, skip
                    return existing_id, "skipped"
                else:
                    # Re-export: different hash, same trial ID
                    # For now, we'll update the existing record
                    # In future, UI could ask user to replace or ignore
                    action = "re-export"
            else:
                action = "inserted"
                existing_id = None
            
            # Prepare trial record for insertion
            filtered_record["imported_at"] = datetime.utcnow().isoformat()
            
            # Build columns and values
            cols = list(filtered_record.keys())
            vals = [filtered_record[k] for k in cols]
            placeholders = ",".join(["?"] * len(cols))
            
            if action == "inserted":
                query = f"INSERT INTO trials ({','.join(cols)}) VALUES ({placeholders})"
                cursor.execute(query, vals)
                trial_id = cursor.lastrowid
            else:
                # Update existing record
                trial_id = existing_id
                # Only update non-PK fields
                set_clause = ",".join([f"{col}=?" for col in cols if col != "trial_id"])
                update_vals = [filtered_record[k] for k in cols if k != "trial_id"]
                query = f"UPDATE trials SET {set_clause} WHERE trial_id=?"
                cursor.execute(query, update_vals + [trial_id])
            
            # Insert samples
            if not samples_df.empty:
                samples_df["trial_id"] = trial_id
                # Delete existing samples for this trial (if re-export)
                cursor.execute("DELETE FROM samples WHERE trial_id = ?", (trial_id,))
                
                for _, row in samples_df.iterrows():
                    cursor.execute("""
                        INSERT INTO samples (trial_id, t_s, dist_raw_m, dist_filt_m, vel_ms, accel_ms2)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        trial_id,
                        row["t_s"],
                        row["dist_raw_m"],
                        row["dist_filt_m"],
                        row["vel_ms"],
                        row["accel_ms2"],
                    ))
            
            # Insert device splits
            if not device_splits_df.empty:
                device_splits_df["trial_id"] = trial_id
                # Delete existing device splits for this trial
                cursor.execute("DELETE FROM device_splits WHERE trial_id = ?", (trial_id,))
                
                for _, row in device_splits_df.iterrows():
                    cursor.execute("""
                        INSERT INTO device_splits 
                        (trial_id, split_distance_m, delta_time_s, cumulative_time_s, split_velocity_ms, is_peak_marker)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        trial_id,
                        row.get("split_distance_m"),
                        row.get("delta_time_s"),
                        row.get("cumulative_time_s"),
                        row.get("split_velocity_ms"),
                        row.get("is_peak_marker", 0),
                    ))
            
            conn.commit()
            return trial_id, action
    
    # Query functions for the UI
    
    def get_all_trials(self) -> pd.DataFrame:
        """Get all trials as DataFrame."""
        with self.get_connection() as conn:
            return pd.read_sql_query("SELECT * FROM trials", conn)
    
    def get_trial_by_id(self, trial_id: int) -> Optional[Dict[str, Any]]:
        """Get a single trial by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM trials WHERE trial_id = ?", (trial_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
        return None
    
    def get_event_groups(self) -> List[str]:
        """Get unique event groups."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT event_group FROM trials ORDER BY event_group")
            return [row[0] for row in cursor.fetchall() if row[0]]
    
    def get_athletes_by_event(self, event_group: str) -> List[str]:
        """Get unique athlete names for a given event group."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT athlete_name FROM trials WHERE event_group = ? ORDER BY athlete_name",
                (event_group,)
            )
            return [row[0] for row in cursor.fetchall() if row[0]]
    
    def get_trials_by_athlete(self, athlete_name: str, event_group: Optional[str] = None) -> pd.DataFrame:
        """Get all trials for an athlete, optionally filtered by event group."""
        with self.get_connection() as conn:
            if event_group:
                query = "SELECT * FROM trials WHERE athlete_name = ? AND event_group = ? ORDER BY session_date DESC"
                return pd.read_sql_query(query, conn, params=(athlete_name, event_group))
            else:
                query = "SELECT * FROM trials WHERE athlete_name = ? ORDER BY session_date DESC"
                return pd.read_sql_query(query, conn, params=(athlete_name,))
    
    def get_samples_for_trial(self, trial_id: int) -> pd.DataFrame:
        """Get time series samples for a trial."""
        with self.get_connection() as conn:
            query = "SELECT t_s, dist_raw_m, dist_filt_m, vel_ms, accel_ms2 FROM samples WHERE trial_id = ? ORDER BY t_s"
            return pd.read_sql_query(query, conn, params=(trial_id,))
    
    def get_device_splits_for_trial(self, trial_id: int) -> pd.DataFrame:
        """Get device splits for a trial."""
        with self.get_connection() as conn:
            query = "SELECT split_distance_m, delta_time_s, cumulative_time_s, split_velocity_ms, is_peak_marker FROM device_splits WHERE trial_id = ? ORDER BY split_distance_m"
            return pd.read_sql_query(query, conn, params=(trial_id,))
    
    def get_trials_by_ids(self, trial_ids: List[int]) -> pd.DataFrame:
        """Get multiple trials by list of IDs."""
        if not trial_ids:
            return pd.DataFrame()
        
        with self.get_connection() as conn:
            placeholders = ",".join("?" * len(trial_ids))
            query = f"SELECT * FROM trials WHERE trial_id IN ({placeholders}) ORDER BY session_date, test_id"
            return pd.read_sql_query(query, conn, params=trial_ids)
    
    def get_flagged_trials(self) -> pd.DataFrame:
        """Get all short/flagged trials."""
        with self.get_connection() as conn:
            query = "SELECT * FROM trials WHERE flag_short_trial = 1 ORDER BY session_date DESC"
            return pd.read_sql_query(query, conn)
    
    def get_trials_by_date_range(self, athlete_name: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Get trials within a date range."""
        with self.get_connection() as conn:
            query = """
                SELECT * FROM trials 
                WHERE athlete_name = ? AND session_date >= ? AND session_date <= ?
                ORDER BY session_date
            """
            return pd.read_sql_query(query, conn, params=(athlete_name, start_date, end_date))
