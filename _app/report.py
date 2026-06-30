"""
report.py: Generate Team Saudi sprint session reports from comparison modes.

Fills the team_saudi_report_template.html with real data from Mode A or Mode B.
Generates static velocity plots, split matrices, metadata strips, and analyst notes.
Outputs HTML and PDF (via weasyprint or print-to-PDF fallback).
"""

import pandas as pd
import numpy as np
import base64
from io import BytesIO
from datetime import datetime
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from pathlib import Path

try:
    from .splits import find_t_reach, get_valid_window_mask
    from .comparison import build_split_matrix_mode_a, build_split_matrix_mode_b
except ImportError:
    from splits import find_t_reach, get_valid_window_mask
    from comparison import build_split_matrix_mode_a, build_split_matrix_mode_b


def generate_velocity_plot_image(
    trials_df: pd.DataFrame,
    db,
    mode: str,
) -> str:
    """
    Generate a static velocity-vs-distance plot using matplotlib.
    
    Args:
        trials_df: Selected trials
        db: Database connection
        mode: "Mode A" or "Mode B"
    
    Returns:
        Base64-encoded PNG image data (data:image/png;base64,...)
    """
    fig, ax = plt.subplots(figsize=(9, 5.5))
    
    colors = plt.cm.tab10(np.linspace(0, 1, len(trials_df)))
    
    for idx, (_, trial) in enumerate(trials_df.iterrows()):
        trial_id = trial["trial_id"]
        samples = db.get_samples_for_trial(trial_id)
        
        if samples.empty:
            continue
        
        # Apply valid window
        distance_m = trial["distance_m"]
        split_origin_t_s = trial["split_origin_t_s"]
        t_reach = find_t_reach(samples, distance_m)
        valid_mask = get_valid_window_mask(samples, split_origin_t_s, t_reach)
        samples_valid = samples[valid_mask]
        
        # Legend label
        if "Mode A" in mode:
            label = trial["session_date"] or "No date"
        else:  # Mode B
            label = trial["athlete_name"]
        
        # Line style (dashed if short trial)
        linestyle = "--" if trial["flag_short_trial"] == 1 else "-"
        linewidth = 1.5 if trial["flag_short_trial"] == 0 else 1.2
        
        # Plot line
        ax.plot(
            samples_valid["dist_filt_m"],
            samples_valid["vel_ms"],
            label=label,
            color=colors[idx],
            linewidth=linewidth,
            linestyle=linestyle,
        )
        
        # Mark peak velocity
        if trial["peak_v_ms"] and trial["peak_v_distance_m"]:
            ax.plot(
                trial["peak_v_distance_m"],
                trial["peak_v_ms"],
                marker="*",
                markersize=12,
                color=colors[idx],
                markeredgecolor="white",
                markeredgewidth=0.5,
            )
    
    ax.set_xlabel("Filtered Distance (m)", fontsize=11, fontweight="bold")
    ax.set_ylabel("Velocity (m/s)", fontsize=11, fontweight="bold")
    ax.set_xlim(0, trials_df["distance_m"].iloc[0] if len(trials_df) > 0 else 60)
    ax.set_ylim(bottom=0)
    ax.grid(True, alpha=0.2, linestyle=":", linewidth=0.5)
    ax.legend(loc="lower right", fontsize=10, framealpha=0.95)
    
    # Apply Team Saudi colors
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#6b7280")
    ax.spines["bottom"].set_color("#6b7280")
    
    plt.tight_layout()
    
    # Convert to base64
    buffer = BytesIO()
    plt.savefig(buffer, format="png", dpi=100, bbox_inches="tight")
    plt.close()
    buffer.seek(0)
    img_base64 = base64.b64encode(buffer.read()).decode("utf-8")
    
    return f"data:image/png;base64,{img_base64}"


def format_value(value, decimals: int = 3) -> str:
    """Format numeric value or return hyphen if None."""
    if value is None or pd.isna(value):
        return "-"
    return f"{value:.{decimals}f}"


def build_split_matrices_html(
    trials_df: pd.DataFrame,
    db,
    split_interval: float,
    mode: str,
) -> tuple[str, str]:
    """
    Build HTML tables for cumulative split times and velocity at split.
    
    Returns: (cumulative_time_html, velocity_html)
    """
    if "Mode A" in mode:
        cum_matrix, vel_matrix = build_split_matrix_mode_a(
            trials_df.sort_values("session_date"),
            db,
            split_interval,
        )
        # Columns are dates
        column_labels = cum_matrix.columns.tolist() if not cum_matrix.empty else []
        is_dates = True
    else:  # Mode B
        cum_matrix, vel_matrix, _ = build_split_matrix_mode_b(
            trials_df,
            db,
            split_interval,
        )
        # Columns are athlete names
        column_labels = cum_matrix.columns.tolist() if not cum_matrix.empty else []
        is_dates = False
    
    # Helper to build table HTML
    def matrix_to_html(matrix_df, is_time: bool = True) -> str:
        if matrix_df.empty:
            return "<p>No data available.</p>"
        
        decimals = 3 if is_time else 2
        
        # Build best-per-row set
        best_per_row = {}
        if is_time:
            for row_idx, dist in enumerate(matrix_df.index):
                best_per_row[dist] = matrix_df.loc[dist].min()
        else:
            for row_idx, dist in enumerate(matrix_df.index):
                best_per_row[dist] = matrix_df.loc[dist].max()
        
        html = '<table>\n  <thead>\n    <tr>\n      <th>Distance [m]</th>\n'
        
        for col in column_labels:
            if is_dates:
                col_display = col.strftime("%d %b") if isinstance(col, pd.Timestamp) else str(col)
            else:
                col_display = str(col)
            html += f"      <th>{col_display}</th>\n"
        
        html += "    </tr>\n  </thead>\n  <tbody>\n"
        
        for dist in matrix_df.index:
            html += f"    <tr><td>{dist:.0f}</td>"
            for col in column_labels:
                val = matrix_df.loc[dist, col]
                formatted = format_value(val, decimals)
                
                # Check if this is the best value
                is_best = False
                if is_time and not pd.isna(val) and abs(val - best_per_row[dist]) < 0.001:
                    is_best = True
                elif not is_time and not pd.isna(val) and abs(val - best_per_row[dist]) < 0.01:
                    is_best = True
                
                if is_best:
                    html += f'<td class="best">{formatted}</td>'
                else:
                    html += f'<td>{formatted}</td>'
            
            html += "</tr>\n"
        
        html += "  </tbody>\n</table>\n"
        return html
    
    cum_html = matrix_to_html(cum_matrix, is_time=True)
    vel_html = matrix_to_html(vel_matrix, is_time=False)
    
    return cum_html, vel_html


def format_metadata_strip(trials_df: pd.DataFrame, mode: str) -> str:
    """Build metadata strip HTML from trial metadata."""
    # Use first trial for most metadata (all should match due to comparability guard)
    trial = trials_df.iloc[0]
    
    # Athlete or cohort name
    if "Mode A" in mode:
        athlete_display = trial["athlete_name"]
    else:  # Mode B
        athletes = trials_df["athlete_name"].unique().tolist()
        athlete_display = " vs ".join(athletes)
    
    distance = f"{trial['distance_m']:.0f} m" if trial["distance_m"] else "-"
    start_pos = trial["start_position"] or "-"
    surface = trial.get("surface", "-") or "-"
    footwear = trial.get("footwear", "-") or "-"
    wind = trial.get("wind", "-") or "-"
    operator = trial.get("operator", "-") or "-"
    
    html = f'''  <div class="meta-strip">
    <div class="meta-item"><div class="label">Athlete</div><div class="value">{athlete_display}</div></div>
    <div class="meta-item"><div class="label">Distance</div><div class="value">{distance}</div></div>
    <div class="meta-item"><div class="label">Start</div><div class="value">{start_pos}</div></div>
    <div class="meta-item"><div class="label">Surface</div><div class="value">{surface}</div></div>
    <div class="meta-item"><div class="label">Footwear</div><div class="value">{footwear}</div></div>
    <div class="meta-item"><div class="label">Wind</div><div class="value">{wind}</div></div>
    <div class="meta-item"><div class="label">Operator</div><div class="value">{operator}</div></div>
  </div>
'''
    return html


def format_header(trials_df: pd.DataFrame, mode: str) -> str:
    """Build header HTML with title, subtitle, and brand."""
    if "Mode A" in mode:
        # Mode A: athlete · date range · SprintScope laser, 200 Hz
        athlete = trials_df.iloc[0]["athlete_name"]
        dates = trials_df.sort_values("session_date")
        date_min = dates.iloc[0]["session_date"]
        date_max = dates.iloc[-1]["session_date"]
        
        if date_min == date_max:
            date_str = str(date_min)
        else:
            date_str = f"{date_min} to {date_max}"
        
        subtitle = f"{athlete} - {date_str} - SprintScope laser, 200 Hz"
    else:  # Mode B
        # Mode B: cohort · rule · SprintScope laser, 200 Hz
        athletes = ", ".join(trials_df["athlete_name"].unique().tolist())
        # Try to infer rule from context (would be passed in real implementation)
        subtitle = f"{athletes} - representative trials - SprintScope laser, 200 Hz"
    
    html = f'''  <div class="header">
    <div>
      <h1>Sprint Session: Performance Analysis</h1>
      <div class="subtitle">{subtitle}</div>
    </div>
    <div class="brand">
      <div class="brand-mark">TEAM <span class="saudi">SAUDI</span></div>
      <div class="brand-sub">Athletics &amp; Para Athletics</div>
    </div>
  </div>
'''
    return html


def generate_report_html(
    trials_df: pd.DataFrame,
    db,
    split_interval: float,
    mode: str,
    analyst_notes: str = "",
) -> str:
    """
    Generate complete report HTML by filling team_saudi_report_template.html.
    
    Args:
        trials_df: Selected trials (already filtered for comparability)
        db: Database connection
        split_interval: Split interval in meters
        mode: "Mode A" or "Mode B"
        analyst_notes: Free-text analyst notes (can be empty)
    
    Returns:
        Complete HTML string ready for PDF conversion or download
    """
    
    # Generate plot image
    plot_img = generate_velocity_plot_image(trials_df, db, mode)
    
    # Build matrices
    cum_html, vel_html = build_split_matrices_html(
        trials_df, db, split_interval, mode
    )
    
    # Format metadata and header
    metadata_html = format_metadata_strip(trials_df, mode)
    header_html = format_header(trials_df, mode)
    
    # Analyst notes (only if not empty)
    notes_html = ""
    if analyst_notes and analyst_notes.strip():
        notes_html = f'  <div class="notes">\n    {analyst_notes}\n  </div>\n'
    
    # Operator name (extract from first trial)
    operator = trials_df.iloc[0].get("operator", "Analyst") or "Analyst"
    
    # Build complete HTML
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Sprint Session Report</title>
<style>
  :root {{
    --green: #006C35;
    --gold: #9C7C2E;
    --ink: #1c1f23;
    --muted: #6b7280;
    --rule: #e3e6ea;
    --rule-strong: #c9ced5;
    --bg: #ffffff;
    --highlight-bg: #f3efe2;
    --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }}

  @page {{
    size: A4;
    margin: 16mm 14mm 14mm 14mm;
  }}

  * {{ box-sizing: border-box; }}

  body {{
    font-family: var(--sans);
    color: var(--ink);
    background: var(--bg);
    margin: 0;
    font-size: 12px;
    line-height: 1.45;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }}

  .page {{ max-width: 980px; margin: 0 auto; padding: 24px 28px; }}

  /* ---------- Header ---------- */
  .header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    border-bottom: 2px solid var(--green);
    padding-bottom: 12px;
  }}
  .header h1 {{
    margin: 0;
    font-size: 22px;
    font-weight: 700;
    color: var(--green);
    letter-spacing: -0.01em;
  }}
  .header .subtitle {{
    margin-top: 4px;
    color: var(--muted);
    font-size: 12px;
  }}
  .brand {{ text-align: right; line-height: 1.3; white-space: nowrap; }}
  .brand .brand-mark {{
    font-size: 15px;
    font-weight: 800;
    letter-spacing: 0.06em;
    color: var(--ink);
  }}
  .brand .brand-mark .saudi {{ color: var(--gold); }}
  .brand .brand-sub {{ font-size: 11px; color: var(--muted); }}

  /* ---------- Metadata strip ---------- */
  .meta-strip {{
    display: flex;
    flex-wrap: wrap;
    gap: 26px;
    background: #f7f8f9;
    border: 1px solid var(--rule);
    border-radius: 6px;
    padding: 12px 16px;
    margin-top: 16px;
  }}
  .meta-item {{ min-width: 90px; }}
  .meta-item .label {{
    font-size: 9.5px;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: var(--muted);
  }}
  .meta-item .value {{ font-size: 13px; font-weight: 700; color: var(--ink); margin-top: 2px; }}

  /* ---------- Section heading (eyebrow) ---------- */
  .eyebrow {{
    margin: 26px 0 10px;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--green);
    border-bottom: 1px solid var(--rule);
    padding-bottom: 6px;
  }}

  /* ---------- Figure / plot ---------- */
  figure {{ margin: 0; }}
  .plot-frame {{
    border: 1px solid var(--rule);
    border-radius: 6px;
    padding: 10px;
    text-align: center;
  }}
  .plot-frame img {{ max-width: 100%; height: auto; }}
  figcaption {{
    margin-top: 10px;
    font-size: 11.5px;
    color: var(--ink);
  }}
  figcaption .lead {{ font-weight: 700; }}

  /* ---------- Tables (shared) ---------- */
  table {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
  th, td {{
    padding: 6px 9px;
    font-size: 11.5px;
    border-bottom: 1px solid var(--rule);
    text-align: right;
  }}
  th {{
    font-size: 9.5px;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--muted);
    font-weight: 700;
    border-bottom: 1px solid var(--rule-strong);
    background: #fbfbfc;
  }}
  th:first-child, td:first-child {{ text-align: left; }}
  tbody tr:last-child td {{ border-bottom: 1px solid var(--rule-strong); }}

  td.best {{ background: var(--highlight-bg); font-weight: 700; color: var(--green); }}

  .table-note {{ font-size: 10px; color: var(--muted); margin-top: 6px; }}

  /* ---------- Analyst notes (narrative) ---------- */
  .notes {{
    margin-top: 18px;
    padding: 12px 14px;
    border-left: 3px solid var(--gold);
    background: #fbfaf6;
    font-size: 12px;
    line-height: 1.5;
  }}

  /* ---------- Footer ---------- */
  .provenance {{
    margin-top: 26px;
    padding-top: 10px;
    border-top: 1px solid var(--rule);
    font-size: 10px;
    color: var(--muted);
  }}

  @media print {{
    .page {{ padding: 0; }}
    .page-break {{ page-break-before: always; }}
  }}
</style>
</head>
<body>
<div class="page">

{header_html}

{metadata_html}

  <div class="eyebrow">Velocity vs Distance</div>
  <figure>
    <div class="plot-frame">
      <img src="{plot_img}" alt="Velocity vs distance overlay">
    </div>
    <figcaption>
      <span class="lead">Overlay of the selected trials.</span>
      This plot shows the filtered velocity profile for each selected trial, with peak velocity marked per line.
    </figcaption>
  </figure>

  <div class="eyebrow">Cumulative Split Times</div>
{cum_html}
  <div class="table-note">Best time per distance highlighted. Empty cells use a hyphen.</div>

  <div class="eyebrow">Velocity at Split</div>
{vel_html}

{notes_html}

  <div class="provenance">
    Data: SprintScope at 200 Hz, Butterworth order 2. Operator {operator}. Team Saudi Athletics - Performance Analysis
  </div>

</div>
</body>
</html>
'''
    
    return html


def generate_pdf_from_html(html_content: str) -> bytes:
    """
    Convert HTML to PDF using weasyprint, or fallback to basic approach.
    
    Returns:
        PDF file as bytes
    """
    try:
        from weasyprint import HTML, CSS
        
        # Create PDF from HTML string
        pdf = HTML(string=html_content).write_pdf()
        return pdf
    except ImportError:
        # Fallback: return error message
        # In production, could use other methods like selenium/headless chrome
        raise ImportError(
            "weasyprint not installed. Install with: pip install weasyprint"
        )


def generate_filename(trials_df: pd.DataFrame, mode: str) -> str:
    """Generate report filename."""
    trial = trials_df.iloc[0]
    
    if "Mode A" in mode:
        athlete = trial["athlete_name"].replace(" ", "_")
        event = "30m" if trial["distance_m"] == 30 else f"{trial['distance_m']:.0f}m"
        date = trial["session_date"] or "nodate"
    else:  # Mode B
        athletes = "_".join([a.replace(" ", "") for a in trials_df["athlete_name"].unique()[:2]])
        event = f"{trial['distance_m']:.0f}m"
        date = trial["session_date"] or "nodate"
        athlete = athletes
    
    # Clean filename
    athlete = athlete.replace("/", "-").replace("\\", "-")
    date = str(date).replace("/", "-").replace(" ", "-")
    
    return f"{athlete}_{event}_session_report_{date}.pdf"
