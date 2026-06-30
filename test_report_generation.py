"""
test_report_generation.py: Quick validation that report generation works.
"""

import sys
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path(__file__).parent / "_app"))
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd

from _app.config_loader import load_config
from _app.db import TrialsDB
from _app.report import generate_report_html, generate_filename


def test_report_generation():
    """Test report HTML generation with sample data."""
    
    print("\n" + "="*70)
    print("TEST: Report Generation with Sample Data")
    print("="*70)
    
    # Initialize
    config = load_config()
    db = TrialsDB(str(config.db_path))
    
    # Get trials from database
    all_trials = db.get_all_trials()
    
    if all_trials.empty:
        print("\n✗ No trials in database. Import sample CSV first.")
        return False
    
    print(f"\n✓ Found {len(all_trials)} trials in database")
    
    # Get first trial (simulating Mode A selection)
    selected_trials = all_trials.head(1)  # Just 1 trial for quick test
    
    print(f"  Testing with trial: {selected_trials.iloc[0]['athlete_name']} - {selected_trials.iloc[0]['session_date']}")
    
    try:
        # Generate report
        report_html = generate_report_html(
            selected_trials,
            db,
            split_interval=10,
            mode="Mode A",
            analyst_notes="Test report with sample data.",
        )
        
        print(f"\n✓ Report HTML generated: {len(report_html)} bytes")
        
        # Check template was filled (not placeholders)
        if "PLACEHOLDER" in report_html:
            print("✗ Report contains placeholder text")
            return False
        
        if "Sprint Session: Performance Analysis" not in report_html:
            print("✗ Report missing header")
            return False
        
        if "Test report with sample data" not in report_html:
            print("✗ Report missing analyst notes")
            return False
        
        print("✓ Header, content, and notes verified")
        
        # Check filename generation
        filename = generate_filename(selected_trials, "Mode A")
        print(f"✓ Generated filename: {filename}")
        
        if not filename.endswith(".pdf"):
            print("✗ Filename doesn't end with .pdf")
            return False
        
        print("\n✓ ALL TESTS PASSED")
        print("  - Report HTML generated successfully")
        print("  - Template filled with real data (no placeholders)")
        print("  - Filename generated correctly")
        
        return True
        
    except Exception as e:
        print(f"\n✗ Error during report generation: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_report_generation()
    sys.exit(0 if success else 1)
