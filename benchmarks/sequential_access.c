/*
 * 프로젝트: RowScope — DRAM Row Buffer Locality Analyzer
 * 파일:    benchmarks/sequential_access.c
 * 목적: 순차 배열 순회 벤치마크.
 *       volatile int 배열을 인덱스 0부터 N-1까지 순서대로 읽으며,
 *       'iterations'번 반복한다. 각 접근의 가상 주소를 트레이스 파일에
 *       기록하여 하위 row buffer 분석에 사용한다.
 *
 * CLI:     ./sequential_access [--size=N] [--iterations=N] \
 *                              [--output=PATH] [--no-trace]
 *
 * 출력 (stdout, key=value 형식, Python 파싱용):
 *   benchmark=sequential
 *   array_size_bytes=16777216
 *   iterations=3
 *   total_accesses=12582912
 *   exec_time_ms=45.32
 *   trace_file=traces/sequential_16MB_stride1_seed0_iter3.trace
 *
 * 작성자:  [Implementation Engineer]
 * 날짜:    2026-03-11
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

    /* 트레이스 출력 경로가 지정되지 않은 경우 자동으로 생성 */
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

    /* 트레이스 기록기 열기 */
    TraceWriter tw;
    if (trace_writer_open(&tw, args.no_trace ? NULL : trace_path,
                          "sequential",
                          1,                  /* 스트라이드 (요소 수) */
                          args.size,
                          total_accesses,
                          0,                  /* 시드 (해당 없음) */
                          args.iterations) != 0) {
        return 1;
    }

    /* 배열 할당 (현실적인 DRAM 매핑을 위해 페이지 정렬) */
    volatile int *arr = (volatile int *)alloc_aligned((size_t)args.size, 4096);

    /* 타이밍 측정 구간의 page-fault 노이즈 방지를 위해 미리 초기화 */
    for (long i = 0; i < num_elements; i++) {
        ((int *)arr)[i] = (int)i;
    }

    /* 타이밍 측정 구간 — 벤치마크 루프 */
    Timer t;
    timer_start(&t);

    for (long iter = 0; iter < args.iterations; iter++) {
        for (long i = 0; i < num_elements; i++) {
            volatile int val = arr[i];  /* 컴파일러 최적화 방지 */
            (void)val;
            trace_writer_write(&tw, (uintptr_t)&arr[i]);
        }
    }

    timer_stop(&t);
    double elapsed_ms = timer_elapsed_ms(&t);

    trace_writer_close(&tw);
    free((void *)arr);

    /* 결과를 key=value 형식으로 출력 (architecture.md §8) */
    printf("benchmark=sequential\n");
    printf("array_size_bytes=%ld\n",   args.size);
    printf("iterations=%ld\n",         args.iterations);
    printf("total_accesses=%ld\n",     total_accesses);
    printf("exec_time_ms=%.2f\n",      elapsed_ms);
    printf("trace_file=%s\n",          args.no_trace ? "(disabled)" : trace_path);

    return 0;
}
