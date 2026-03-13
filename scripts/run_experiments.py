#!/usr/bin/env python3
"""
RowScope 실험 오케스트레이터
=============================
프로젝트: RowScope — DRAM Row Buffer Locality Analyzer
파일:    scripts/run_experiments.py
목적: C 벤치마크 실험을 Python 수준에서 조율한다.
     실험 파라미터 매트릭스를 읽어 subprocess로 C 바이너리를 실행하고,
     key=value 형식의 stdout을 구조화된 JSON 결과 파일로 저장하며,
     트레이스 출력을 traces/에 기록한다.

사용법:
    python scripts/run_experiments.py --all
    python scripts/run_experiments.py --benchmark sequential
    python scripts/run_experiments.py --stride-sweep
    python scripts/run_experiments.py --workingset-sweep
    python scripts/run_experiments.py --analyze-only

플래그:
    --all                모든 실험 실행 (sequential, random, stride, sweep)
    --benchmark NAME     지정한 벤치마크만 실행
                         (sequential | random | stride | sweep)
    --stride-sweep       설정된 모든 stride 값으로 stride_access 실행
    --workingset-sweep   설정된 모든 크기로 working_set_sweep 실행
    --analyze-only       벤치마크 실행 건너뜀; 기존 트레이스 파일 분석만 수행
    --no-trace           C 바이너리에 --no-trace 전달 (타이밍 전용, 트레이스 파일 없음)
    --dry-run            실행 없이 명령어만 출력

작성자:  [Implementation Engineer]
날짜:    2026-03-11
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
# 프로젝트 루트: 이 스크립트 디렉터리의 한 단계 위
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR   = SCRIPT_DIR.parent
BIN_DIR    = ROOT_DIR / "bin"
TRACES_DIR = ROOT_DIR / "traces"
RESULTS_RAW_DIR = ROOT_DIR / "results" / "raw"

# ---------------------------------------------------------------------------
# 실험 파라미터 매트릭스 (architecture.md §9)
# ---------------------------------------------------------------------------
EXPERIMENTS = {
    # sequential: iterations는 전체 순회 횟수를 제어한다.
    # 큰 배열의 경우 트레이스 파일이 50MB 이하가 되도록 1회로 제한한다.
    # 1 MB  × 1 iter  / 4 bytes = 262,144 접근   →  ~2.6 MB 트레이스
    # 4 MB  × 1 iter  / 4 bytes = 1,048,576 접근 →  ~10 MB 트레이스
    # 16 MB × 1 iter  / 4 bytes = 4,194,304 접근 →  ~42 MB 트레이스 (경계선; 허용)
    # 64 MB: --no-trace 사용; 분석에도 너무 큼
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
    # working_set_sweep은 별도로 처리되는 단일 호출
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
    """간결하게 사람이 읽기 쉬운 크기 문자열을 반환한다 (예: 1048576 -> '1MB')."""
    if n >= (1 << 20) and n % (1 << 20) == 0:
        return f"{n >> 20}MB"
    if n >= (1 << 10) and n % (1 << 10) == 0:
        return f"{n >> 10}KB"
    return f"{n}B"


def _parse_kv_output(text: str) -> dict:
    """
    C 벤치마크 stdout (key=value 줄)을 Python dict로 파싱한다.
    여러 단계 출력 (working_set_sweep)은 여러 dict를 생성한다.
    '='가 포함된 각 출력 줄에 대해 dict 리스트를 반환한다.
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
    subprocess 명령어를 실행하고 stdout 문자열을 반환한다.
    실행 전 명령어를 출력한다. 0이 아닌 반환 코드 시 종료한다.
    """
    return _run_command_in_dir(cmd, cwd=None, dry_run=dry_run)


def _run_command_in_dir(cmd: list, cwd: Optional[str] = None, dry_run: bool = False) -> str:
    """
    지정된 작업 디렉터리에서 subprocess 명령어를 실행한다.
    stdout을 문자열로 반환한다. 0이 아닌 반환 코드 시 종료한다.
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
    """결과 레코드 리스트를 JSON 파일로 저장한다."""
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w") as f:
        json.dump(records, f, indent=2)
    print(f"  [saved] {json_path}")


def _check_binary(name: str) -> Path:
    """지정한 바이너리의 경로를 반환하고, 없으면 종료한다."""
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
# 벤치마크별 실행 함수
# ---------------------------------------------------------------------------

def run_sequential(no_trace: bool = False, dry_run: bool = False) -> list:
    """설정된 모든 크기로 sequential_access를 실행한다. 결과 dict 리스트를 반환한다."""
    binary = _check_binary("sequential_access")
    all_results = []
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for params in EXPERIMENTS["sequential"]:
        size_h = _human_size(params["size"])
        # 실험별 no_trace 플래그 (예: 거대한 트레이스 파일을 피하기 위한 64MB용)
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
    """설정된 모든 크기로 random_access를 실행한다. 결과 dict 리스트를 반환한다."""
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
    """설정된 모든 stride 값으로 stride_access를 실행한다. 결과 dict 리스트를 반환한다."""
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
    """working_set_sweep을 실행한다. 결과 dict 리스트를 반환한다."""
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
    traces/에 있는 트레이스 파일에 대해 Python 분석 파이프라인을 실행한다.
    상대 임포트가 해결되도록 analysis.analyze_trace를 모듈로 실행한다.
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
    # 'analysis' 패키지를 임포트할 수 있도록 프로젝트 루트에서 실행
    _run_command_in_dir(cmd, cwd=str(ROOT_DIR), dry_run=dry_run)


def run_summarize(dry_run: bool = False) -> None:
    """
    summary_table.csv 생성을 위해 summarize_results.py를 실행한다.
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
# CLI 진입점
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

    # 출력 디렉터리가 존재하는지 확인
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
