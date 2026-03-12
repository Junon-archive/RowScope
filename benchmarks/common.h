/*
 * Project: RowScope — DRAM Row Buffer Locality Analyzer
 * File:    benchmarks/common.h
 * Purpose: Shared header-only utilities: timing, trace writing, CLI arg parsing.
 *          All functions are static inline or static to avoid multiple-definition
 *          errors when included in multiple translation units.
 * Author:  [Implementation Engineer]
 * Date:    2026-03-11
 *
 * Trace file format (per architecture.md section 5):
 *   Line 1: # benchmark=X size=Y stride=Z accesses=N element_size=4 seed=S iterations=I
 *   Lines 2+: one decimal virtual address per line
 *
 * Naming convention for auto-generated trace paths:
 *   traces/{benchmark}_{size_human}_{param}.trace
 */

#ifndef ROWSCOPE_COMMON_H
#define ROWSCOPE_COMMON_H

/*
 * _POSIX_C_SOURCE 200112L is required before any system header to expose:
 *   - struct timespec and clock_gettime(CLOCK_MONOTONIC, ...)   [POSIX.1-2001]
 *   - posix_memalign()                                          [POSIX.1-2001]
 * Must be defined before the first #include.
 */
#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200112L
#endif

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <time.h>
#include <math.h>

/* =========================================================================
 * Timing
 * ========================================================================= */

typedef struct {
    struct timespec start;
    struct timespec end;
} Timer;

static inline void timer_start(Timer *t) {
    clock_gettime(CLOCK_MONOTONIC, &t->start);
}

static inline void timer_stop(Timer *t) {
    clock_gettime(CLOCK_MONOTONIC, &t->end);
}

/* Returns elapsed time in milliseconds. Call timer_stop() first. */
static inline double timer_elapsed_ms(const Timer *t) {
    double sec  = (double)(t->end.tv_sec  - t->start.tv_sec);
    double nsec = (double)(t->end.tv_nsec - t->start.tv_nsec);
    return (sec * 1000.0) + (nsec / 1.0e6);
}

/* Returns elapsed time in nanoseconds. Call timer_stop() first. */
static inline uint64_t timer_elapsed_ns(const Timer *t) {
    uint64_t sec  = (uint64_t)(t->end.tv_sec  - t->start.tv_sec);
    uint64_t nsec = (uint64_t)((int64_t)t->end.tv_nsec - (int64_t)t->start.tv_nsec);
    return sec * 1000000000ULL + nsec;
}

/* =========================================================================
 * Trace Writer
 * =========================================================================
 * The trace file starts with a single metadata header line:
 *   # benchmark=sequential size=16777216 stride=1 accesses=4194304 element_size=4 seed=0 iterations=3
 * Followed by one decimal virtual address per line (no spaces, no blanks).
 */

typedef struct {
    FILE   *fp;
    int     enabled;       /* 0 if --no-trace was passed */
    long    write_count;   /* number of address lines written so far */
} TraceWriter;

/*
 * Open trace file and write the metadata header line.
 * Returns 0 on success, -1 on error.
 * If path is NULL or empty, sets tw->enabled = 0 (no-op writes).
 */
static inline int trace_writer_open(TraceWriter *tw,
                                    const char  *path,
                                    const char  *benchmark,
                                    long         stride,
                                    long         array_size,
                                    long         accesses,
                                    long         seed,
                                    long         iterations)
{
    tw->write_count = 0;

    if (path == NULL || path[0] == '\0') {
        tw->fp      = NULL;
        tw->enabled = 0;
        return 0;
    }

    tw->fp = fopen(path, "w");
    if (tw->fp == NULL) {
        fprintf(stderr, "[trace_writer] ERROR: cannot open '%s' for writing\n", path);
        tw->enabled = 0;
        return -1;
    }

    tw->enabled = 1;

    /* Write metadata header (architecture.md §5.1) */
    fprintf(tw->fp,
            "# benchmark=%s size=%ld stride=%ld accesses=%ld element_size=4 seed=%ld iterations=%ld\n",
            benchmark, array_size, stride, accesses, seed, iterations);

    return 0;
}

/*
 * Write a single virtual address to the trace.
 * This is the hot path — kept minimal.
 */
static inline void trace_writer_write(TraceWriter *tw, uintptr_t address) {
    if (tw->enabled) {
        fprintf(tw->fp, "%lu\n", (unsigned long)address);
        tw->write_count++;
    }
}

/*
 * Flush and close the trace file.
 * Returns 0 on success, -1 on error.
 */
static inline int trace_writer_close(TraceWriter *tw) {
    if (tw->fp != NULL) {
        fflush(tw->fp);
        if (fclose(tw->fp) != 0) {
            fprintf(stderr, "[trace_writer] ERROR: fclose failed\n");
            tw->fp      = NULL;
            tw->enabled = 0;
            return -1;
        }
        tw->fp      = NULL;
        tw->enabled = 0;
    }
    return 0;
}

/* =========================================================================
 * CLI Argument Parsing
 * =========================================================================
 * Supports --key=value format.  Unknown keys are silently ignored.
 * Boolean flags (--no-trace) set the corresponding field to 1.
 */

typedef struct {
    long size;           /* array size in bytes          (default: 16MB)  */
    long iterations;     /* full traversal count          (default: 3)     */
    long stride;         /* stride in elements (int)      (default: 1)     */
    long accesses;       /* number of memory accesses     (default: 1000000) */
    long seed;           /* RNG seed                      (default: 42)    */
    char output[256];    /* trace output path             (default: "")    */
    int  no_trace;       /* 1 = disable trace writing     (default: 0)     */
    long min_size;       /* sweep: minimum array size     (default: 524288)*/
    long max_size;       /* sweep: maximum array size     (default: 134217728) */
    int  steps;          /* sweep: number of size steps   (default: 9)     */
    char output_dir[256];/* sweep: output directory       (default: "traces") */
} BenchmarkArgs;

static inline void print_usage(const char *prog_name) {
    fprintf(stderr,
        "Usage: %s [OPTIONS]\n"
        "\n"
        "Common options:\n"
        "  --size=N          Array size in bytes (default: 16777216 = 16MB)\n"
        "  --iterations=N    Number of full array traversals (default: 3)\n"
        "  --stride=N        Stride in elements (default: 1)\n"
        "  --accesses=N      Number of memory accesses (default: 1000000)\n"
        "  --seed=N          RNG seed for reproducibility (default: 42)\n"
        "  --output=PATH     Trace output file path (default: auto-generated)\n"
        "  --no-trace        Disable trace writing (timing only)\n"
        "\n"
        "Sweep options (working_set_sweep):\n"
        "  --min-size=N      Minimum working set size in bytes (default: 524288)\n"
        "  --max-size=N      Maximum working set size in bytes (default: 134217728)\n"
        "  --steps=N         Number of logarithmically-spaced sizes (default: 9)\n"
        "  --output-dir=DIR  Directory for sweep trace files (default: traces)\n",
        prog_name);
}

/*
 * Parse argc/argv into a BenchmarkArgs struct.
 * Applies defaults for all unspecified fields.
 * Unknown arguments are silently ignored.
 */
static inline void parse_args(int argc, char *argv[], BenchmarkArgs *args) {
    /* Apply defaults */
    args->size        = 16L * 1024L * 1024L;   /* 16 MB */
    args->iterations  = 3;
    args->stride      = 1;
    args->accesses    = 1000000L;
    args->seed        = 42;
    args->output[0]   = '\0';
    args->no_trace    = 0;
    args->min_size    = 524288L;               /* 512 KB */
    args->max_size    = 134217728L;            /* 128 MB */
    args->steps       = 9;
    strncpy(args->output_dir, "traces", sizeof(args->output_dir) - 1);
    args->output_dir[sizeof(args->output_dir) - 1] = '\0';

    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];

        /* Boolean flag: --no-trace */
        if (strcmp(arg, "--no-trace") == 0) {
            args->no_trace = 1;
            continue;
        }

        /* --help */
        if (strcmp(arg, "--help") == 0 || strcmp(arg, "-h") == 0) {
            print_usage(argv[0]);
            exit(0);
        }

        /* --key=value pairs */
        if (strncmp(arg, "--", 2) != 0) continue;
        const char *eq = strchr(arg, '=');
        if (eq == NULL) continue;

        /* Extract key (without leading --) and value */
        size_t key_len = (size_t)(eq - (arg + 2));
        char   key[64];
        if (key_len >= sizeof(key)) continue;
        strncpy(key, arg + 2, key_len);
        key[key_len] = '\0';
        const char *val = eq + 1;

        if (strcmp(key, "size") == 0) {
            args->size = atol(val);
        } else if (strcmp(key, "iterations") == 0) {
            args->iterations = atol(val);
        } else if (strcmp(key, "stride") == 0) {
            args->stride = atol(val);
        } else if (strcmp(key, "accesses") == 0) {
            args->accesses = atol(val);
        } else if (strcmp(key, "seed") == 0) {
            args->seed = atol(val);
        } else if (strcmp(key, "output") == 0) {
            strncpy(args->output, val, sizeof(args->output) - 1);
            args->output[sizeof(args->output) - 1] = '\0';
        } else if (strcmp(key, "min-size") == 0) {
            args->min_size = atol(val);
        } else if (strcmp(key, "max-size") == 0) {
            args->max_size = atol(val);
        } else if (strcmp(key, "steps") == 0) {
            args->steps = (int)atol(val);
        } else if (strcmp(key, "output-dir") == 0) {
            strncpy(args->output_dir, val, sizeof(args->output_dir) - 1);
            args->output_dir[sizeof(args->output_dir) - 1] = '\0';
        }
        /* Unknown keys are silently ignored */
    }
}

/* =========================================================================
 * Memory Helpers
 * ========================================================================= */

/*
 * Allocate size bytes aligned to alignment bytes using posix_memalign.
 * alignment must be a power of 2 and a multiple of sizeof(void*).
 * Returns pointer on success, exits on failure.
 */
static inline void *alloc_aligned(size_t size, size_t alignment) {
    void *ptr = NULL;
    int   rc  = posix_memalign(&ptr, alignment, size);
    if (rc != 0 || ptr == NULL) {
        fprintf(stderr, "[alloc_aligned] ERROR: posix_memalign(%zu, %zu) failed (rc=%d)\n",
                alignment, size, rc);
        exit(EXIT_FAILURE);
    }
    return ptr;
}

/* =========================================================================
 * Human-readable size formatting helper (for trace filenames / stdout)
 * ========================================================================= */

/*
 * Format a byte count as a human-readable string in the buf provided.
 * Examples: 1048576 -> "1MB", 524288 -> "512KB", 67108864 -> "64MB"
 */
static inline void format_size_human(long bytes, char *buf, size_t buf_len) {
    if (bytes >= (1L << 20) && (bytes % (1L << 20)) == 0) {
        snprintf(buf, buf_len, "%ldMB", bytes >> 20);
    } else if (bytes >= (1L << 10) && (bytes % (1L << 10)) == 0) {
        snprintf(buf, buf_len, "%ldKB", bytes >> 10);
    } else {
        snprintf(buf, buf_len, "%ldB", bytes);
    }
}

#endif /* ROWSCOPE_COMMON_H */
