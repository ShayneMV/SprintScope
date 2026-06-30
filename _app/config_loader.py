"""
config.py: Configuration loader and validation.

Handles:
- Reading config.toml
- Setting defaults for paths (DATA_ROOT, DB_PATH)
- Validating paths exist
- Providing configuration to app and parser
"""

import os
import tomllib
from pathlib import Path
from typing import Dict, Any, Optional, List


def get_default_db_path() -> Path:
    """
    Get default database path (outside any cloud sync).
    
    On Windows: %LOCALAPPDATA%\\laveg_app\\laveg.sqlite
    On Unix: ~/.laveg_app/laveg.sqlite
    """
    if os.name == "nt":
        # Windows
        localappdata = os.environ.get("LOCALAPPDATA")
        if localappdata:
            db_dir = Path(localappdata) / "laveg_app"
        else:
            db_dir = Path.home() / ".laveg_app"
    else:
        # Unix
        db_dir = Path.home() / ".laveg_app"
    
    return db_dir / "laveg.sqlite"


def get_default_data_root() -> Optional[Path]:
    """
    Get default data root (parent of _app folder).
    
    Assumes the app structure:
    <DATA_ROOT>/_app/app.py
    
    Returns None if we can't determine it.
    """
    app_py = Path(__file__).parent / "app.py"
    if app_py.exists():
        return app_py.parent.parent
    return None


class Config:
    """Configuration object."""
    
    def __init__(self, config_dict: Dict[str, Any]):
        self.raw = config_dict
        
        # Paths
        self.data_root = Path(config_dict.get("paths", {}).get("data_root") or get_default_data_root() or ".")
        self.db_path = Path(config_dict.get("paths", {}).get("db_path") or get_default_db_path())
        
        # Tolerances
        self.overshoot_tolerance = config_dict.get("tolerances", {}).get("overshoot_tolerance", 0.25)
        self.validation_tolerance_s = config_dict.get("tolerances", {}).get("validation_tolerance_s", 0.03)
        
        # Parsing
        self.event_tokens = config_dict.get("parsing", {}).get("event_tokens", [
            "100m", "200m", "400m", "800m", "1500m", "60m",
            "110mH", "400mH", "100mH", "300mH",
            "LJ", "TJ", "PV", "SP", "HJ", "DT", "HT", "JT", "WT"
        ])
        
        # UI
        self.default_split_interval_m = config_dict.get("ui", {}).get("default_split_interval_m", 10.0)
        self.available_metrics = config_dict.get("ui", {}).get("available_metrics", {
            "peak_v_ms": "Peak Velocity (m/s)",
            "cumulative_time_10m": "Time to 10m (s)",
            "cumulative_time_30m": "Time to 30m (s)",
            "cumulative_time_50m": "Time to 50m (s)",
            "cumulative_time_60m": "Time to 60m (s)",
            "velocity_at_10m": "Velocity at 10m (m/s)",
            "velocity_at_50m": "Velocity at 50m (m/s)",
            "velocity_at_60m": "Velocity at 60m (m/s)",
        })
    
    def validate(self) -> List[str]:
        """
        Validate configuration.
        
        Returns list of warning/error messages.
        """
        warnings = []
        
        if not self.data_root.exists():
            warnings.append(f"Data root not found: {self.data_root}")
        
        if not self.db_path.parent.exists():
            warnings.append(f"DB parent directory not found: {self.db_path.parent} (will be created)")
        
        return warnings


def load_config(config_path: Optional[Path] = None) -> Config:
    """
    Load configuration from config.toml.
    
    Args:
        config_path: Path to config.toml. If None, looks in _app/config.toml.
    
    Returns:
        Config object with defaults applied.
    """
    if config_path is None:
        config_path = Path(__file__).parent / "config.toml"
    
    config_dict = {}
    
    if config_path.exists():
        with open(config_path, "rb") as f:
            config_dict = tomllib.load(f)
    
    return Config(config_dict)


def save_config(config: Config, config_path: Optional[Path] = None) -> None:
    """
    Save configuration to config.toml (for future use when UI updates config).
    
    Args:
        config: Config object to save.
        config_path: Path to save to. If None, uses _app/config.toml.
    """
    if config_path is None:
        config_path = Path(__file__).parent / "config.toml"
    
    # For now, just preserve the dict
    # In future, could update specific values and write back
    pass
