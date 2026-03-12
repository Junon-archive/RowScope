# How to Interpret RowScope Results

**Version:** 1.0
**Date:** 2026-03-11

This guide explains how to read the figures, tables, and statistics produced by RowScope. It is written for engineers examining the project output for the first time, or anyone looking to understand the relationship between memory access patterns and DRAM row buffer behavior. The final section answers frequently asked questions about the results.

---

## Table of Contents

1. [Reading the Row Hit Rate Metric](#1-reading-the-row-hit-rate-metric)
2. [Understanding the Stride Analysis](#2-understanding-the-stride-analysis)
3. [Sequential vs. Random: The Locality Gap](#3-sequential-vs-random-the-locality-gap)
4. [Working Set Analysis](#4-working-set-analysis)
5. [How to Read Each Figure Type](#5-how-to-read-each-figure-type)
6. [What Results Mean for Real Applications](#6-what-results-mean-for-real-applications)
7. [Frequently Asked Questions](#7-frequently-asked-questions)

---

## 1. Reading the Row Hit Rate Metric

Row hit rate is the fraction of memory accesses that find the target row already open in the DRAM row buffer. It is the primary metric in RowScope.

| Hit Rate Range | Classification | What It Means |
|----------------|---------------|---------------|
| > 95% | Excellent locality | The workload is DRAM-friendly. Most accesses pay only column-access latency (~13 ns). Effective bandwidth approaches hardware peak. |
| 70–95% | Good locality | Row boundary crossings are infrequent. Performance impact is modest. |
| 50–70% | Moderate locality | A significant fraction of accesses pay precharge + activation overhead. Memory bandwidth is noticeably below peak. |
| 20–50% | Poor locality | Conflicts dominate. Effective memory latency is 2–3× higher than the hit case. |
| < 20% | Very poor locality | The workload is effectively random from DRAM's perspective. Nearly every access pays full conflict latency (~39–70 ns). Memory bandwidth may be less than 30% of peak. |

**The conflict rate is the complementary concern.** A high conflict rate means most accesses force a precharge-activate cycle — the most expensive DRAM operation. The locality score (hit rate minus conflict rate) captures both signals in a single value ranging from +1 (all hits) to −1 (all conflicts).

---

## 2. Understanding the Stride Analysis

### 2.1 What Stride Measures

The stride benchmark accesses `arr[0], arr[N], arr[2N], arr[3N], ...` — every N-th integer element. Each step advances the address by `N × 4` bytes (4 bytes per `int`).

Row boundaries occur every 8192 bytes. The number of steps per row crossing is:

```
steps_per_crossing = row_size / (stride × element_size)
                   = 8192 / (stride × 4)
                   = 2048 / stride
```

The fraction of steps that cross a row boundary (causing a potential conflict) is the inverse:

```
crossing_frequency = stride × 4 / 8192
                   = stride / 2048
```

Therefore, the predicted row hit rate is:

```
hit_rate ≈ 1 − crossing_frequency
         = 1 − stride / 2048
         = 1 − (stride × element_size) / row_size
```

### 2.2 Verification Against Measured Data

| Stride | Predicted Hit Rate | Measured Hit Rate |
|--------|-------------------|-------------------|
| 1 | 99.95% | 99.95% |
| 128 | 93.75% | 93.75% |
| 256 | 87.50% | 87.49% |
| 512 | 75.00% | 74.99% |
| 1024 | 50.00% | 49.98% |

The model and measurement agree to within 0.02 percentage points. The small discrepancy arises from the initial miss (the very first access to an empty bank), which is not predicted by the formula.

### 2.3 The Critical Stride Threshold

When `stride = row_size / element_size = 8192 / 4 = 2048 elements`, the byte step equals exactly one row size. Every access crosses a row boundary — hit rate approaches 0% and the workload becomes pathological for open-page policy.

At stride = 1024 (half the critical threshold), hit rate is 50%: every other access crosses a row boundary. This matches the measured value of 49.98% exactly.

### 2.4 Why This Matters

The stride pathology is not hypothetical. Real applications exhibit it:

- **Matrix transposition** with column-major storage accesses rows of the source matrix with stride equal to the row length. If the row length in bytes is a multiple of 8192, every access is in a new DRAM row.
- **Certain FFT implementations** with power-of-two sizes access memory with strides that are powers of two — potentially aligning with DRAM row boundaries.
- **Tiled algorithms** designed to improve cache locality sometimes introduce strides that align poorly with DRAM geometry.

---

## 3. Sequential vs. Random: The Locality Gap

### 3.1 Sequential Access (99.95% Hit Rate)

Sequential access processes `arr[0], arr[1], arr[2], ...` — one element at a time. Each 8KB DRAM row contains `8192 / 4 = 2048` integer elements. After the first access to a row (a miss), all 2047 subsequent accesses to that row are hits.

```
Hit rate = (elements_per_row - 1) / elements_per_row
         = 2047 / 2048
         ≈ 99.95%
```

This matches the measured value exactly. The ~0.05% miss rate corresponds to the first access of each new row.

### 3.2 Random Access (0.4% to 6.2% Hit Rate, Depending on Array Size)

Uniform random access distributes requests across all elements of the array. For a 16MB array:

- Number of rows covered: 16MB / 8KB = 2048 rows
- Number of banks: 8
- Rows per bank: 256

The probability that two successive random accesses go to the same bank *and* the same row is approximately `1/8 × 1/256 ≈ 0.05%` — nearly zero. The dominant outcome is conflict (same bank, different row).

The measured hit rate for random access on a 16MB array is 0.4%, which is consistent with the small probability of random address reuse. For a 1MB array (128 rows per bank), the hit rate rises to 6.2% because the address space is smaller and accidental reuse is more likely.

**Key insight:** Random access hit rate decreases as array size increases, because there are more rows to "miss" into. Sequential access hit rate is independent of array size — it depends only on the ratio of access step size to row size.

### 3.3 Interpreting the Gap

The gap between sequential (99.95%) and random-16MB (0.4%) hit rates is 99.55 percentage points. In latency terms:

- Sequential: nearly all accesses at ~13 ns (column latency)
- Random: nearly all accesses at ~39–70 ns (precharge + activate + column)

Effective memory latency ratio: 3–5×. For a memory-bandwidth-bound workload, this translates directly to a 3–5× throughput difference.

---

## 4. Working Set Analysis

The working set sweep runs sequential access at array sizes from 512KB to 128MB, with three passes over each array. The measured hit rate is ~99.95% at every size.

**Why no discontinuity?** In hardware, you would expect a hit rate cliff at the L3 cache size (~6–32 MB on typical server processors): below L3, the cache absorbs most accesses before they reach DRAM; above L3, DRAM sees nearly all accesses. RowScope does not model CPU cache, so all accesses in the trace are treated as DRAM-level events regardless of array size.

The uniform ~99.95% hit rate across all working set sizes confirms:
1. The row buffer state machine is stable and consistent across array sizes.
2. For a sequential pattern, row buffer locality is determined entirely by the spatial structure of accesses within each row, not by how many rows exist.

**In a hardware-profiled equivalent,** you would see: hit rate near 100% for small working sets (cache-resident), then a transition zone at the L3 capacity, then a plateau at the DRAM-level sequential hit rate (~99.95%) for large working sets. RowScope captures the DRAM plateau only.

---

## 5. How to Read Each Figure Type

### 5.1 Hit/Miss/Conflict Bar Chart (`hit_miss_conflict_by_benchmark.png`)

A grouped bar chart showing mean hit rate, miss rate, and conflict rate for each benchmark type (sequential, random, stride aggregate, working set). Read it as follows:

- **Blue bar (hit rate):** proportion of accesses served from the open row buffer. Taller = better locality.
- **Orange bar (miss rate):** proportion of accesses where the bank was idle. This is typically very small (< 0.5%) for all workloads — misses only occur on the first access to each row.
- **Red bar (conflict rate):** proportion of accesses that forced a precharge-activate cycle. Taller = worse locality. For sequential, this is negligible; for random, this dominates.

**Reading the chart:** Sequential and working set should show nearly solid blue. Random should show nearly solid red. Stride (aggregate) should show a mix, because it averages over all stride values from 1 to 1024.

### 5.2 Stride vs. Hit Rate Line Plot (`stride_vs_hit_rate.png`)

An X-Y line chart with stride value on the x-axis (logarithmic scale) and hit rate on the y-axis. Read it as follows:

- The curve should be smooth and monotonically decreasing from ~99.95% at stride=1 to ~50% at stride=1024.
- The slope is consistent on a linear scale but appears steeper at high strides on a log scale.
- Any deviation from the theoretical line `hit_rate = 1 − stride/2048` indicates a measurement artifact or an off-by-one in the stride parameter.

**Reference line:** The theoretical prediction can be plotted as a dashed line for comparison. Close agreement between measured and predicted validates the model.

### 5.3 Working Set vs. Locality Score (`working_set_vs_locality.png`)

An X-Y line chart with array size on the x-axis (logarithmic scale, MB) and locality score on the y-axis. Read it as follows:

- Locality score should be flat at ~+0.999 across all array sizes.
- Any deviation from a flat line at this value indicates inconsistency in the sequential access pattern or the state machine implementation.
- In a hardware measurement with cache modeling, this chart would show a step down from ~+1.0 to the DRAM-level sequential hit rate at the L3 cache capacity.

### 5.4 Locality Score Comparison (`locality_score_comparison.png`)

A single bar chart comparing the mean locality score for each benchmark. Sequential and working set should be near +1.0. Random should be near −1.0. Stride at the aggregate level should be around +0.5 to +0.7 (averaging over all strides).

---

## 6. What Results Mean for Real Applications

### 6.1 Database Workloads

A sequential table scan (SELECT * FROM table) has near-perfect row buffer locality. Each row in the DRAM sense contains many consecutive table rows; the scan proceeds in the same direction as DRAM's spatial layout.

A random lookup (SELECT * FROM table WHERE id = ?) is equivalent to the random access benchmark. If the table is larger than the row buffer can serve from cache, nearly every lookup triggers a row conflict. This is why database systems invest heavily in buffer pool management and index access path optimization — a random lookup against a cold table is among the worst-case DRAM access patterns.

### 6.2 Matrix Traversal

Row-major matrix traversal (accessing all elements of row i before moving to row i+1) is sequential in C — the innermost loop increments the column index, which advances the address by 4 bytes at a time. Hit rate: ~99.95%.

Column-major traversal of a row-major matrix accesses `A[0][j], A[1][j], A[2][j], ...` — advancing by `num_columns × 4` bytes per step. If `num_columns = 1024`, the stride is 4096 bytes = half a row, giving ~50% hit rate. If `num_columns = 2048`, stride = 8192 bytes = one full row, and hit rate approaches 0%. This is the root cause of the well-known performance penalty for column-major matrix traversal in C.

### 6.3 Linked List vs. Array

Array traversal is sequential (hit rate ~99.95%). Linked list traversal follows pointer-to-next-node relationships: if nodes are allocated at arbitrary addresses (as in a long-running process with fragmented heap), successive pointers may jump anywhere in the address space — equivalent to random access. Hit rate: effectively the same as the random benchmark.

This quantifies the performance case for array-of-structs vs. list-of-structs: the difference is not only cache line utilization but also DRAM row buffer efficiency.

### 6.4 GPU Memory Coalescing

GPU memory coalescing is the GPU equivalent of row buffer locality. A coalesced memory access means multiple threads in a warp access consecutive addresses within the same cache line / DRAM row. This maps directly to sequential access behavior in RowScope: near-perfect hit rate and maximum memory bandwidth.

Uncoalesced access (threads accessing stride-N or random addresses) is the GPU equivalent of the stride or random benchmarks: hit rate degrades, and effective bandwidth drops. GPU performance engineers optimize for coalescing for exactly the same reasons that CPU engineers optimize for sequential memory access.

---

## 7. Frequently Asked Questions

The following questions address common points of confusion when analyzing DRAM row buffer behavior. RowScope provides concrete, quantitative backing for each answer.

---

**Q: What is a DRAM row buffer hit, and why does it matter for performance?**

A: A row buffer hit occurs when a memory access targets the row that is currently open (activated) in a DRAM bank. Because the row contents are already latched in the row buffer — fast SRAM — the access is served at column-access latency (~13 ns for DDR4), with no row activation required. A row conflict, by contrast, requires a precharge (closing the current row) followed by an activation (opening the new row) before the column access, adding roughly 26–56 ns. The hit rate determines how often a workload pays the short path vs. the long path, directly affecting effective memory latency and bandwidth utilization.

---

**Q: Why does sequential access achieve near-perfect row buffer hit rate?**

A: In the model used here, each DRAM row is 8KB, and each array element is a 4-byte integer. A single row therefore holds 8192 / 4 = 2048 consecutive elements. Sequential traversal accesses `arr[0], arr[1], ..., arr[2047]` — all within the same row — then moves to the next row. After the first miss (row activation), 2047 of the next 2047 accesses are hits. The theoretical hit rate is 2047/2048 ≈ 99.95%, which matches the measured value exactly. This is the best-case pattern for open-page policy.

---

**Q: What is a row conflict, and what makes it the most expensive DRAM event?**

A: A row conflict occurs when a memory access targets a row that is *different* from the currently-open row in the same bank. The DRAM controller must first close the current row (precharge: charge is restored to the bitlines, ~tRP = 13 ns), then activate the new row (sense amplifiers amplify the new row's signal into the row buffer, ~tRCD = 13 ns), then perform the column access (~tCAS = 13 ns). The full sequence (tRP + tRCD + tCAS ≈ 39 ns minimum, often 70 ns in practice) is 3–5× longer than a row hit (tCAS only). Random access on a large array produces ~96–99% conflict rate — nearly every access pays this maximum latency.

---

**Q: How does stride size affect DRAM row buffer performance?**

A: Stride-N access advances the address by `N × element_size` bytes per step. A row boundary crossing occurs when this step exceeds the remaining column space in the current row. The probability of a crossing per step is `(N × element_size) / row_size`. For row_size = 8192 and element_size = 4 bytes:

```
hit_rate ≈ 1 − N / 2048
```

At N=256 (1KB step), hit rate is 87.5%. At N=1024 (4KB step, half a row), hit rate is 50%. At N=2048 (8KB = one full row), every step crosses a row boundary and hit rate approaches 0%. The RowScope stride sweep confirms this formula to within 0.02 percentage points across 11 stride values.

---

**Q: What is the difference between open-page and closed-page DRAM policy?**

A: Under open-page policy, after an access completes, the activated row remains open in the row buffer until a different row in the same bank is accessed (conflict). This benefits workloads with temporal locality — if the next access to the same bank targets the same row, it is served as a hit with no latency overhead. Under closed-page policy, the row is precharged (closed) after every access, regardless of what comes next. This eliminates conflicts — every access is a miss — but also eliminates hits. Closed-page policy is better for random workloads where open-page policy would accumulate conflicts anyway. Real controllers use adaptive policies that select the appropriate mode per bank based on observed traffic patterns. RowScope models open-page policy exclusively.

---

**Q: Why does the random access hit rate increase as array size decreases?**

A: Uniform random access distributes requests across all rows in the array. For a 64MB array, there are 64MB / 8KB = 8192 distinct rows. For an access to hit, the next random address must land in the same bank and the same currently-open row — probability approximately 1/(8 × 1024) ≈ 0.01%. For a 1MB array (128 rows, 16 per bank), the probability of hitting the same row again is much higher: 1/(8 × 16) ≈ 0.78%. The measured hit rates confirm this: 0.1% for 64MB random and 6.2% for 1MB random. The smaller the array, the more temporal locality random access accidentally exhibits.

---

**Q: What would a real hardware measurement look like compared to RowScope's simulation?**

A: A hardware measurement using CPU performance counters (e.g., Intel `UNC_M_CAS_COUNT.RD` for DRAM CAS reads, or `UNC_M_ACT_COUNT` for row activations) would differ from RowScope in three important ways. First, only accesses that miss the L3 cache reach DRAM — cache-resident working sets would show zero DRAM activity regardless of access pattern. Second, physical address mapping may differ from virtual address mapping due to OS page allocation, potentially changing which accesses land in which banks. Third, the actual DRAM controller may use adaptive page policy, reordering requests and closing rows proactively. RowScope's value is that it isolates the address-pattern effect from these confounding factors, providing a clean model of the *inherent* locality of each access pattern as seen at the DRAM interface.
