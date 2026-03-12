/*
 * Project: RowScope — DRAM Row Buffer Locality Analyzer
 * File:    benchmarks/random_access.c
 * Purpose: Random array access benchmark.
 *          Performs 'accesses' uniformly-random reads across an int array.
 *          Uses srand(seed) + rand() for reproducible index generation.
 *          Records each access's virtual address in a trace file.
 *
 * CLI:     ./random_access [--size=N] [--accesses=N] [--seed=N] \
 *                          [--output=PATH] [--no-trace]
 *
 * Output (stdout, key=value format):
 *   benchmark=random
 *   array_size_bytes=16777216
 *   accesses=100000
 *   seed=42
 *   exec_time_ms=12.47
 *   trace_file=traces/random_16MB_100000acc_seed42.trace
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
        fprintf(stderr, "[random_access] ERROR: --size must be >= %zu\n", sizeof(int));
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
                 "traces/random_%s_%ldacc_seed%ld.trace",
                 size_human, args.accesses, args.seed);
    }

    /* Open trace writer */
    TraceWriter tw;
    if (trace_writer_open(&tw, args.no_trace ? NULL : trace_path,
                          "random",
                          0,                  /* stride = 0 (random, N/A) */
                          args.size,
                          args.accesses,
                          args.seed,
                          1                   /* iterations = 1 for random */
                          ) != 0) {
        return 1;
    }

    /* Allocate and initialize array */
    volatile int *arr = (volatile int *)alloc_aligned((size_t)args.size, 4096);
    for (long i = 0; i < num_elements; i++) {
        ((int *)arr)[i] = (int)i;
    }

    /* Seed the PRNG for reproducibility */
    srand((unsigned int)args.seed);

    /* Timed benchmark loop */
    Timer t;
    timer_start(&t);

    for (long a = 0; a < args.accesses; a++) {
        /* Generate random index in [0, num_elements) */
        long idx = (long)(rand()) % num_elements;
        if (idx < 0) idx = -idx;  /* guard against implementation-defined negatives */

        volatile int val = arr[idx];
        (void)val;
        trace_writer_write(&tw, (uintptr_t)&arr[idx]);
    }

    timer_stop(&t);
    double elapsed_ms = timer_elapsed_ms(&t);

    trace_writer_close(&tw);
    free((void *)arr);

    /* Print results */
    printf("benchmark=random\n");
    printf("array_size_bytes=%ld\n",  args.size);
    printf("accesses=%ld\n",          args.accesses);
    printf("seed=%ld\n",              args.seed);
    printf("exec_time_ms=%.2f\n",     elapsed_ms);
    printf("trace_file=%s\n",         args.no_trace ? "(disabled)" : trace_path);

    return 0;
}
