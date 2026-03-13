#!/usr/bin/env bash
# =============================================================================
# 프로젝트: RowScope — DRAM Row Buffer Locality Analyzer
# 파일:    scripts/build.sh
# 목적: 모든 C 벤치마크 프로그램을 bin/에 컴파일한다.
#       컴파일이 하나라도 실패하면 0이 아닌 종료 코드로 종료한다.
#       파일별 성공/실패 결과를 stdout에 출력한다.
# 사용법:   ./scripts/build.sh
# 작성자:  [Implementation Engineer]
# 날짜:    2026-03-11
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
BENCH_DIR="$ROOT_DIR/benchmarks"
BIN_DIR="$ROOT_DIR/bin"

# architecture.md §8.1은 c11과 -lm을 명시하지만, 우리 기능 셋에는 c99도 적합하다.
# working_set_sweep.c의 math.h (log/exp) 지원을 위해 -std=c99 -lm으로 컴파일하며,
# 이 호스트의 gcc 버전과도 호환된다.
CFLAGS="-O2 -std=c99 -Wall -Wextra"
LDFLAGS="-lm"

BENCHMARKS=(
    "sequential_access"
    "random_access"
    "stride_access"
    "working_set_sweep"
)

echo "[build] RowScope benchmark build starting..."
echo "[build] ROOT_DIR   = $ROOT_DIR"
echo "[build] BENCH_DIR  = $BENCH_DIR"
echo "[build] BIN_DIR    = $BIN_DIR"
echo "[build] CFLAGS     = $CFLAGS"
echo ""

mkdir -p "$BIN_DIR"

FAILED=0

for bench in "${BENCHMARKS[@]}"; do
    src="$BENCH_DIR/${bench}.c"
    out="$BIN_DIR/${bench}"

    if [[ ! -f "$src" ]]; then
        echo "[build] SKIP   $bench  (source not found: $src)"
        continue
    fi

    printf "[build] Compiling %-28s -> %s ... " "${bench}.c" "bin/${bench}"

    if gcc $CFLAGS -o "$out" "$src" $LDFLAGS 2>/dev/null; then
        echo "OK"
    else
        echo "FAILED"
        # 오류 내용이 보이도록 stderr를 노출하여 재실행
        gcc $CFLAGS -o "$out" "$src" $LDFLAGS || true
        FAILED=$((FAILED + 1))
    fi
done

echo ""
if [[ $FAILED -eq 0 ]]; then
    echo "[build] All benchmarks compiled successfully."
    echo "[build] Binaries in $BIN_DIR/"
    ls -lh "$BIN_DIR/"
    exit 0
else
    echo "[build] ERROR: $FAILED benchmark(s) failed to compile."
    exit 1
fi
