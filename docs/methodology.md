# RowScope Methodology

**Version:** 1.0
**Date:** 2026-03-11

This document describes the analysis model underlying RowScope: how virtual addresses are mapped to DRAM coordinates, how the row buffer state machine classifies each access, what metrics are computed, and what simplifications are made. It is a companion to `docs/architecture.md` (system design) and `docs/interpretation_guide.md` (result interpretation).

---

## Table of Contents

1. [Analysis Model Design Philosophy](#1-analysis-model-design-philosophy)
2. [DRAM Address Mapping](#2-dram-address-mapping)
3. [Row Buffer State Machine](#3-row-buffer-state-machine)
4. [Trace Generation](#4-trace-generation)
5. [Analysis Metrics](#5-analysis-metrics)
6. [Experiment Design](#6-experiment-design)
7. [Limitations of the Model](#7-limitations-of-the-model)

---

## 1. Analysis Model Design Philosophy

RowScope uses a *user-space simulation model*: it replays address traces through a software-implemented DRAM model rather than measuring hardware performance counters. This choice is intentional and has specific tradeoffs.

**Why simulation rather than hardware profiling:**

- Hardware PMU counters for DRAM row hits (e.g., Intel `UNC_M_CAS_COUNT`) require privileged access, vary by processor generation, and are not available in all environments. A simulation-based approach is portable and reproducible.
- Simulation allows complete control over DRAM geometry parameters (row size, bank count, addressing scheme), enabling systematic exploration of how these parameters affect locality. Hardware experiments fix these parameters to whatever the installed DIMM provides.
- For comparative analysis — does pattern A have better locality than pattern B? — a consistent simulation model produces valid relative measurements even if absolute values differ from hardware.

**Where this model is not sufficient:**

- Absolute hit rate values may differ from hardware measurements because virtual addresses are used as proxies for physical addresses. The OS page allocator may scatter physical pages in ways that change actual bank and row assignments.
- CPU cache effects are not modeled. In production workloads, L1/L2/L3 caches absorb many accesses before they reach DRAM. RowScope counts all trace accesses as DRAM-level events.

The model is honest about these limitations (see Section 7). The comparative insights it produces — sequential vs. random, stride-1 vs. stride-1024, small vs. large working set — are robust to these simplifications because the same model is applied uniformly to all workloads.

---

## 2. DRAM Address Mapping

### 2.1 Model Parameters

| Parameter | Value Used | Description |
|-----------|-----------|-------------|
| Row size | 8192 bytes (8 KB) | Size of one DRAM row (row buffer capacity) |
| Number of banks | 8 | Number of independent DRAM banks |
| Addressing scheme | Bit-interleaved | How address bits are assigned to bank, row, column |

### 2.2 Bit-Interleaved Address Decomposition

In the bit-interleaved scheme, address bits are partitioned as follows:

```
Address bit layout:
  bits [12: 0]  → column offset  (13 bits, addresses within one 8KB row)
  bits [15:13]  → bank_id        (3 bits, selects one of 8 banks)
  bits [47:16]  → row_id         (32 bits, selects row within a bank)
```

Equivalently, with `R = log2(row_size) = log2(8192) = 13` and `B = log2(num_banks) = log2(8) = 3`:

```
col_offset = addr & (row_size - 1)          = addr & 0x1FFF
bank_id    = (addr >> R) & (num_banks - 1)  = (addr >> 13) & 0x7
row_id     = addr >> (R + B)                = addr >> 16
```

### 2.3 Worked Example

```
addr = 0x00020000 = 131072

col_offset = 131072 & 0x1FFF       = 0x0000  (column 0)
bank_id    = (131072 >> 13) & 0x7  = 16 & 7  = 0  (bank 0)
row_id     = 131072 >> 16          = 2        (row 2 in bank 0)

addr = 0x00002000 = 8192  (exactly one row beyond addr 0)

col_offset = 8192 & 0x1FFF        = 0         (column 0)
bank_id    = (8192 >> 13) & 0x7   = 1 & 7 = 1 (bank 1)
row_id     = 8192 >> 16           = 0          (row 0 in bank 1)
```

The second address is in bank 1, row 0 — the row of bank 1 that is interleaved with row 0 of bank 0. This interleaving means that consecutive 8KB blocks are spread across banks before repeating. A full cycle (one row across all 8 banks) spans 8 × 8192 = 65,536 bytes = 64 KB.

### 2.4 Why This Mapping Matters for Locality Analysis

The addressing scheme determines which access patterns cause row conflicts:

- **Sequential access** at small steps (4 bytes per element) advances the column offset within a row, staying in the same bank and row for 2048 elements before crossing a bank boundary. This produces near-perfect hit rate.
- **Stride-N access** at `N × 4` bytes per step crosses a bank (and potentially row) boundary more frequently as N grows. At N = 2048, every step is exactly 8192 bytes — a full row-sized jump — which advances bank_id by 1 and (after 8 steps) row_id by 1.
- **Random access** uniformly samples the address space, visiting different banks and rows with high probability on each successive access.

---

## 3. Row Buffer State Machine

### 3.1 State Definitions

Each bank independently maintains one of two states:

| State | Meaning |
|-------|---------|
| `EMPTY` | No row is currently open in this bank's row buffer |
| `OPEN(row_id)` | Row `row_id` is open and its contents are available at column latency |

Initially, all banks are in the `EMPTY` state.

### 3.2 State Transitions and Access Classification

On each memory access mapped to `(bank_id, row_id, col_offset)`:

```
State Transition Diagram:

        ┌──────────────────────────────────────────────────────┐
        │                                                      │
        ▼                                                      │
   ┌─────────┐   access (bank, row)     ┌──────────────────┐  │
   │  EMPTY  │ ──────────────────────▶  │  OPEN(row)       │  │
   └─────────┘  classify: MISS          └──────────────────┘  │
                                              │     │          │
                                 same row ────┘     │          │
                                 classify: HIT       │          │
                                                     │ different row
                                                     │ classify: CONFLICT
                                                     │
                                                     ▼
                                        ┌──────────────────┐
                                        │  OPEN(new_row)   │──┘
                                        └──────────────────┘
```

Formally:

| Current State | Access Target | Event Classified | New State |
|---------------|--------------|------------------|-----------|
| `EMPTY` | any row `r` | **Miss** | `OPEN(r)` |
| `OPEN(r)` | same row `r` | **Hit** | `OPEN(r)` (unchanged) |
| `OPEN(r)` | different row `r'` | **Conflict** | `OPEN(r')` |

### 3.3 Implementation Notes

The state machine is implemented in `analysis/row_buffer_model.py` as a `RowBufferModel` class:

- One state variable per bank: a list indexed by bank identifier
- The sentinel value `-1` represents the `EMPTY` state (distinguishable from any valid row identifier, which is non-negative)
- Counters for hits, misses, and conflicts are accumulated per-bank and globally
- Sets of unique accessed rows and banks are tracked per-bank

The state machine processes accesses sequentially. There is no parallelism, queue modeling, or prefetch prediction — each access is evaluated against the current state at the moment it arrives.

---

## 4. Trace Generation

### 4.1 C Benchmark Programs

Four C programs generate address traces (compiled with `-std=c99 -O2 -Wall -Wextra`):

| Program | Access Pattern | Key Parameters |
|---------|---------------|----------------|
| `sequential_access` | `arr[i]` for `i = 0, 1, 2, ..., N-1`, repeated | `--size`, `--iterations` |
| `random_access` | `arr[idx]` where `idx` is drawn from a seeded LCG RNG, uniform over `[0, N)` | `--size`, `--accesses`, `--seed` |
| `stride_access` | `arr[i % N]` where `i += stride` on each step | `--size`, `--stride`, `--accesses` |
| `working_set_sweep` | Sequential access at each of several array sizes in a log-spaced sweep | `--min-size`, `--max-size`, `--steps`, `--iterations` |

### 4.2 Trace File Format

Each trace file is a plain text file with the following structure:

```
# benchmark=sequential size=16777216 stride=1 accesses=4194304 element_size=4 seed=0 iterations=1
134217728
134217732
134217736
...
```

- Line 1: metadata header (comment, `#` prefix)
- Lines 2 onward: one decimal virtual address per line, as a `uintptr_t` value recorded at the time of the array access

Addresses are the actual virtual addresses from the running process, captured by dereferencing a volatile pointer in the C benchmark and writing the address (not the value) to the trace file.

### 4.3 Address Source

All addresses are virtual memory addresses allocated by `malloc` in the C benchmark. They are not physical addresses. The operating system's virtual-to-physical page mapping introduces an indirection that this model does not reverse. See Section 7 for the implications.

---

## 5. Analysis Metrics

### 5.1 Access Classification

For a trace of `N` total accesses, the analysis produces raw counts:

- `row_hit_count`: number of accesses classified as hits
- `row_miss_count`: number of accesses classified as misses
- `row_conflict_count`: number of accesses classified as conflicts

**Invariant:** `row_hit_count + row_miss_count + row_conflict_count = N` for all traces.

### 5.2 Rate Metrics

```
row_hit_rate      = row_hit_count      / N
row_miss_rate     = row_miss_count     / N
row_conflict_rate = row_conflict_count / N
```

All three rates sum to 1.0.

### 5.3 Locality Score

```
locality_score = row_hit_rate - row_conflict_rate
```

Range: `[-1.0, +1.0]`

- `+1.0`: all accesses are hits (perfect locality)
- `0.0`: hits and conflicts are balanced (mixed behavior)
- `-1.0`: all accesses are conflicts (worst-case pattern for open-page policy)

The locality score is a single-number summary that captures both the benefit (hits) and the cost (conflicts) in one value. It is especially useful for ranking patterns: sequential (+0.999) vs. random (−0.998) at 16MB makes the gap immediately apparent.

### 5.4 Derived Metrics

- `unique_rows_accessed`: the number of distinct row identifiers observed across all banks. Measures how much of the row address space a workload touches.
- `unique_banks_accessed`: the number of distinct banks accessed. For most workloads covering at least 64KB of address space, this is 8 (all banks).

---

## 6. Experiment Design

### 6.1 Parameter Choices

**Row size = 8192 bytes (8 KB)**

This matches the common DDR4 DRAM row size. With 4-byte integers, one row holds 2048 elements — a convenient round number for reasoning about stride thresholds.

**Number of banks = 8**

DDR4 DIMMs typically have 8 or 16 banks. Eight banks was chosen to keep the experiment tractable while capturing realistic bank-interleaving behavior. The stride analysis results are independent of bank count since the row-crossing threshold depends only on row size.

**Stride values: 1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024 (elements)**

These cover the range from near-sequential (stride=1) to near-random (stride=1024, corresponding to a 4KB step = half a row). The values double at each step, producing a clean logarithmic sweep that reveals the monotonic degradation of hit rate.

**Working set sizes: 512KB to 128MB (9 log-spaced steps)**

The lower bound (512KB) is below typical L2 cache capacity. The upper bound (128MB) is well above typical L3 cache capacity. In a hardware experiment, this sweep would reveal a hit rate discontinuity at the L3 boundary (where accesses begin reaching DRAM). In this simulation, all accesses are modeled as DRAM-level events, so the working set sweep instead validates that sequential access maintains consistent locality regardless of array size.

**Access count = 200,000 for random and stride benchmarks**

This is large enough to produce stable statistics (relative standard error < 0.1% for hit rates) while keeping trace files manageable (~3 MB each). Sequential benchmarks traverse the full array once, producing access counts proportional to array size.

### 6.2 Reproducibility

- All random benchmarks use a fixed seed (42) for the LCG random number generator. Results are deterministic across runs on the same platform.
- Sequential and stride benchmarks are deterministic by construction.
- Working set benchmarks use 3 iterations to increase access count and stabilize statistics for smaller arrays.

---

## 7. Limitations of the Model

The following limitations should be understood by anyone interpreting RowScope results.

**1. Virtual addresses, not physical addresses.**
RowScope records virtual memory addresses. The CPU and OS use page tables to map virtual pages to physical pages, and the DRAM controller uses physical addresses (along with a hardware address-to-bank mapping) to determine the actual bank and row. For `malloc`-allocated arrays, the physical pages backing a large array may not be contiguous — the OS can place them on any available physical pages. For workloads confined to one or a few virtual pages (small arrays), the virtual and physical layouts are likely consistent. For large arrays, the physical layout is unpredictable.

**Implication:** For comparative analysis between workload types (sequential vs. random), the relative conclusions are robust. Absolute hit rate values may not match hardware PMU measurements.

**2. No CPU cache modeling.**
Every address in the trace is treated as a DRAM access. In practice, L1/L2/L3 caches serve a large fraction of accesses (especially for hot working sets). RowScope measures the locality of the *access pattern* as presented to DRAM, not the effective DRAM hit rate after cache filtering. For array sizes within L3 capacity, most accesses are cache hits; the DRAM would see only cold misses and eviction-driven writebacks. RowScope does not model this.

**3. Open-page policy only.**
The state machine models an open-page policy (the current row stays open until a different row in the same bank is accessed). Real DRAM controllers may use closed-page policy (row is precharged after every access) or adaptive policy (switches based on observed traffic). Under closed-page policy, there are no row conflicts — only hits and misses — and the state machine analysis would need to be reinterpreted.

**4. Single-threaded, single-rank, no refresh.**
The model handles a single stream of accesses with no concurrency. Multi-threaded workloads with interleaved access streams from multiple cores would exhibit different bank contention behavior. DRAM refresh cycles (which precharge banks periodically to restore charge) are not modeled. The model assumes a single rank (no rank-level parallelism).

**5. Simplified random access model.**
The random benchmark uses the C standard library `rand()` function, an LCG with a 32-bit state. For access counts on the order of 200,000, this is statistically sound. For applications requiring higher-quality randomness, a better PRNG should be used.

**Summary:** RowScope is best interpreted as a *behavioral model* that accurately captures how access patterns interact with row buffer mechanics under idealized assumptions, rather than a *hardware emulator* that predicts exact DRAM performance on specific hardware.
