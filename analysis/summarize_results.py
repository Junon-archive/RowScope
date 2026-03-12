"""
RowScope — Results Summarizer
===============================
Project: RowScope — DRAM Row Buffer Locality Analyzer
File:    analysis/summarize_results.py
Purpose: Load summary.csv produced by analyze_trace.py and generate
         human-readable summary tables grouped by benchmark type.
         Outputs a condensed summary_table.csv for reporting.

Summary CSV schema (architecture.md §6.1):
    benchmark, array_size_bytes, array_size_mb, stride, stride_bytes,
    num_accesses, row_hit_count, row_miss_count, row_conflict_count,
    row_hit_rate, row_miss_rate, row_conflict_rate, locality_score,
    unique_rows_accessed, unique_banks_accessed, trace_file

Output summary_table columns:
    benchmark, avg_hit_rate, avg_conflict_rate, avg_locality_score,
    num_experiments

Author:  [Implementation Engineer]
Date:    2026-03-11
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional


def _import_pandas():
    """Import pandas with a helpful error message if not installed."""
    try:
        import pandas as pd
        return pd
    except ImportError:
        print(
            "ERROR: pandas is required. Install it with: pip install pandas",
            file=sys.stderr,
        )
        sys.exit(1)


def load_summary(summary_path: str) -> "pd.DataFrame":  # noqa: F821
    """
    Load summary.csv into a pandas DataFrame.

    Args:
        summary_path: Path to summary.csv.

    Returns:
        DataFrame with dtypes inferred from CSV content.

    Raises:
        FileNotFoundError: If summary_path does not exist.
    """
    pd = _import_pandas()
    p = Path(summary_path)
    if not p.exists():
        raise FileNotFoundError(f"Summary file not found: {summary_path}")
    return pd.read_csv(str(p))


def generate_summary_table(df: "pd.DataFrame") -> "pd.DataFrame":  # noqa: F821
    """
    Generate a human-readable summary table grouped by benchmark type.

    Groups df by 'benchmark' column and aggregates:
        avg_hit_rate       = mean(row_hit_rate)
        avg_conflict_rate  = mean(row_conflict_rate)
        avg_locality_score = mean(locality_score)
        num_experiments    = count of rows per group

    Args:
        df: DataFrame from load_summary().

    Returns:
        DataFrame with columns:
            benchmark, avg_hit_rate, avg_conflict_rate,
            avg_locality_score, num_experiments
        Sorted by avg_locality_score descending.
    """
    pd = _import_pandas()

    if df.empty:
        return pd.DataFrame(
            columns=[
                "benchmark", "avg_hit_rate", "avg_conflict_rate",
                "avg_locality_score", "num_experiments",
            ]
        )

    grouped = (
        df.groupby("benchmark", as_index=False)
        .agg(
            avg_hit_rate=("row_hit_rate", "mean"),
            avg_conflict_rate=("row_conflict_rate", "mean"),
            avg_locality_score=("locality_score", "mean"),
            num_experiments=("benchmark", "count"),
        )
        .sort_values("avg_locality_score", ascending=False)
        .reset_index(drop=True)
    )

    return grouped


def save_summary(df: "pd.DataFrame", output_path: str) -> None:  # noqa: F821
    """
    Write DataFrame to CSV with 6-decimal float precision.

    Args:
        df:          DataFrame to write.
        output_path: Destination path.

    Raises:
        OSError: If the output file cannot be written.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False, float_format="%.6f")
    print(f"Summary saved: {output_path}")


def load_all_results(results_dir: str) -> "pd.DataFrame":  # noqa: F821
    """
    Load and concatenate all summary CSV files found in results_dir.

    Searches for files matching 'summary*.csv' and '*_summary.csv'.

    Args:
        results_dir: Directory to search.

    Returns:
        Combined DataFrame, or empty DataFrame if none found.
    """
    pd = _import_pandas()
    p = Path(results_dir)

    if not p.exists():
        return pd.DataFrame()

    # Gather unique paths from both glob patterns
    paths = set(p.glob("summary*.csv")) | set(p.glob("*_summary.csv"))
    if not paths:
        return pd.DataFrame()

    dfs = []
    for csv_path in sorted(paths):
        try:
            dfs.append(pd.read_csv(str(csv_path)))
        except Exception as exc:
            print(f"[WARNING] Could not read {csv_path}: {exc}", file=sys.stderr)

    if not dfs:
        return pd.DataFrame()

    return pd.concat(dfs, ignore_index=True)


def print_aligned_table(df: "pd.DataFrame", float_fmt: str = "{:.4f}") -> None:
    """
    Print a DataFrame to stdout in aligned tabular form.

    Args:
        df:        DataFrame to print.
        float_fmt: Format string for floating-point columns.
    """
    if df.empty:
        print("(empty table)")
        return

    # Build string representations for each cell
    col_strings = {}
    for col in df.columns:
        col_strs = []
        for val in df[col]:
            if isinstance(val, float):
                col_strs.append(float_fmt.format(val))
            else:
                col_strs.append(str(val))
        col_strings[col] = col_strs

    # Compute column widths
    col_widths = {
        col: max(len(col), max((len(s) for s in col_strings[col]), default=0))
        for col in df.columns
    }

    # Print header
    header = "  ".join(col.ljust(col_widths[col]) for col in df.columns)
    print(header)
    print("-" * len(header))

    # Print rows
    for i in range(len(df)):
        row_str = "  ".join(
            col_strings[col][i].ljust(col_widths[col]) for col in df.columns
        )
        print(row_str)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize RowScope analysis results from summary.csv",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--input",
        required=True,
        metavar="CSV",
        help="Path to summary.csv produced by analyze_trace.py",
    )
    parser.add_argument(
        "--output",
        required=True,
        metavar="CSV",
        help="Output path for summary_table.csv",
    )
    return parser


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()

    try:
        df = load_summary(args.input)
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)

    if df.empty:
        print("[WARNING] summary.csv is empty — nothing to summarize.")
        sys.exit(0)

    table = generate_summary_table(df)
    save_summary(table, args.output)

    print()
    print_aligned_table(table)
