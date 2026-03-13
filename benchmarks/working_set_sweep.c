/*
 * 프로젝트: RowScope — DRAM Row Buffer Locality Analyzer
 * 파일:    benchmarks/working_set_sweep.c
 * 목적: 워킹 셋 크기 스윕 벤치마크.
 *       min-size와 max-size 사이에서 로그 등간격으로 'steps'개의 배열 크기를
 *       순회한다. 각 크기에서 'iterations'번 전체 순차 패스를 수행하고
 *       별도의 트레이스 파일을 기록한다.
 *       DRAM row 용량 대비 다양한 워킹 셋 크기에서 row buffer locality가
 *       어떻게 변하는지를 관찰한다.
 *
 * CLI:     ./working_set_sweep [--min-size=N] [--max-size=N] [--steps=N] \
 *                              [--iterations=N] [--output-dir=DIR] [--no-trace]
 *
 * 출력 (stdout): 각 단계마다 key=value 블록 한 줄, step 인덱스 접두사 포함.
 *   step=0 benchmark=working_set array_size_bytes=524288 ...
 *   step=1 benchmark=working_set array_size_bytes=1048576 ...
 *   ...
 *
 * 트레이스 파일: {output-dir}/working_set_{size_human}_iter{iterations}.trace
 *
 * 작성자:  [Implementation Engineer]
 * 날짜:    2026-03-11
 */

#include "common.h"

/*
 * 주어진 배열 크기로 단일 순차 접근 패스를 실행한다.
 * tw->enabled가 참이면 *tw에 주소를 기록한다.
 * 경과 시간을 밀리초로 반환한다.
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

    /* 로그 등간격 크기 배열 생성 */
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

        /* sizeof(int) = 4의 배수로 내림 처리 */
        raw_size = (raw_size / 4L) * 4L;
        if (raw_size < 4L) raw_size = 4L;
        sizes[s] = raw_size;
    }

    /* 각 크기에 대해 벤치마크 단계 실행 */
    for (int s = 0; s < steps; s++) {
        long  step_size      = sizes[s];
        long  num_elements   = step_size / (long)sizeof(int);
        long  total_accesses = num_elements * args.iterations;

        /* 이 단계의 트레이스 파일 경로 생성 */
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

        /* 이 단계의 트레이스 기록기 열기 */
        TraceWriter tw;
        if (trace_writer_open(&tw, args.no_trace ? NULL : trace_path,
                              "working_set",
                              1,              /* 스트라이드 = 1 (순차 접근) */
                              step_size,
                              total_accesses,
                              0,              /* 시드 해당 없음 */
                              args.iterations) != 0) {
            /* 치명적 오류 아님: 이 단계의 트레이스를 건너뛰고 계속 */
            fprintf(stderr, "[working_set_sweep] WARNING: could not open trace for step %d, skipping\n", s);
            tw.enabled = 0;
            tw.fp = NULL;
        }

        double elapsed_ms = run_sequential_pass(step_size, args.iterations, &tw);
        trace_writer_close(&tw);

        /* 단계별 결과 출력 */
        printf("step=%d benchmark=working_set array_size_bytes=%ld array_size_human=%s "
               "iterations=%ld total_accesses=%ld exec_time_ms=%.2f trace_file=%s\n",
               s, step_size, size_human,
               args.iterations, total_accesses, elapsed_ms,
               args.no_trace ? "(disabled)" : trace_path);
    }

    free(sizes);
    return 0;
}
