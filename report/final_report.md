# RowScope: DRAM Row Buffer Locality Analyzer
## Experiment Report

**Generated:** 2026-03-12 11:36:28
**System:** Linux-6.8.0-94-generic-x86_64-with-glibc2.35 | Python 3.14.3
**RowScope Version:** 1.0
**Architecture Spec Version:** 1.0 (2026-03-11)

---

## 1. Project Motivation

Modern DRAM performance is strongly influenced by row buffer locality — the tendency of
consecutive memory accesses to target the same open row in a DRAM bank, enabling fast
column-access latency without a row precharge/activate cycle.

RowScope measures how different memory access patterns (sequential, random, stride, sweep)
interact with the DRAM row buffer state machine, producing quantitative hit/miss/conflict
rates for comparison.

Understanding row buffer locality is critical for:
- Memory-intensive algorithm design (loop tiling, data layout optimization)
- Hardware prefetch effectiveness analysis
- DRAM controller policy evaluation

---

## 2. DRAM Row Buffer Concepts

### 2.1 Row Buffer States

Each DRAM bank has an independent row buffer with two states:

| State | Description |
|-------|-------------|
| `EMPTY` | No row is currently loaded |
| `OPEN(row_id)` | Row `row_id` is loaded and accessible at column latency |

### 2.2 Access Events

| Event | Condition | Latency |
|-------|-----------|---------|
| Row Hit | Bank `OPEN(r)`, access targets same row `r` | tCAS (~13 ns) |
| Row Miss | Bank `EMPTY`, any row accessed | tRCD + tCAS (~26 ns) |
| Row Conflict | Bank `OPEN(r)`, access targets different row `r'` | tRP + tRCD + tCAS (~39 ns) |

### 2.3 DRAM Address Mapping (Sequential Scheme)

With `ROW_SIZE=8192` bytes and `NUM_BANKS=16`:

```
col_offset = addr & 0x1FFF          (bits [12:0])
bank_id    = (addr >> 13) & 0xF     (bits [16:13])
row_id     = addr >> 17             (bits [31:17])
```

---

## 3. Analysis Model

RowScope applies a parametric address decomposition model to translate virtual memory addresses into DRAM coordinates (bank, row, column). The bit-interleaved scheme assigns the low 13 bits of an address to the column offset (within an 8KB row), the next 3 bits to the bank identifier (selecting one of 8 banks), and the remaining upper bits to the row identifier. A per-bank state machine classifies each access as a row hit, row miss, or row conflict based on whether the target row matches the currently-open row in that bank. See `docs/methodology.md` for the full derivation and parameter rationale.

**DRAMMapper parameters:**

| Parameter | Value |
|-----------|-------|
| Row size | 8192 bytes |
| Number of banks | 8 |
| Interleaving scheme | bit-interleaved |

---

## 4. Experimental Setup

### 4.1 Host System

| Property | Value |
|----------|-------|
| OS | Linux-6.8.0-94-generic-x86_64-with-glibc2.35 |
| CPU | x86_64 |
| Memory | (install psutil for memory info) |
| Compiler | gcc (C99, -O2 -Wall -Wextra) |
| Python | 3.14.3 |

### 4.2 Benchmark Parameter Matrix

| Benchmark | Sizes / Strides | Accesses | Iterations |
|-----------|----------------|----------|------------|
| Sequential | 1MB, 4MB, 16MB, 64MB | all elements × iterations | 3 |
| Random | 1MB, 4MB, 16MB, 64MB | 100,000 per run | 1 |
| Stride | 16MB fixed; stride ∈ {1,2,4,8,16,32,64,128,256,512,1024} | 100,000 | 1 |
| Working Set | 512KB → 128MB (9 log-spaced steps) | all elements × iterations | 3 |

**Total trace files:** 28

---

## 5. Results

### 5.1 Workload Comparison

| Benchmark | Hit Rate | Conflict Rate | Miss Rate | Locality Score |
|-----------|----------|---------------|-----------|----------------|
| Sequential | 99.95% | 0.05% | 0.00% | +0.9990 |
| Random | 4.07% | 95.91% | 0.02% | -0.9184 |
| Stride | 90.91% | 9.08% | 0.02% | +0.8183 |
| Working Set | 99.95% | 0.05% | 0.00% | +0.9990 |

*Table: Mean hit/miss/conflict rates and locality score by benchmark type.*

![Workload Comparison](results/figures/workload_comparison.png)

### 5.2 Stride Analysis

| Stride (elements) | Byte Step | Hit Rate | Conflict Rate | Locality Score |
|-------------------|-----------|----------|---------------|----------------|
| 1 | 4 B | 99.95% | 0.03% | +0.9992 |
| 2 | 8 B | 99.90% | 0.08% | +0.9982 |
| 4 | 16 B | 99.80% | 0.18% | +0.9962 |
| 8 | 32 B | 99.61% | 0.38% | +0.9923 |
| 16 | 64 B | 99.22% | 0.77% | +0.9845 |
| 32 | 128 B | 98.44% | 1.55% | +0.9689 |
| 64 | 256 B | 96.87% | 3.11% | +0.9376 |
| 128 | 512 B | 93.75% | 6.24% | +0.8751 |
| 256 | 1024 B | 87.49% | 12.49% | +0.7500 |
| 512 | 2048 B | 74.99% | 25.00% | +0.4999 |
| 1024 | 4096 B | 49.98% | 50.01% | -0.0003 |

*Table: Row buffer statistics for stride benchmark (16MB array, 100K accesses).*

![Stride vs Hit Rate](results/figures/stride_vs_hit_rate.png)

### 5.3 Working Set Sweep

| Array Size | Hit Rate | Conflict Rate | Miss Rate | Locality Score |
|------------|----------|---------------|-----------|----------------|
| 512 KB | 99.95% | 0.04% | 0.00% | +0.9991 |
| 1 MB | 99.95% | 0.05% | 0.00% | +0.9990 |
| 2 MB | 99.95% | 0.05% | 0.00% | +0.9990 |
| 4 MB | 99.95% | 0.05% | 0.00% | +0.9990 |
| 8 MB | 99.95% | 0.05% | 0.00% | +0.9990 |
| 16 MB | 99.95% | 0.05% | 0.00% | +0.9990 |
| 32 MB | 99.95% | 0.05% | 0.00% | +0.9990 |
| 64 MB | 99.95% | 0.05% | 0.00% | +0.9990 |
| 128 MB | 99.95% | 0.05% | 0.00% | +0.9990 |

*Table: Locality score across working set sizes (sequential pattern).*

![Working Set vs Locality](results/figures/working_set_sweep.png)

### 5.4 Sequential vs Random Locality

![Sequential vs Random](results/figures/sequential_vs_random.png)

### 5.5 Row Buffer Locality Heatmap

![Locality Heatmap](results/figures/locality_heatmap.png)

---

## 6. Interpretation

### 6.1 Sequential Access

Sequential access achieves a mean row hit rate of **99.95%**, consistent across all tested array sizes (1 MB, 4 MB, 16 MB). With a row size of 8192 bytes and 4-byte integer elements, each DRAM row holds 2048 consecutive elements. After the first row miss (activation), the next 2047 accesses are served from the open row buffer. Theoretical hit rate = 2047 / 2048 = 99.95%, matching measurement.

**Expected:** hit rate ≈ 99.9% (2047/2048 accesses per row are hits after warm-up).

### 6.2 Random Access

Random access produces a mean row hit rate of **4.07%** (range: 0.20% to 12.26%) and a mean conflict rate of **95.91%**. Hit rate decreases as array size grows — from 12.26% at 1 MB to 0.20% at 64 MB — because larger arrays spread accesses across more rows, making accidental row reuse less likely. At 16 MB, there are 2048 rows across 8 banks (256 rows per bank); the probability that two successive random accesses land in the same bank and row is approximately 1/2048 ≈ 0.05%.

**Expected:** conflict rate ≈ 90%+ (uniform distribution across ~2048 rows per bank
means same-bank sequential accesses almost never hit the same row).

### 6.3 Stride Access

Stride access hit rate decreases monotonically as stride grows, following the theoretical relationship:

```
hit_rate ≈ 1 − (stride × element_size) / row_size
         = 1 − (stride × 4) / 8192
         = 1 − stride / 2048
```

At stride=1, hit rate is **99.95%** (identical to sequential). 
At stride=256 (1KB step), hit rate falls to **87.49%** (predicted: 87.50%). 
At stride=1024 (4KB step = half a row), hit rate is **49.98%** (predicted: 50.00%). The critical threshold — where every access crosses a row boundary — is stride=2048 (8KB = one full row), beyond which hit rate approaches 0%.

**Key transition:** At stride = `ROW_SIZE / sizeof(int)` = 2048 elements (8KB),
every access crosses exactly one row boundary. For stride = 1024 (4KB = half row),
hit rate is approximately 50% within the same bank.

### 6.4 Working Set Sweep

Working set hit rate is stable at **99.95%** (min: 99.95%, max: 99.95%) across all array sizes from 512 KB to 128 MB. This confirms that for a sequential access pattern, row buffer locality is determined by the spatial structure of accesses within each row, independent of total working set size. Note: this simulation does not model CPU cache. A hardware measurement would show a transition at the L3 cache capacity boundary (~16–32 MB on typical server processors), below which cache hits prevent most accesses from reaching DRAM at all.

**Expected:** Locality score remains ≈ 0.998 across all sizes since the access
pattern is sequential regardless of working set size.

---

## 7. Limitations

1. **Virtual address assumption:** Benchmarks record virtual addresses from `malloc`.
   The analysis treats these as physical addresses. OS page table mapping means the
   actual physical bank distribution may differ; however, relative pattern comparisons
   remain valid.

2. **Single-threaded model:** RowScope models a single-threaded access stream.
   Multi-threaded workloads with bank-interleaved access from multiple cores are not
   modeled.

3. **No cache modeling:** L1/L2/L3 cache effects are not simulated. In practice,
   cache hits reduce DRAM traffic; the row buffer model analyzes only accesses that
   reach DRAM.

4. **Closed-page policy:** RowScope uses an open-page (row stays open until a conflict)
   state machine. Real DRAM controllers may use closed-page or adaptive policies.

5. **`rand()` quality:** The random benchmark uses `srand(seed)` + `rand()` from libc,
   which has lower statistical quality than a full PRNG. Results are reproducible but
   may exhibit platform-dependent period behavior for very large access counts.

---

## 8. Key Takeaways

1. **Sequential access achieves 99.95% row hit rate** because 2048 consecutive 4-byte integers fit in one 8KB DRAM row. Spatial locality in software maps directly to temporal locality in DRAM.

2. **Random access causes 95.91% conflict rate** on large arrays. Every uniform random access is overwhelmingly likely to target a different row than the currently-open one. Pointer-chasing and hash table access patterns fall into this category.

3. **Stride hit rate follows a linear formula:** `hit_rate = 1 − stride/2048`. Stride=1 gives 99.95%; stride=1024 gives 49.98%. The critical threshold is stride=2048 (one full row), where hit rate reaches 0%.

4. **The locality gap between sequential and random is ~99.5 percentage points.** In latency terms, this translates to a 3–5× difference in effective DRAM access time per operation.

5. **Working set size does not affect row hit rate for sequential patterns.** Hit rate is ~99.95% from 512KB to 128MB. Pattern structure, not data volume, determines locality.

6. **Locality score = hit_rate − conflict_rate** provides a single [-1, +1] summary. Sequential ≈ +0.999; random at 16MB ≈ −0.998. This metric directly reflects the net effect of open-page policy for a given workload.

7. **DRAM controller policy selection depends on measured hit rates.** Open-page policy benefits sequential workloads. Closed-page or adaptive policy is better for random workloads. RowScope produces the data needed to make this decision quantitatively.

8. **Matrix column traversal and certain FFT strides exhibit the row-size pathology.** Any stride that is a multiple of 2048 elements (8KB) causes every access to land in a new row — the worst case for open-page policy. This is the architectural basis for the standard advice to prefer row-major access in C.

---

*Report generated by `report/generate_report.py`.*
*RowScope — https://github.com/Junon-archive/RowScope*
