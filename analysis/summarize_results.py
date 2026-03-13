"""
RowScope — 결과 요약기
=======================
프로젝트: RowScope — DRAM Row Buffer Locality Analyzer
파일:    analysis/summarize_results.py
목적: analyze_trace.py가 생성한 summary.csv를 불러와
     벤치마크 유형별로 그룹화한 사람이 읽기 쉬운 요약 테이블을 생성한다.
     보고서 작성용으로 압축된 summary_table.csv를 출력한다.

Summary CSV 스키마 (architecture.md §6.1):
    benchmark, array_size_bytes, array_size_mb, stride, stride_bytes,
    num_accesses, row_hit_count, row_miss_count, row_conflict_count,
    row_hit_rate, row_miss_rate, row_conflict_rate, locality_score,
    unique_rows_accessed, unique_banks_accessed, trace_file

출력 summary_table 컬럼:
    benchmark, avg_hit_rate, avg_conflict_rate, avg_locality_score,
    num_experiments

작성자:  [Implementation Engineer]
날짜:    2026-03-11
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional


def _import_pandas():
    """pandas를 임포트한다. 설치되지 않은 경우 유용한 오류 메시지를 출력한다."""
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
    summary.csv를 pandas DataFrame으로 불러온다.

    Args:
        summary_path: summary.csv 경로.

    Returns:
        CSV 내용으로부터 dtype이 추론된 DataFrame.

    Raises:
        FileNotFoundError: summary_path가 존재하지 않는 경우.
    """
    pd = _import_pandas()
    p = Path(summary_path)
    if not p.exists():
        raise FileNotFoundError(f"Summary file not found: {summary_path}")
    return pd.read_csv(str(p))


def generate_summary_table(df: "pd.DataFrame") -> "pd.DataFrame":  # noqa: F821
    """
    벤치마크 유형별로 그룹화한 사람이 읽기 쉬운 요약 테이블을 생성한다.

    df를 'benchmark' 컬럼으로 그룹화하고 아래를 집계한다:
        avg_hit_rate       = mean(row_hit_rate)
        avg_conflict_rate  = mean(row_conflict_rate)
        avg_locality_score = mean(locality_score)
        num_experiments    = 그룹별 행 수

    Args:
        df: load_summary()에서 반환된 DataFrame.

    Returns:
        아래 컬럼을 갖는 DataFrame:
            benchmark, avg_hit_rate, avg_conflict_rate,
            avg_locality_score, num_experiments
        avg_locality_score 내림차순 정렬.
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
    DataFrame을 소수점 6자리 정밀도로 CSV에 저장한다.

    Args:
        df:          저장할 DataFrame.
        output_path: 저장 경로.

    Raises:
        OSError: 출력 파일을 쓸 수 없는 경우.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False, float_format="%.6f")
    print(f"Summary saved: {output_path}")


def load_all_results(results_dir: str) -> "pd.DataFrame":  # noqa: F821
    """
    results_dir에서 모든 요약 CSV 파일을 불러와 합친다.

    'summary*.csv'와 '*_summary.csv' 패턴에 맞는 파일을 탐색한다.

    Args:
        results_dir: 탐색할 디렉터리.

    Returns:
        합쳐진 DataFrame. 파일이 없으면 빈 DataFrame을 반환.
    """
    pd = _import_pandas()
    p = Path(results_dir)

    if not p.exists():
        return pd.DataFrame()

    # 두 가지 glob 패턴에서 고유한 경로를 수집
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
    DataFrame을 정렬된 표 형식으로 stdout에 출력한다.

    Args:
        df:        출력할 DataFrame.
        float_fmt: 부동소수점 컬럼의 형식 문자열.
    """
    if df.empty:
        print("(empty table)")
        return

    # 각 셀의 문자열 표현 생성
    col_strings = {}
    for col in df.columns:
        col_strs = []
        for val in df[col]:
            if isinstance(val, float):
                col_strs.append(float_fmt.format(val))
            else:
                col_strs.append(str(val))
        col_strings[col] = col_strs

    # 컬럼 너비 계산
    col_widths = {
        col: max(len(col), max((len(s) for s in col_strings[col]), default=0))
        for col in df.columns
    }

    # 헤더 출력
    header = "  ".join(col.ljust(col_widths[col]) for col in df.columns)
    print(header)
    print("-" * len(header))

    # 행 출력
    for i in range(len(df)):
        row_str = "  ".join(
            col_strings[col][i].ljust(col_widths[col]) for col in df.columns
        )
        print(row_str)


# ---------------------------------------------------------------------------
# CLI 진입점
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
