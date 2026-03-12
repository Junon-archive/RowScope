/*
 * Project: RowScope — DRAM Row Buffer Locality Analyzer
 * File:    benchmarks/working_set_sweep.c
 * Purpose: Working set size sweep benchmark.
 *          Iterates over 'steps' logarithmically-spaced array sizes between
 *          min-size and max-size.  For each size performs 'iterations' full
 *          sequential passes and writes a separate trace file.
 *          Demonstrates how row buffer locality behaves across different
 *          working set sizes relative to DRAM row capacity.
 *
 * CLI:     ./working_set_sweep [--min-size=N] [--max-size=N] [--steps=N] \
 *                              [--iterations=N] [--output-dir=DIR] [--no-trace]
 *
 * Output (stdout): one key=value block per step, prefixed with step index.
 *   step=0 benchmark=working_set array_size_bytes=524288 ...
 *   step=1 benchmark=working_set array_size_bytes=1048576 ...
 *   ...
 *
 * Trace files: {output-dir}/working_set_{size_human}_iter{iterations}.trace
 *
 * Author:  [Implementation Engineer]
 * Date:    2026-03-11
 */

#include "common.h"

/*
 * Run a single sequential-access pass for a given array size.
 * Writes addresses to *tw if tw->enabled.
 * Returns elapsed time in milliseconds.
 */
static double run_sequential_pass(long size_bytes, long iterations,
                                  TraceWriter *tw) {
    long num_elements = size_bytes / (long)sizeof(int);

    volatile int *arr = (volatile int *)alloc_aligned((size_t)size_bytes, 4096);
    for (long i = 0; i < num_elements; i++) {
        ((int *)arr)[i] = (int)i;
    }

    Timer t;
    timer_start(&t);

    for (long iter = 0; iter < iterations; iter++) {
        for (long i = 0; i < num_elements; i++) {
            volatile int val = arr[i];
            (void)val;
            trace_writer_write(tw, (uintptr_t)&arr[i]);
        }
    }

    timer_stop(&t);
    double elapsed = timer_elapsed_ms(&t);

    free((void *)arr);
    return elapsed;
}

int main(int argc, char *argv[]) {
    BenchmarkArgs args;
    parse_args(argc, argv, &args);

    if (args.min_size <= 0 || args.max_size <= 0 || args.min_size > args.max_size) {
        fprintf(stderr, "[working_set_sweep] ERROR: invalid min-size/max-size\n");
        return 1;
    }
    if (args.steps < 1) {
        fprintf(stderr, "[working_set_sweep] ERROR: --steps must be >= 1\n");
        return 1;
    }

    /* Build log-spaced size array */
    double log_min  = log((double)args.min_size);
    double log_max  = log((double)args.max_size);
    int    steps    = args.steps;

    long *sizes = (long *)malloc((size_t)steps * sizeof(long));
    if (sizes == NULL) {
        fprintf(stderr, "[working_set_sweep] ERROR: malloc failed\n");
        return 1;
    }

    for (int s = 0; s < steps; s++) {
        double frac = (steps == 1) ? 0.0 : (double)s / (double)(steps - 1);
        double log_size = log_min + frac * (log_max - log_min);
        long   raw_size = (long)exp(log_size);

        /* Round down to nearest multiple of sizeof(int) = 4 */
        raw_size = (raw_size / 4L) * 4L;
        if (raw_size < 4L) raw_size = 4L;
        sizes[s] = raw_size;
    }

    /* Run one benchmark step per size */
    for (int s = 0; s < steps; s++) {
        long  step_size      = sizes[s];
        long  num_elements   = step_size / (long)sizeof(int);
        long  total_accesses = num_elements * args.iterations;

        /* Build trace file path for this step */
        char  trace_path[512];
        char  size_human[32];
        format_size_human(step_size, size_human, sizeof(size_human));

        if (args.no_trace) {
            trace_path[0] = '\0';
        } else {
            snprintf(trace_path, sizeof(trace_path),
                     "%s/working_set_%s_iter%ld.trace",
                     args.output_dir, size_human, args.iterations);
        }

        /* Open trace writer for this step */
        TraceWriter tw;
        if (trace_writer_open(&tw, args.no_trace ? NULL : trace_path,
                              "working_set",
                              1,              /* stride = 1 (sequential) */
                              step_size,
                              total_accesses,
                              0,              /* seed N/A */
                              args.iterations) != 0) {
            /* Non-fatal: skip this step's trace but continue */
            fprintf(stderr, "[working_set_sweep] WARNING: could not open trace for step %d, skipping\n", s);
            tw.enabled = 0;
            tw.fp = NULL;
        }

        double elapsed_ms = run_sequential_pass(step_size, args.iterations, &tw);
        trace_writer_close(&tw);

        /* Print per-step results */
        printf("step=%d benchmark=working_set array_size_bytes=%ld array_size_human=%s "
               "iterations=%ld total_accesses=%ld exec_time_ms=%.2f trace_file=%s\n",
               s, step_size, size_human,
               args.iterations, total_accesses, elapsed_ms,
               args.no_trace ? "(disabled)" : trace_path);
    }

    free(sizes);
    return 0;
}
