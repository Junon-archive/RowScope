/*
 * 프로젝트: RowScope — DRAM Row Buffer Locality Analyzer
 * 파일:    benchmarks/common.h
 * 목적: 공통 헤더 전용 유틸리티: 타이밍, 트레이스 기록, CLI 인수 파싱.
 *       모든 함수는 static inline 또는 static으로 선언되어,
 *       여러 번역 단위에 include되어도 다중 정의 오류가 발생하지 않는다.
 * 작성자:  [Implementation Engineer]
 * 날짜:    2026-03-11
 *
 * 트레이스 파일 형식 (architecture.md §5 참고):
 *   1행: # benchmark=X size=Y stride=Z accesses=N element_size=4 seed=S iterations=I
 *   2행~: 십진수 가상 주소 (한 줄에 하나)
 *
 * 자동 생성 트레이스 파일명 규칙:
 *   traces/{benchmark}_{size_human}_{param}.trace
 */

#ifndef ROWSCOPE_COMMON_H
#define ROWSCOPE_COMMON_H

/*
 * _POSIX_C_SOURCE 200112L은 어떤 시스템 헤더보다 먼저 정의해야
 * 아래 기능들을 사용할 수 있다:
 *   - struct timespec 및 clock_gettime(CLOCK_MONOTONIC, ...)   [POSIX.1-2001]
 *   - posix_memalign()                                          [POSIX.1-2001]
 * 반드시 첫 번째 #include 이전에 정의해야 한다.
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
 * 타이밍 (Timing)
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

/* 경과 시간을 밀리초로 반환한다. timer_stop() 호출 후 사용할 것. */
static inline double timer_elapsed_ms(const Timer *t) {
    double sec  = (double)(t->end.tv_sec  - t->start.tv_sec);
    double nsec = (double)(t->end.tv_nsec - t->start.tv_nsec);
    return (sec * 1000.0) + (nsec / 1.0e6);
}

/* 경과 시간을 나노초로 반환한다. timer_stop() 호출 후 사용할 것. */
static inline uint64_t timer_elapsed_ns(const Timer *t) {
    uint64_t sec  = (uint64_t)(t->end.tv_sec  - t->start.tv_sec);
    uint64_t nsec = (uint64_t)((int64_t)t->end.tv_nsec - (int64_t)t->start.tv_nsec);
    return sec * 1000000000ULL + nsec;
}

/* =========================================================================
 * 트레이스 기록기 (Trace Writer)
 * =========================================================================
 * 트레이스 파일은 메타데이터 헤더 한 줄로 시작한다:
 *   # benchmark=sequential size=16777216 stride=1 accesses=4194304 element_size=4 seed=0 iterations=3
 * 이후 가상 주소를 십진수로 한 줄씩 기록한다 (공백이나 빈 줄 없음).
 */

typedef struct {
    FILE   *fp;
    int     enabled;       /* 0이면 트레이스 기록 비활성화 (--no-trace 옵션) */
    long    write_count;   /* 지금까지 기록한 주소 줄 수 */
} TraceWriter;

/*
 * 트레이스 파일을 열고 메타데이터 헤더 줄을 기록한다.
 * 성공 시 0, 오류 시 -1을 반환한다.
 * path가 NULL이거나 빈 문자열이면 tw->enabled = 0으로 설정하고 기록을 비활성화한다.
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

    /* 메타데이터 헤더 기록 (architecture.md §5.1) */
    fprintf(tw->fp,
            "# benchmark=%s size=%ld stride=%ld accesses=%ld element_size=4 seed=%ld iterations=%ld\n",
            benchmark, array_size, stride, accesses, seed, iterations);

    return 0;
}

/*
 * 트레이스에 가상 주소 하나를 기록한다.
 * 핫 패스(hot path)이므로 최소한의 코드만 실행한다.
 */
static inline void trace_writer_write(TraceWriter *tw, uintptr_t address) {
    if (tw->enabled) {
        fprintf(tw->fp, "%lu\n", (unsigned long)address);
        tw->write_count++;
    }
}

/*
 * 트레이스 파일을 플러시하고 닫는다.
 * 성공 시 0, 오류 시 -1을 반환한다.
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
 * CLI 인수 파싱 (CLI Argument Parsing)
 * =========================================================================
 * --key=value 형식을 지원한다. 알 수 없는 키는 무시한다.
 * 불리언 플래그 (--no-trace)는 해당 필드를 1로 설정한다.
 */

typedef struct {
    long size;           /* 배열 크기 (바이트)            (기본값: 16MB)   */
    long iterations;     /* 전체 순회 횟수                (기본값: 3)      */
    long stride;         /* 스트라이드 (int 요소 단위)     (기본값: 1)      */
    long accesses;       /* 메모리 접근 횟수              (기본값: 1000000) */
    long seed;           /* 난수 시드                     (기본값: 42)     */
    char output[256];    /* 트레이스 출력 경로             (기본값: "")     */
    int  no_trace;       /* 1이면 트레이스 기록 비활성화   (기본값: 0)      */
    long min_size;       /* 스윕 최소 배열 크기           (기본값: 524288) */
    long max_size;       /* 스윕 최대 배열 크기           (기본값: 134217728) */
    int  steps;          /* 스윕 크기 단계 수             (기본값: 9)      */
    char output_dir[256];/* 스윕 출력 디렉터리            (기본값: "traces") */
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
 * argc/argv를 파싱하여 BenchmarkArgs 구조체를 채운다.
 * 미지정 필드에는 기본값을 적용한다.
 * 알 수 없는 인수는 무시한다.
 */
static inline void parse_args(int argc, char *argv[], BenchmarkArgs *args) {
    /* 기본값 설정 */
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

        /* 불리언 플래그: --no-trace */
        if (strcmp(arg, "--no-trace") == 0) {
            args->no_trace = 1;
            continue;
        }

        /* --help */
        if (strcmp(arg, "--help") == 0 || strcmp(arg, "-h") == 0) {
            print_usage(argv[0]);
            exit(0);
        }

        /* --key=value 쌍 처리 */
        if (strncmp(arg, "--", 2) != 0) continue;
        const char *eq = strchr(arg, '=');
        if (eq == NULL) continue;

        /* '--' 이후의 키와 등호 뒤의 값을 추출 */
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
        /* 알 수 없는 키는 무시 */
    }
}

/* =========================================================================
 * 메모리 관련 유틸리티 (Memory Helpers)
 * ========================================================================= */

/*
 * posix_memalign을 사용해 alignment 바이트 경계에 정렬된 size 바이트를 할당한다.
 * alignment는 2의 거듭제곱이어야 하며 sizeof(void*)의 배수여야 한다.
 * 성공 시 포인터를 반환하고, 실패 시 프로세스를 종료한다.
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
 * 사람이 읽기 쉬운 크기 포매팅 (트레이스 파일명 / stdout 출력용)
 * ========================================================================= */

/*
 * 바이트 수를 사람이 읽기 쉬운 문자열로 변환하여 buf에 저장한다.
 * 예시: 1048576 -> "1MB", 524288 -> "512KB", 67108864 -> "64MB"
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
