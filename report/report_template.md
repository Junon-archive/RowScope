# RowScope: DRAM Row Buffer Locality Analyzer
## Experiment Report

**Generated:** {{ generated_date }}
**System:** {{ system_info }}
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

{{ analysis_model_description }}

**DRAMMapper parameters:**

| Parameter | Value |
|-----------|-------|
| Row size | {{ dram_row_size }} bytes |
| Number of banks | {{ dram_num_banks }} |
| Interleaving scheme | {{ dram_scheme }} |

---

## 4. Experimental Setup

### 4.1 Host System

| Property | Value |
|----------|-------|
| OS | {{ system_os }} |
| CPU | {{ system_cpu }} |
| Memory | {{ system_memory }} |
| Compiler | gcc (C99, -O2 -Wall -Wextra) |
| Python | {{ python_version }} |

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

{{ workload_comparison_table }}

*Table: Mean hit/miss/conflict rates and locality score by benchmark type.*

![Workload Comparison]({{ figures_dir }}/workload_comparison.png)

### 5.2 Stride Analysis

{{ stride_analysis_table }}

*Table: Row buffer statistics for stride benchmark (16MB array, 100K accesses).*

![Stride vs Hit Rate]({{ figures_dir }}/stride_vs_hit_rate.png)

### 5.3 Working Set Sweep

{{ working_set_table }}

*Table: Locality score across working set sizes (sequential pattern).*

![Working Set vs Locality]({{ figures_dir }}/working_set_sweep.png)

### 5.4 Sequential vs Random Locality

![Sequential vs Random]({{ figures_dir }}/sequential_vs_random.png)

### 5.5 Row Buffer Locality Heatmap

![Locality Heatmap]({{ figures_dir }}/locality_heatmap.png)

---

## 6. Interpretation

### 6.1 Sequential Access

{{ sequential_interpretation }}

**Expected:** hit rate ≈ 99.9% (2047/2048 accesses per row are hits after warm-up).

### 6.2 Random Access

{{ random_interpretation }}

**Expected:** conflict rate ≈ 90%+ (uniform distribution across ~2048 rows per bank
means same-bank sequential accesses almost never hit the same row).

### 6.3 Stride Access

{{ stride_interpretation }}

**Key transition:** At stride = `ROW_SIZE / sizeof(int)` = 2048 elements (8KB),
every access crosses exactly one row boundary. For stride = 1024 (4KB = half row),
hit rate is approximately 50% within the same bank.

### 6.4 Working Set Sweep

{{ workingset_interpretation }}

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

{{ key_takeaways }}

---

*Report generated by `report/generate_report.py`.*
*RowScope — https://github.com/[your-username]/RowScope*
