"""
RowScope — Trace File Analyzer
================================
Project: RowScope — DRAM Row Buffer Locality Analyzer
File:    analysis/analyze_trace.py
Purpose: Parse .trace files produced by C benchmarks, run each address through
         DRAMMapper + RowBufferModel, and produce per-trace and per-access
         result data matching the schemas in architecture.md §6.

Trace file format (architecture.md §5.1):
  Line 1:  # benchmark=X size=Y stride=Z accesses=N element_size=4 seed=S iterations=I
  Line 2+: one decimal virtual address per line

CLI usage:
    python -m analysis.analyze_trace \\
        --trace-dir traces/ \\
        --output results/processed/summary.csv \\
        --per-access-dir results/processed/per_access/ \\
        [--row-size 8192] [--num-banks 16] [--scheme sequential] \\
        [--verbose]

Exit codes (architecture.md §7.3):
    0: success
    1: configuration error
    2: trace file error
    3: output error

Author:  [Implementation Engineer]
Date:    2026-03-11
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Optional


def parse_trace_header(trace_path: str) -> dict:
    """
    Parse the metadata header line of a trace file.

    The header is expected to be line 1, starting with '#', followed by
    space-separated key=value pairs.

    Args:
        trace_path: Path to .trace file.

    Returns:
        Dict of metadata key-value pairs.  All values are strings.

    Raises:
        FileNotFoundError: If trace_path does not exist.
        ValueError: If the header line is missing or malformed.

    Example:
        parse_trace_header("traces/sequential_16MB_stride1.trace")
        -> {
               "benchmark": "sequential", "size": "16777216",
               "stride": "1", "accesses": "4194304",
               "element_size": "4", "seed": "0", "iterations": "3"
           }
    """
    p = Path(trace_path)
    if not p.exists():
        raise FileNotFoundError(f"Trace file not found: {trace_path}")

    with open(p, "r") as fh:
        first_line = fh.readline()

    if not first_line.startswith("#"):
        raise ValueError(
            f"Trace file {trace_path!r} does not start with a '#' header line. "
            f"Got: {first_line[:80]!r}"
        )

    metadata: dict = {}
    # Strip leading '#' and split on whitespace to get key=value tokens
    for token in first_line[1:].split():
        if "=" in token:
            key, _, value = token.partition("=")
            metadata[key.strip()] = value.strip()

    return metadata


def analyze_trace_file(
    trace_path: str,
    mapper,
    per_access_output: Optional[str] = None,
) -> dict:
    """
    Analyze a single trace file.

    Reads all addresses from the trace, feeds them through mapper and a fresh
    RowBufferModel instance, and returns a summary dict conforming to the
    summary.csv schema (architecture.md §6.1).

    Args:
        trace_path:         Path to .trace file.
        mapper:             Configured DRAMMapper instance.
        per_access_output:  If not None, path to write per-access annotated CSV
                            (architecture.md §6.2 schema).

    Returns:
        Dict with all columns from summary.csv schema, plus "trace_file".

    Raises:
        FileNotFoundError: If trace_path does not exist.
        ValueError: If the file contains non-numeric lines (other than header).
    """
    try:
        from analysis.row_buffer_model import RowBufferModel
    except ModuleNotFoundError:
        from row_buffer_model import RowBufferModel

    metadata = parse_trace_header(trace_path)

    model = RowBufferModel(mapper)

    # Open per-access output CSV if requested
    per_access_fh  = None
    per_access_csv = None
    if per_access_output is not None:
        Path(per_access_output).parent.mkdir(parents=True, exist_ok=True)
        per_access_fh  = open(per_access_output, "w", newline="")
        per_access_csv = csv.writer(per_access_fh)
        per_access_csv.writerow(
            ["access_seq", "address", "bank_id", "row_id", "col_offset", "event", "prev_row_id"]
        )

    try:
        access_seq = 0
        with open(trace_path, "r") as fh:
            for lineno, line in enumerate(fh):
                line = line.strip()
                if not line:
                    continue
                if line.startswith("#"):
                    # Header or comment — skip
                    continue

                try:
                    address = int(line)
                except ValueError:
                    raise ValueError(
                        f"Non-numeric line in trace {trace_path!r} "
                        f"at line {lineno + 1}: {line!r}"
                    )

                if per_access_csv is not None:
                    # Capture bank state before this access to record prev_row_id
                    bank_id_pre, row_id_pre, _ = mapper.map(address)
                    prev_row = model._open_row[bank_id_pre]
                    if prev_row == -1:
                        prev_row_str = "empty"
                    else:
                        prev_row_str = str(prev_row)

                bank_id, row_id, col_offset = mapper.map(address)
                event = model.process_access(address)

                if per_access_csv is not None:
                    per_access_csv.writerow(
                        [access_seq, address, bank_id, row_id, col_offset, event, prev_row_str]
                    )

                access_seq += 1

    finally:
        if per_access_fh is not None:
            per_access_fh.close()

    stats = model.get_stats()

    # Extract metadata fields with sensible defaults
    benchmark      = metadata.get("benchmark", "unknown")
    array_size_bytes = int(metadata.get("size", 0))
    stride_elem    = int(metadata.get("stride", 1))
    # stride_bytes: stride in elements * element_size (default element_size=4 bytes)
    element_size   = int(metadata.get("element_size", 4))
    stride_bytes   = stride_elem * element_size
    declared_accesses = int(metadata.get("accesses", access_seq))
    seed           = int(metadata.get("seed", 0))
    iterations     = int(metadata.get("iterations", 1))

    result = {
        "benchmark":            benchmark,
        "array_size_bytes":     array_size_bytes,
        "array_size_mb":        array_size_bytes / (1024.0 * 1024.0),
        "stride":               stride_elem,
        "stride_bytes":         stride_bytes,
        "num_accesses":         access_seq,
        "row_hit_count":        stats["hits"],
        "row_miss_count":       stats["misses"],
        "row_conflict_count":   stats["conflicts"],
        "row_hit_rate":         stats["hit_rate"],
        "row_miss_rate":        stats["miss_rate"],
        "row_conflict_rate":    stats["conflict_rate"],
        "locality_score":       stats["locality_score"],
        "unique_rows_accessed": stats["unique_rows"],
        "unique_banks_accessed": stats["unique_banks"],
        "trace_file":           str(trace_path),
        # bonus fields for diagnostics
        "seed":                 seed,
        "iterations":           iterations,
        "element_size":         element_size,
    }
    return result


def batch_analyze(
    trace_dir: str,
    mapper,
    per_access_dir: Optional[str] = None,
    verbose: bool = False,
) -> "pd.DataFrame":  # noqa: F821  (pandas imported lazily)
    """
    Analyze all .trace files in a directory.

    Args:
        trace_dir:       Directory containing .trace files.
        mapper:          Configured DRAMMapper instance.
        per_access_dir:  If not None, directory to write per-access CSVs.
        verbose:         Print progress for each trace file.

    Returns:
        pandas DataFrame with one row per trace file, columns matching
        summary.csv schema (architecture.md §6.1).

    Raises:
        FileNotFoundError: If trace_dir does not exist.
    """
    try:
        import pandas as pd
    except ImportError:
        print(
            "ERROR: pandas is required for batch_analyze. "
            "Install it with: pip install pandas",
            file=sys.stderr,
        )
        sys.exit(1)

    trace_dir_path = Path(trace_dir)
    if not trace_dir_path.exists():
        raise FileNotFoundError(f"Trace directory not found: {trace_dir}")

    trace_files = sorted(trace_dir_path.glob("*.trace"))
    if not trace_files:
        print(f"[WARNING] No .trace files found in {trace_dir}", file=sys.stderr)
        return pd.DataFrame()

    rows = []
    for trace_path in trace_files:
        if verbose:
            print(f"  Analyzing {trace_path.name}...")

        per_access_path: Optional[str] = None
        if per_access_dir is not None:
            per_access_path = str(
                Path(per_access_dir) / (trace_path.stem + "_annotated.csv")
            )
            Path(per_access_dir).mkdir(parents=True, exist_ok=True)

        try:
            row = analyze_trace_file(str(trace_path), mapper, per_access_path)
        except (FileNotFoundError, ValueError) as exc:
            print(f"  [WARNING] Skipping {trace_path.name}: {exc}", file=sys.stderr)
            continue

        rows.append(row)

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze RowScope trace files and produce summary.csv",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--trace-dir",
        required=True,
        metavar="DIR",
        help="Directory containing .trace files",
    )
    parser.add_argument(
        "--output",
        required=True,
        metavar="CSV",
        help="Output path for summary.csv",
    )
    parser.add_argument(
        "--per-access-dir",
        default=None,
        metavar="DIR",
        help="Directory for per-access annotated CSVs (optional)",
    )
    parser.add_argument(
        "--row-size",
        type=int,
        default=8192,
        metavar="N",
        help="DRAM row size in bytes (must be power of 2)",
    )
    parser.add_argument(
        "--num-banks",
        type=int,
        default=16,
        metavar="N",
        help="Number of DRAM banks (must be power of 2)",
    )
    parser.add_argument(
        "--scheme",
        choices=["sequential", "bitwise"],
        default="sequential",
        help="DRAM address interleaving scheme",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Print progress for each trace file",
    )
    return parser


if __name__ == "__main__":
    try:
        from analysis.dram_mapping import DRAMMapper
    except ModuleNotFoundError:
        from dram_mapping import DRAMMapper

    parser = _build_parser()
    args = parser.parse_args()

    try:
        mapper = DRAMMapper(args.row_size, args.num_banks, args.scheme)
    except ValueError as exc:
        print(f"[ERROR] Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        df = batch_analyze(
            args.trace_dir,
            mapper,
            per_access_dir=args.per_access_dir,
            verbose=args.verbose,
        )
    except FileNotFoundError as exc:
        print(f"[ERROR] Trace file error: {exc}", file=sys.stderr)
        sys.exit(2)

    if df.empty:
        print("[ERROR] No trace files were successfully analyzed.", file=sys.stderr)
        sys.exit(2)

    try:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(str(output_path), index=False, float_format="%.6f")
    except OSError as exc:
        print(f"[ERROR] Output error: {exc}", file=sys.stderr)
        sys.exit(3)

    print(f"Wrote {len(df)} rows to {args.output}")

    # Print a concise summary table to stdout
    display_cols = [
        c for c in [
            "benchmark", "array_size_mb", "stride", "num_accesses",
            "row_hit_rate", "row_conflict_rate", "locality_score",
        ]
        if c in df.columns
    ]
    print()
    print(df[display_cols].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
