#!/usr/bin/env python3
"""
RowScope Experiment Orchestrator
=================================
Project: RowScope — DRAM Row Buffer Locality Analyzer
File:    scripts/run_experiments.py
Purpose: Python-level orchestration of C benchmark experiments.
         Reads experiment parameter matrices, runs C binaries via subprocess,
         captures key=value stdout into structured JSON result files, and
         saves trace outputs to traces/.

Usage:
    python scripts/run_experiments.py --all
    python scripts/run_experiments.py --benchmark sequential
    python scripts/run_experiments.py --stride-sweep
    python scripts/run_experiments.py --workingset-sweep
    python scripts/run_experiments.py --analyze-only

Flags:
    --all                Run all experiments (sequential, random, stride, sweep)
    --benchmark NAME     Run only the named benchmark
                         (sequential | random | stride | sweep)
    --stride-sweep       Run stride_access across all configured stride values
    --workingset-sweep   Run working_set_sweep across all configured sizes
    --analyze-only       Skip benchmark execution; re-run analysis only
    --no-trace           Pass --no-trace to C binaries (timing only, no trace files)
    --dry-run            Print commands without executing them

Author:  [Implementation Engineer]
Date:    2026-03-11
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Project root: one level up from this script's directory
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR   = SCRIPT_DIR.parent
BIN_DIR    = ROOT_DIR / "bin"
TRACES_DIR = ROOT_DIR / "traces"
RESULTS_RAW_DIR = ROOT_DIR / "results" / "raw"

# ---------------------------------------------------------------------------
# Experiment parameter matrix (architecture.md §9)
# ---------------------------------------------------------------------------
EXPERIMENTS = {
    # sequential: iterations controls how many full sweeps are done.
    # For large arrays we cap at 1 iteration to keep trace files below 50 MB.
    # 1 MB  * 1 iter  / 4 bytes = 262 144 accesses  ->  ~2.6 MB trace
    # 4 MB  * 1 iter  / 4 bytes = 1 048 576 accesses ->  ~10 MB trace
    # 16 MB * 1 iter  / 4 bytes = 4 194 304 accesses ->  ~42 MB trace (borderline; ok)
    # 64 MB: use --no-trace; too large for analysis anyway
    "sequential": [
        {"size": 1  * 1024 * 1024, "iterations": 1, "no_trace": False},
        {"size": 4  * 1024 * 1024, "iterations": 1, "no_trace": False},
        {"size": 16 * 1024 * 1024, "iterations": 1, "no_trace": False},
        {"size": 64 * 1024 * 1024, "iterations": 1, "no_trace": True},
    ],
    "random": [
        {"size": 1  * 1024 * 1024, "accesses": 200000, "seed": 42},
        {"size": 4  * 1024 * 1024, "accesses": 200000, "seed": 42},
        {"size": 16 * 1024 * 1024, "accesses": 200000, "seed": 42},
        {"size": 64 * 1024 * 1024, "accesses": 200000, "seed": 42},
    ],
    "stride": [
        {"size": 16 * 1024 * 1024, "stride": s, "accesses": 200000}
        for s in [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024]
    ],
    # working_set_sweep is a single invocation handled separately
    "sweep": [
        {
            "min_size":   512 * 1024,
            "max_size":   128 * 1024 * 1024,
            "steps":      9,
            "iterations": 3,
        }
    ],
}


def _human_size(n: int) -> str:
    """Return a compact human-readable size string (e.g. 1048576 -> '1MB')."""
    if n >= (1 << 20) and n % (1 << 20) == 0:
        return f"{n >> 20}MB"
    if n >= (1 << 10) and n % (1 << 10) == 0:
        return f"{n >> 10}KB"
    return f"{n}B"


def _parse_kv_output(text: str) -> dict:
    """
    Parse C benchmark stdout (key=value lines) into a Python dict.
    Multi-value steps (working_set_sweep) produce multiple dicts.
    Returns a list of dicts (one per output line that contains '=').
    """
    results = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        record = {}
        for token in line.split():
            if "=" in token:
                k, _, v = token.partition("=")
                record[k] = v
        if record:
            results.append(record)
    return results


def _run_command(cmd: list, dry_run: bool = False) -> str:
    """
    Run a subprocess command, return its stdout as a string.
    Prints the command before running.  Exits on non-zero return code.
    """
    return _run_command_in_dir(cmd, cwd=None, dry_run=dry_run)


def _run_command_in_dir(cmd: list, cwd: Optional[str] = None, dry_run: bool = False) -> str:
    """
    Run a subprocess command in a given working directory.
    Returns stdout as a string.  Exits on non-zero return code.
    """
    cmd_str = " ".join(str(c) for c in cmd)
    print(f"  [cmd] {cmd_str}")
    if cwd:
        print(f"  [cwd] {cwd}")

    if dry_run:
        return ""

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            cwd=cwd,
        )
    except FileNotFoundError:
        print(f"  [ERROR] Binary not found: {cmd[0]}", file=sys.stderr)
        sys.exit(1)

    if result.returncode != 0:
        print(f"  [ERROR] Command exited with code {result.returncode}", file=sys.stderr)
        print(f"  [stderr] {result.stderr.strip()}", file=sys.stderr)
        sys.exit(result.returncode)

    if result.stdout:
        for line in result.stdout.strip().splitlines():
            print(f"    {line}")

    return result.stdout


def _save_json(records: list, json_path: Path) -> None:
    """Persist a list of result records to a JSON file."""
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w") as f:
        json.dump(records, f, indent=2)
    print(f"  [saved] {json_path}")


def _check_binary(name: str) -> Path:
    """Return path to named binary, exit if not found."""
    binary = BIN_DIR / name
    if not binary.exists():
        print(
            f"[ERROR] Binary '{binary}' not found. "
            f"Run './scripts/build.sh' first.",
            file=sys.stderr,
        )
        sys.exit(1)
    return binary


# ---------------------------------------------------------------------------
# Per-benchmark run functions
# ---------------------------------------------------------------------------

def run_sequential(no_trace: bool = False, dry_run: bool = False) -> list:
    """Run sequential_access for all configured sizes. Returns list of result dicts."""
    binary = _check_binary("sequential_access")
    all_results = []
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for params in EXPERIMENTS["sequential"]:
        size_h = _human_size(params["size"])
        # Per-experiment no_trace flag (e.g. for 64 MB to avoid huge trace files)
        experiment_no_trace = no_trace or params.get("no_trace", False)
        trace_path = TRACES_DIR / f"sequential_{size_h}_stride1_seed0_iter{params['iterations']}.trace"

        cmd = [
            str(binary),
            f"--size={params['size']}",
            f"--iterations={params['iterations']}",
        ]
        if experiment_no_trace:
            cmd.append("--no-trace")
        else:
            cmd.append(f"--output={trace_path}")

        print(f"\n[sequential] size={size_h} iterations={params['iterations']}"
              f"{' (no-trace)' if experiment_no_trace else ''}")
        stdout = _run_command(cmd, dry_run=dry_run)
        records = _parse_kv_output(stdout)
        all_results.extend(records)

    json_path = RESULTS_RAW_DIR / f"sequential_{timestamp}.json"
    if not dry_run:
        _save_json(all_results, json_path)
    return all_results


def run_random(no_trace: bool = False, dry_run: bool = False) -> list:
    """Run random_access for all configured sizes. Returns list of result dicts."""
    binary = _check_binary("random_access")
    all_results = []
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for params in EXPERIMENTS["random"]:
        size_h = _human_size(params["size"])
        trace_path = TRACES_DIR / f"random_{size_h}_{params['accesses']}acc_seed{params['seed']}.trace"
        cmd = [
            str(binary),
            f"--size={params['size']}",
            f"--accesses={params['accesses']}",
            f"--seed={params['seed']}",
            f"--output={trace_path}",
        ]
        if no_trace:
            cmd.append("--no-trace")

        print(f"\n[random] size={size_h} accesses={params['accesses']} seed={params['seed']}")
        stdout = _run_command(cmd, dry_run=dry_run)
        records = _parse_kv_output(stdout)
        all_results.extend(records)

    json_path = RESULTS_RAW_DIR / f"random_{timestamp}.json"
    if not dry_run:
        _save_json(all_results, json_path)
    return all_results


def run_stride(no_trace: bool = False, dry_run: bool = False) -> list:
    """Run stride_access for all configured stride values. Returns list of result dicts."""
    binary = _check_binary("stride_access")
    all_results = []
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for params in EXPERIMENTS["stride"]:
        size_h = _human_size(params["size"])
        trace_path = TRACES_DIR / f"stride_{size_h}_stride{params['stride']}_{params['accesses']}acc.trace"
        cmd = [
            str(binary),
            f"--size={params['size']}",
            f"--stride={params['stride']}",
            f"--accesses={params['accesses']}",
            f"--output={trace_path}",
        ]
        if no_trace:
            cmd.append("--no-trace")

        print(f"\n[stride] size={size_h} stride={params['stride']} accesses={params['accesses']}")
        stdout = _run_command(cmd, dry_run=dry_run)
        records = _parse_kv_output(stdout)
        all_results.extend(records)

    json_path = RESULTS_RAW_DIR / f"stride_{timestamp}.json"
    if not dry_run:
        _save_json(all_results, json_path)
    return all_results


def run_sweep(no_trace: bool = False, dry_run: bool = False) -> list:
    """Run working_set_sweep. Returns list of result dicts."""
    binary = _check_binary("working_set_sweep")
    all_results = []
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for params in EXPERIMENTS["sweep"]:
        cmd = [
            str(binary),
            f"--min-size={params['min_size']}",
            f"--max-size={params['max_size']}",
            f"--steps={params['steps']}",
            f"--iterations={params['iterations']}",
            f"--output-dir={TRACES_DIR}",
        ]
        if no_trace:
            cmd.append("--no-trace")

        min_h = _human_size(params["min_size"])
        max_h = _human_size(params["max_size"])
        print(f"\n[sweep] min={min_h} max={max_h} steps={params['steps']}")
        stdout = _run_command(cmd, dry_run=dry_run)
        records = _parse_kv_output(stdout)
        all_results.extend(records)

    json_path = RESULTS_RAW_DIR / f"sweep_{timestamp}.json"
    if not dry_run:
        _save_json(all_results, json_path)
    return all_results


def run_analysis(dry_run: bool = False) -> None:
    """
    Run Python analysis pipeline on trace files already in traces/.
    Invokes analysis.analyze_trace as a module so relative imports resolve.
    """
    analyze_module = ROOT_DIR / "analysis" / "analyze_trace.py"
    if not analyze_module.exists():
        print(f"[WARNING] {analyze_module} not found, skipping analysis.", file=sys.stderr)
        return

    output_csv = ROOT_DIR / "results" / "processed" / "summary.csv"
    cmd = [
        sys.executable,
        "-m", "analysis.analyze_trace",
        "--trace-dir", str(TRACES_DIR),
        "--output",    str(output_csv),
        "--verbose",
    ]
    print("\n[analysis] Running analysis.analyze_trace...")
    # Run from project root so the 'analysis' package is importable
    _run_command_in_dir(cmd, cwd=str(ROOT_DIR), dry_run=dry_run)


def run_summarize(dry_run: bool = False) -> None:
    """
    Run summarize_results.py to produce summary_table.csv.
    """
    output_csv   = ROOT_DIR / "results" / "processed" / "summary.csv"
    summary_tbl  = ROOT_DIR / "results" / "processed" / "summary_table.csv"

    if not output_csv.exists():
        print(f"[WARNING] {output_csv} not found, skipping summarize.", file=sys.stderr)
        return

    cmd = [
        sys.executable,
        "-m", "analysis.summarize_results",
        "--input",  str(output_csv),
        "--output", str(summary_tbl),
    ]
    print("\n[analysis] Running analysis.summarize_results...")
    _run_command_in_dir(cmd, cwd=str(ROOT_DIR), dry_run=dry_run)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="RowScope Experiment Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/run_experiments.py --all\n"
            "  python scripts/run_experiments.py --benchmark sequential\n"
            "  python scripts/run_experiments.py --stride-sweep\n"
            "  python scripts/run_experiments.py --workingset-sweep\n"
            "  python scripts/run_experiments.py --analyze-only\n"
        ),
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--all",
        action="store_true",
        help="Run all experiments (sequential, random, stride, working_set_sweep)",
    )
    group.add_argument(
        "--benchmark",
        metavar="NAME",
        choices=["sequential", "random", "stride", "sweep"],
        help="Run only the named benchmark",
    )
    group.add_argument(
        "--stride-sweep",
        action="store_true",
        help="Run stride_access across all configured stride values",
    )
    group.add_argument(
        "--workingset-sweep",
        action="store_true",
        help="Run working_set_sweep across all configured sizes",
    )
    group.add_argument(
        "--analyze-only",
        action="store_true",
        help="Skip benchmark execution; run analysis on existing trace files only",
    )
    parser.add_argument(
        "--no-trace",
        action="store_true",
        default=False,
        help="Pass --no-trace to C binaries (timing-only mode, no trace files)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print commands without executing them",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Ensure output directories exist
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_RAW_DIR.mkdir(parents=True, exist_ok=True)

    start_time = datetime.now()
    print(f"[run_experiments] Started at {start_time.isoformat()}")
    print(f"[run_experiments] ROOT_DIR = {ROOT_DIR}")

    if args.analyze_only:
        run_analysis(dry_run=args.dry_run)
        run_summarize(dry_run=args.dry_run)

    elif args.all:
        run_sequential(no_trace=args.no_trace, dry_run=args.dry_run)
        run_random(    no_trace=args.no_trace, dry_run=args.dry_run)
        run_stride(    no_trace=args.no_trace, dry_run=args.dry_run)
        run_sweep(     no_trace=args.no_trace, dry_run=args.dry_run)
        run_analysis(dry_run=args.dry_run)
        run_summarize(dry_run=args.dry_run)

    elif args.benchmark == "sequential":
        run_sequential(no_trace=args.no_trace, dry_run=args.dry_run)

    elif args.benchmark == "random":
        run_random(no_trace=args.no_trace, dry_run=args.dry_run)

    elif args.benchmark == "stride":
        run_stride(no_trace=args.no_trace, dry_run=args.dry_run)

    elif args.benchmark == "sweep":
        run_sweep(no_trace=args.no_trace, dry_run=args.dry_run)

    elif args.stride_sweep:
        run_stride(no_trace=args.no_trace, dry_run=args.dry_run)

    elif args.workingset_sweep:
        run_sweep(no_trace=args.no_trace, dry_run=args.dry_run)

    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\n[run_experiments] Done in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
