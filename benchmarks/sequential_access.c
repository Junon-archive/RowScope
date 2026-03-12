/*
 * Project: RowScope — DRAM Row Buffer Locality Analyzer
 * File:    benchmarks/sequential_access.c
 * Purpose: Sequential array traversal benchmark.
 *          Reads a volatile int array from index 0..N-1 in order, repeated
 *          'iterations' times.  Records each access's virtual address in a
 *          trace file for downstream row buffer analysis.
 *
 * CLI:     ./sequential_access [--size=N] [--iterations=N] \
 *                              [--output=PATH] [--no-trace]
 *
 * Output (stdout, key=value format for Python parsing):
 *   benchmark=sequential
 *   array_size_bytes=16777216
 *   iterations=3
 *   total_accesses=12582912
 *   exec_time_ms=45.32
 *   trace_file=traces/sequential_16MB_stride1_seed0_iter3.trace
 *
 * Author:  [Implementation Engineer]
 * Date:    2026-03-11
 */

#include "common.h"

int main(int argc, char *argv[]) {
    BenchmarkArgs args;
    parse_args(argc, argv, &args);

    long num_elements = args.size / (long)sizeof(int);
    if (num_elements <= 0) {
        fprintf(stderr, "[sequential_access] ERROR: --size must be >= %zu\n", sizeof(int));
        return 1;
    }

    /* Build trace output path if not provided */
    char trace_path[512];
    if (args.no_trace) {
        trace_path[0] = '\0';
    } else if (args.output[0] != '\0') {
        strncpy(trace_path, args.output, sizeof(trace_path) - 1);
        trace_path[sizeof(trace_path) - 1] = '\0';
    } else {
        char size_human[32];
        format_size_human(args.size, size_human, sizeof(size_human));
        snprintf(trace_path, sizeof(trace_path),
                 "traces/sequential_%s_stride1_seed0_iter%ld.trace",
                 size_human, args.iterations);
    }

    long total_accesses = num_elements * args.iterations;

    /* Open trace writer */
    TraceWriter tw;
    if (trace_writer_open(&tw, args.no_trace ? NULL : trace_path,
                          "sequential",
                          1,                  /* stride (elements) */
                          args.size,
                          total_accesses,
                          0,                  /* seed (N/A) */
                          args.iterations) != 0) {
        return 1;
    }

    /* Allocate array (page-aligned for realistic DRAM mapping) */
    volatile int *arr = (volatile int *)alloc_aligned((size_t)args.size, 4096);

    /* Initialize array to avoid page-fault noise during timed region */
    for (long i = 0; i < num_elements; i++) {
        ((int *)arr)[i] = (int)i;
    }

    /* Timed benchmark loop */
    Timer t;
    timer_start(&t);

    for (long iter = 0; iter < args.iterations; iter++) {
        for (long i = 0; i < num_elements; i++) {
            volatile int val = arr[i];  /* prevent optimization */
            (void)val;
            trace_writer_write(&tw, (uintptr_t)&arr[i]);
        }
    }

    timer_stop(&t);
    double elapsed_ms = timer_elapsed_ms(&t);

    trace_writer_close(&tw);
    free((void *)arr);

    /* Print results in key=value format (architecture.md §8) */
    printf("benchmark=sequential\n");
    printf("array_size_bytes=%ld\n",   args.size);
    printf("iterations=%ld\n",         args.iterations);
    printf("total_accesses=%ld\n",     total_accesses);
    printf("exec_time_ms=%.2f\n",      elapsed_ms);
    printf("trace_file=%s\n",          args.no_trace ? "(disabled)" : trace_path);

    return 0;
}
