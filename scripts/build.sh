#!/usr/bin/env bash
# =============================================================================
# Project: RowScope — DRAM Row Buffer Locality Analyzer
# File:    scripts/build.sh
# Purpose: Compile all C benchmark programs into bin/.
#          Exits with non-zero status if any compilation fails.
#          Prints per-file success/failure to stdout.
# Usage:   ./scripts/build.sh
# Author:  [Implementation Engineer]
# Date:    2026-03-11
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
BENCH_DIR="$ROOT_DIR/benchmarks"
BIN_DIR="$ROOT_DIR/bin"

# Architecture.md §8.1 specifies c11 and -lm; using c99 is also conformant for
# our feature set. We compile with -std=c99 -lm to support math.h (log/exp in
# working_set_sweep.c) while staying compatible with the gcc version on this host.
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
        # Re-run with stderr visible so the engineer sees the error
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
