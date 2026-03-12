/*
 * Project: RowScope — DRAM Row Buffer Locality Analyzer
 * File:    benchmarks/stride_access.c
 * Purpose: Configurable-stride array access benchmark.
 *          Accesses array element at index = (index + stride) % num_elements
 *          for 'accesses' iterations, with wrap-around.
 *          stride=1 produces identical address sequence to sequential_access.
 *
 * CLI:     ./stride_access [--size=N] [--stride=N] [--accesses=N] \
 *                          [--output=PATH] [--no-trace]
 *
 * Output (stdout, key=value format):
 *   benchmark=stride
 *   array_size_bytes=16777216
 *   stride_elements=64
 *   stride_bytes=256
 *   accesses=100000
 *   exec_time_ms=8.91
 *   trace_file=traces/stride_16MB_stride64_100000acc.trace
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
        fprintf(stderr, "[stride_access] ERROR: --size must be >= %zu\n", sizeof(int));
        return 1;
    }
    if (args.stride <= 0) {
        fprintf(stderr, "[stride_access] ERROR: --stride must be >= 1\n");
        return 1;
    }

    long stride_bytes = args.stride * (long)sizeof(int);

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
                 "traces/stride_%s_stride%ld_%ldacc.trace",
                 size_human, args.stride, args.accesses);
    }

    /* Open trace writer */
    TraceWriter tw;
    if (trace_writer_open(&tw, args.no_trace ? NULL : trace_path,
                          "stride",
                          args.stride,
                          args.size,
                          args.accesses,
                          0,   /* seed N/A */
                          1    /* iterations = 1 for stride */
                          ) != 0) {
        return 1;
    }

    /* Allocate and initialize array */
    volatile int *arr = (volatile int *)alloc_aligned((size_t)args.size, 4096);
    for (long i = 0; i < num_elements; i++) {
        ((int *)arr)[i] = (int)i;
    }

    /* Timed benchmark loop — stride with wrap-around */
    Timer t;
    long index = 0;
    timer_start(&t);

    for (long a = 0; a < args.accesses; a++) {
        volatile int val = arr[index];
        (void)val;
        trace_writer_write(&tw, (uintptr_t)&arr[index]);
        index = (index + args.stride) % num_elements;
    }

    timer_stop(&t);
    double elapsed_ms = timer_elapsed_ms(&t);

    trace_writer_close(&tw);
    free((void *)arr);

    /* Print results */
    printf("benchmark=stride\n");
    printf("array_size_bytes=%ld\n",  args.size);
    printf("stride_elements=%ld\n",   args.stride);
    printf("stride_bytes=%ld\n",      stride_bytes);
    printf("accesses=%ld\n",          args.accesses);
    printf("exec_time_ms=%.2f\n",     elapsed_ms);
    printf("trace_file=%s\n",         args.no_trace ? "(disabled)" : trace_path);

    return 0;
}
