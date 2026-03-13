/*
 * 프로젝트: RowScope — DRAM Row Buffer Locality Analyzer
 * 파일:    benchmarks/stride_access.c
 * 목적: 설정 가능한 스트라이드 배열 접근 벤치마크.
 *       index = (index + stride) % num_elements 방식으로
 *       'accesses'번 접근하며 랩어라운드를 지원한다.
 *       stride=1이면 sequential_access와 동일한 주소 시퀀스를 생성한다.
 *
 * CLI:     ./stride_access [--size=N] [--stride=N] [--accesses=N] \
 *                          [--output=PATH] [--no-trace]
 *
 * 출력 (stdout, key=value 형식):
 *   benchmark=stride
 *   array_size_bytes=16777216
 *   stride_elements=64
 *   stride_bytes=256
 *   accesses=100000
 *   exec_time_ms=8.91
 *   trace_file=traces/stride_16MB_stride64_100000acc.trace
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
        fprintf(stderr, "[stride_access] ERROR: --size must be >= %zu\n", sizeof(int));
        return 1;
    }
    if (args.stride <= 0) {
        fprintf(stderr, "[stride_access] ERROR: --stride must be >= 1\n");
        return 1;
    }

    long stride_bytes = args.stride * (long)sizeof(int);

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
                 "traces/stride_%s_stride%ld_%ldacc.trace",
                 size_human, args.stride, args.accesses);
    }

    /* 트레이스 기록기 열기 */
    TraceWriter tw;
    if (trace_writer_open(&tw, args.no_trace ? NULL : trace_path,
                          "stride",
                          args.stride,
                          args.size,
                          args.accesses,
                          0,   /* 시드 해당 없음 */
                          1    /* 스트라이드 접근은 반복 횟수 = 1 */
                          ) != 0) {
        return 1;
    }

    /* 배열 할당 및 초기화 */
    volatile int *arr = (volatile int *)alloc_aligned((size_t)args.size, 4096);
    for (long i = 0; i < num_elements; i++) {
        ((int *)arr)[i] = (int)i;
    }

    /* 타이밍 측정 구간 — 랩어라운드를 포함한 스트라이드 루프 */
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

    /* 결과 출력 */
    printf("benchmark=stride\n");
    printf("array_size_bytes=%ld\n",  args.size);
    printf("stride_elements=%ld\n",   args.stride);
    printf("stride_bytes=%ld\n",      stride_bytes);
    printf("accesses=%ld\n",          args.accesses);
    printf("exec_time_ms=%.2f\n",     elapsed_ms);
    printf("trace_file=%s\n",         args.no_trace ? "(disabled)" : trace_path);

    return 0;
}
