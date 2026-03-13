"""
RowScope — 트레이스 파일 분석기
================================
프로젝트: RowScope — DRAM Row Buffer Locality Analyzer
파일:    analysis/analyze_trace.py
목적: C 벤치마크가 생성한 .trace 파일을 파싱하고, 각 주소를
     DRAMMapper + RowBufferModel에 통과시켜 트레이스별 및 접근별
     결과 데이터를 생성한다 (architecture.md §6 스키마 준수).

트레이스 파일 형식 (architecture.md §5.1):
  1행:  # benchmark=X size=Y stride=Z accesses=N element_size=4 seed=S iterations=I
  2행~: 십진수 가상 주소 (한 줄에 하나)

CLI 사용법:
    python -m analysis.analyze_trace \\
        --trace-dir traces/ \\
        --output results/processed/summary.csv \\
        --per-access-dir results/processed/per_access/ \\
        [--row-size 8192] [--num-banks 16] [--scheme sequential] \\
        [--verbose]

종료 코드 (architecture.md §7.3):
    0: 성공
    1: 설정 오류
    2: 트레이스 파일 오류
    3: 출력 오류

작성자:  [Implementation Engineer]
날짜:    2026-03-11
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Optional


def parse_trace_header(trace_path: str) -> dict:
    """
    트레이스 파일의 메타데이터 헤더 줄을 파싱한다.

    헤더는 1행이어야 하며 '#'으로 시작하고, 공백으로 구분된 key=value 쌍이 뒤따른다.

    Args:
        trace_path: .trace 파일 경로.

    Returns:
        메타데이터 key-value 쌍의 dict. 모든 값은 문자열.

    Raises:
        FileNotFoundError: trace_path가 존재하지 않는 경우.
        ValueError: 헤더 줄이 없거나 형식이 잘못된 경우.

    예시:
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
    # 선두의 '#'을 제거하고 공백으로 분리하여 key=value 토큰을 추출
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
    단일 트레이스 파일을 분석한다.

    트레이스의 모든 주소를 읽어 mapper와 새로운 RowBufferModel 인스턴스에 통과시키고,
    summary.csv 스키마에 맞는 요약 dict를 반환한다 (architecture.md §6.1).

    Args:
        trace_path:         .trace 파일 경로.
        mapper:             설정된 DRAMMapper 인스턴스.
        per_access_output:  None이 아니면, 접근별 어노테이션 CSV를 기록할 경로
                            (architecture.md §6.2 스키마).

    Returns:
        summary.csv 스키마의 모든 컬럼과 "trace_file"을 포함하는 dict.

    Raises:
        FileNotFoundError: trace_path가 존재하지 않는 경우.
        ValueError: 파일에 숫자가 아닌 줄이 있는 경우 (헤더 제외).
    """
    try:
        from analysis.row_buffer_model import RowBufferModel
    except ModuleNotFoundError:
        from row_buffer_model import RowBufferModel

    metadata = parse_trace_header(trace_path)

    model = RowBufferModel(mapper)

    # 요청된 경우 접근별 출력 CSV 열기
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
                    # 헤더 또는 주석 줄 — 건너뜀
                    continue

                try:
                    address = int(line)
                except ValueError:
                    raise ValueError(
                        f"Non-numeric line in trace {trace_path!r} "
                        f"at line {lineno + 1}: {line!r}"
                    )

                if per_access_csv is not None:
                    # prev_row_id 기록을 위해 이 접근 이전의 뱅크 상태를 캡처
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

    # 적절한 기본값을 사용해 메타데이터 필드 추출
    benchmark      = metadata.get("benchmark", "unknown")
    array_size_bytes = int(metadata.get("size", 0))
    stride_elem    = int(metadata.get("stride", 1))
    # stride_bytes: 요소 단위 stride × element_size (기본 element_size=4바이트)
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
        # 진단용 추가 필드
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
    디렉터리 내 모든 .trace 파일을 분석한다.

    Args:
        trace_dir:       .trace 파일이 있는 디렉터리.
        mapper:          설정된 DRAMMapper 인스턴스.
        per_access_dir:  None이 아니면, 접근별 CSV를 기록할 디렉터리.
        verbose:         각 트레이스 파일 처리 시 진행 상황을 출력.

    Returns:
        트레이스 파일 한 개당 한 행을 갖는 pandas DataFrame.
        컬럼은 summary.csv 스키마 (architecture.md §6.1)와 일치.

    Raises:
        FileNotFoundError: trace_dir이 존재하지 않는 경우.
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
# CLI 진입점
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

    # 간결한 요약 테이블을 stdout에 출력
    display_cols = [
        c for c in [
            "benchmark", "array_size_mb", "stride", "num_accesses",
            "row_hit_rate", "row_conflict_rate", "locality_score",
        ]
        if c in df.columns
    ]
    print()
    print(df[display_cols].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
