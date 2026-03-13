#!/usr/bin/env bash
# =============================================================================
# 프로젝트: RowScope — DRAM Row Buffer Locality Analyzer
# 파일:    scripts/run_all.sh
# 목적: 전체 파이프라인 실행기.
#       단계: 빌드 → 벤치마크 → 분석 → 시각화 → 보고서
#       각 단계는 플래그로 건너뛸 수 있다.
#
# 사용법:   ./scripts/run_all.sh [--skip-build] [--skip-benchmarks] \
#                                [--skip-analysis] [--skip-visualization] \
#                                [--skip-report]
#
# 작성자:  [Implementation Engineer]
# 날짜:    2026-03-11
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
BIN_DIR="$ROOT_DIR/bin"
TRACES_DIR="$ROOT_DIR/traces"
RESULTS_RAW_DIR="$ROOT_DIR/results/raw"
RESULTS_PROC_DIR="$ROOT_DIR/results/processed"
RESULTS_FIG_DIR="$ROOT_DIR/results/figures"
ANALYSIS_DIR="$ROOT_DIR/analysis"
VIZ_DIR="$ROOT_DIR/visualization"
REPORT_DIR="$ROOT_DIR/report"

# ---- 플래그 파싱 ---------------------------------------------------------------
SKIP_BUILD=0
SKIP_BENCHMARKS=0
SKIP_ANALYSIS=0
SKIP_VISUALIZATION=0
SKIP_REPORT=0

for arg in "$@"; do
    case "$arg" in
        --skip-build)         SKIP_BUILD=1 ;;
        --skip-benchmarks)    SKIP_BENCHMARKS=1 ;;
        --skip-analysis)      SKIP_ANALYSIS=1 ;;
        --skip-visualization) SKIP_VISUALIZATION=1 ;;
        --skip-report)        SKIP_REPORT=1 ;;
        --help|-h)
            echo "Usage: $0 [--skip-build] [--skip-benchmarks] [--skip-analysis]"
            echo "          [--skip-visualization] [--skip-report]"
            exit 0
            ;;
        *)
            echo "[run_all] WARNING: unknown argument '$arg' (ignored)" ;;
    esac
done

# ---- 헬퍼 함수 ---------------------------------------------------------------

log_stage() {
    echo ""
    echo "============================================================"
    echo " STAGE: $1"
    echo "============================================================"
}

require_binary() {
    local bin="$BIN_DIR/$1"
    if [[ ! -x "$bin" ]]; then
        echo "[run_all] ERROR: binary not found or not executable: $bin"
        echo "[run_all] Run './scripts/build.sh' first, or omit --skip-build."
        exit 1
    fi
}

# ---- 필요한 디렉터리 생성 -------------------------------------------------------
mkdir -p "$TRACES_DIR" "$RESULTS_RAW_DIR" "$RESULTS_PROC_DIR" "$RESULTS_FIG_DIR"

# ===========================================================================
# 단계 1: 빌드
# ===========================================================================
if [[ $SKIP_BUILD -eq 0 ]]; then
    log_stage "BUILD"
    bash "$SCRIPT_DIR/build.sh"
else
    echo "[run_all] Skipping build stage (--skip-build)"
fi

# ===========================================================================
# 단계 2: 벤치마크 실행
# ===========================================================================
if [[ $SKIP_BENCHMARKS -eq 0 ]]; then
    log_stage "BENCHMARKS"

    require_binary "sequential_access"
    require_binary "random_access"
    require_binary "stride_access"
    require_binary "working_set_sweep"

    # --- 순차 접근: 4가지 크기 ---
    SEQUENTIAL_SIZES=(1048576 4194304 16777216 67108864)
    for size in "${SEQUENTIAL_SIZES[@]}"; do
        size_mb=$(( size / 1048576 ))
        trace_file="$TRACES_DIR/sequential_${size_mb}MB_stride1_seed0_iter3.trace"
        result_file="$RESULTS_RAW_DIR/sequential_${size_mb}MB.txt"
        echo "[run_all] sequential  size=${size_mb}MB -> $trace_file"
        "$BIN_DIR/sequential_access" \
            --size="$size" \
            --iterations=3 \
            --output="$trace_file" \
            | tee "$result_file"
    done

    # --- 무작위 접근: 4가지 크기 ---
    RANDOM_SIZES=(1048576 4194304 16777216 67108864)
    for size in "${RANDOM_SIZES[@]}"; do
        size_mb=$(( size / 1048576 ))
        trace_file="$TRACES_DIR/random_${size_mb}MB_100000acc_seed42.trace"
        result_file="$RESULTS_RAW_DIR/random_${size_mb}MB.txt"
        echo "[run_all] random      size=${size_mb}MB -> $trace_file"
        "$BIN_DIR/random_access" \
            --size="$size" \
            --accesses=100000 \
            --seed=42 \
            --output="$trace_file" \
            | tee "$result_file"
    done

    # --- 스트라이드 접근: 11가지 stride 값 (고정 16MB) ---
    STRIDES=(1 2 4 8 16 32 64 128 256 512 1024)
    for stride in "${STRIDES[@]}"; do
        trace_file="$TRACES_DIR/stride_16MB_stride${stride}_100000acc.trace"
        result_file="$RESULTS_RAW_DIR/stride_16MB_stride${stride}.txt"
        echo "[run_all] stride      stride=${stride} -> $trace_file"
        "$BIN_DIR/stride_access" \
            --size=16777216 \
            --stride="$stride" \
            --accesses=100000 \
            --output="$trace_file" \
            | tee "$result_file"
    done

    # --- 워킹 셋 스윕: 512KB ~ 128MB, 9단계 ---
    sweep_result_file="$RESULTS_RAW_DIR/working_set_sweep.txt"
    echo "[run_all] working_set_sweep -> $TRACES_DIR"
    "$BIN_DIR/working_set_sweep" \
        --min-size=524288 \
        --max-size=134217728 \
        --steps=9 \
        --iterations=3 \
        --output-dir="$TRACES_DIR" \
        | tee "$sweep_result_file"

    echo "[run_all] Benchmarks complete. Trace files in $TRACES_DIR"
else
    echo "[run_all] Skipping benchmarks stage (--skip-benchmarks)"
fi

# ===========================================================================
# 단계 3: 분석
# ===========================================================================
if [[ $SKIP_ANALYSIS -eq 0 ]]; then
    log_stage "ANALYSIS"

    ANALYZE_SCRIPT="$ANALYSIS_DIR/analyze_trace.py"
    SUMMARIZE_SCRIPT="$ANALYSIS_DIR/summarize_results.py"

    if [[ ! -f "$ANALYZE_SCRIPT" ]]; then
        echo "[run_all] ERROR: $ANALYZE_SCRIPT not found."
        exit 1
    fi

    echo "[run_all] Running analyze_trace.py on all trace files..."
    # TODO: analyze_trace.py 구현 후 이 호출을 업데이트해야 한다.
    export PYTHONPATH="$ROOT_DIR:${PYTHONPATH:-}"
    python3 "$ANALYZE_SCRIPT" \
        --trace-dir "$TRACES_DIR" \
        --output "$RESULTS_PROC_DIR/summary.csv" \
        --per-access-dir "$RESULTS_PROC_DIR/per_access" \
        || { echo "[run_all] ERROR: analyze_trace.py failed (exit $?)."; exit 1; }

    echo "[run_all] Running summarize_results.py..."
    python3 "$SUMMARIZE_SCRIPT" \
        --input "$RESULTS_PROC_DIR/summary.csv" \
        --output "$RESULTS_PROC_DIR/summary_table.csv" \
        || { echo "[run_all] ERROR: summarize_results.py failed (exit $?)."; exit 1; }

    echo "[run_all] Analysis complete. Results in $RESULTS_PROC_DIR"
else
    echo "[run_all] Skipping analysis stage (--skip-analysis)"
fi

# ===========================================================================
# 단계 4: 시각화
# ===========================================================================
if [[ $SKIP_VISUALIZATION -eq 0 ]]; then
    log_stage "VISUALIZATION"

    PLOT_SCRIPT="$VIZ_DIR/plot_results.py"

    if [[ ! -f "$PLOT_SCRIPT" ]]; then
        echo "[run_all] ERROR: $PLOT_SCRIPT not found."
        exit 1
    fi

    echo "[run_all] Running plot_results.py..."
    export PYTHONPATH="$ROOT_DIR:${PYTHONPATH:-}"
    python3 "$PLOT_SCRIPT" \
        --summary "$RESULTS_PROC_DIR/summary.csv" \
        --output-dir "$RESULTS_FIG_DIR" \
        || { echo "[run_all] ERROR: plot_results.py failed (exit $?)."; exit 1; }

    echo "[run_all] Visualization complete. Figures in $RESULTS_FIG_DIR"
else
    echo "[run_all] Skipping visualization stage (--skip-visualization)"
fi

# ===========================================================================
# 단계 5: 보고서 생성
# ===========================================================================
if [[ $SKIP_REPORT -eq 0 ]]; then
    log_stage "REPORT"

    REPORT_SCRIPT="$REPORT_DIR/generate_report.py"

    if [[ ! -f "$REPORT_SCRIPT" ]]; then
        echo "[run_all] ERROR: $REPORT_SCRIPT not found."
        exit 1
    fi

    echo "[run_all] Running generate_report.py..."
    export PYTHONPATH="$ROOT_DIR:${PYTHONPATH:-}"
    python3 "$REPORT_SCRIPT" \
        --summary "$RESULTS_PROC_DIR/summary.csv" \
        --figures-dir "results/figures" \
        --template "$REPORT_DIR/report_template.md" \
        --output "$REPORT_DIR/final_report.md" \
        || { echo "[run_all] ERROR: generate_report.py failed (exit $?)."; exit 1; }

    echo "[run_all] Report written to $REPORT_DIR/final_report.md"
else
    echo "[run_all] Skipping report stage (--skip-report)"
fi

echo ""
echo "============================================================"
echo " RowScope pipeline complete."
echo "============================================================"
