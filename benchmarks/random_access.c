/*
 * 프로젝트: RowScope — DRAM Row Buffer Locality Analyzer
 * 파일:    benchmarks/random_access.c
 * 목적: 무작위 배열 접근 벤치마크.
 *       int 배열에서 'accesses'번 균일 무작위 읽기를 수행한다.
 *       재현 가능한 인덱스 생성을 위해 srand(seed) + rand()를 사용한다.
 *       각 접근의 가상 주소를 트레이스 파일에 기록한다.
 *
 * CLI:     ./random_access [--size=N] [--accesses=N] [--seed=N] \
 *                          [--output=PATH] [--no-trace]
 *
 * 출력 (stdout, key=value 형식):
 *   benchmark=random
 *   array_size_bytes=16777216
 *   accesses=100000
 *   seed=42
 *   exec_time_ms=12.47
 *   trace_file=traces/random_16MB_100000acc_seed42.trace
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
        fprintf(stderr, "[random_access] ERROR: --size must be >= %zu\n", sizeof(int));
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
                 "traces/random_%s_%ldacc_seed%ld.trace",
                 size_human, args.accesses, args.seed);
    }

    /* 트레이스 기록기 열기 */
    TraceWriter tw;
    if (trace_writer_open(&tw, args.no_trace ? NULL : trace_path,
                          "random",
                          0,                  /* 스트라이드 = 0 (무작위, 해당 없음) */
                          args.size,
                          args.accesses,
                          args.seed,
                          1                   /* 무작위 접근은 반복 횟수 = 1 */
                          ) != 0) {
        return 1;
    }

    /* 배열 할당 및 초기화 */
    volatile int *arr = (volatile int *)alloc_aligned((size_t)args.size, 4096);
    for (long i = 0; i < num_elements; i++) {
        ((int *)arr)[i] = (int)i;
    }

    /* 재현성을 위해 PRNG 시드 설정 */
    srand((unsigned int)args.seed);

    /* 타이밍 측정 구간 — 벤치마크 루프 */
    Timer t;
    timer_start(&t);

    for (long a = 0; a < args.accesses; a++) {
        /* [0, num_elements) 범위의 무작위 인덱스 생성 */
        long idx = (long)(rand()) % num_elements;
        if (idx < 0) idx = -idx;  /* 구현 정의 음수 결과에 대한 방어 처리 */

        volatile int val = arr[idx];
        (void)val;
        trace_writer_write(&tw, (uintptr_t)&arr[idx]);
    }

    timer_stop(&t);
    double elapsed_ms = timer_elapsed_ms(&t);

    trace_writer_close(&tw);
    free((void *)arr);

    /* 결과 출력 */
    printf("benchmark=random\n");
    printf("array_size_bytes=%ld\n",  args.size);
    printf("accesses=%ld\n",          args.accesses);
    printf("seed=%ld\n",              args.seed);
    printf("exec_time_ms=%.2f\n",     elapsed_ms);
    printf("trace_file=%s\n",         args.no_trace ? "(disabled)" : trace_path);

    return 0;
}
