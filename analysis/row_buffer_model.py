"""
RowScope — Row Buffer State Machine Model
==========================================
Project: RowScope — DRAM Row Buffer Locality Analyzer
File:    analysis/row_buffer_model.py
Purpose: Per-bank row buffer state machine simulation.
         Classifies each memory access as 'hit', 'miss', or 'conflict'
         per the state machine defined in architecture.md §4.

State machine per bank (architecture.md §4.1 / §4.2):
  States:  EMPTY | OPEN(row_id)
  T1: EMPTY       + access(bank=b, row=r)  -> OPEN(r)     [miss]
  T2: OPEN(r)     + access(bank=b, row=r)  -> OPEN(r)     [hit]
  T3: OPEN(r)     + access(bank=b, row=r') -> OPEN(r')    [conflict]
  (accesses to a different bank do not affect this bank's state)

Author:  [Implementation Engineer]
Date:    2026-03-11
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from .dram_mapping import DRAMMapper

# Sentinel value: bank row buffer is empty (no open row)
_EMPTY = -1


class RowBufferModel:
    """
    Simulates per-bank row buffer state machines.

    Each bank independently tracks which row (if any) is currently open.
    All banks start in the EMPTY state.

    Usage:
        mapper = DRAMMapper()
        model  = RowBufferModel(mapper)
        event  = model.process_access(address)   # -> "hit" | "miss" | "conflict"
        stats  = model.get_stats()
    """

    def __init__(self, mapper: "DRAMMapper") -> None:
        """
        Initialize RowBufferModel with a DRAMMapper.

        Args:
            mapper: A configured DRAMMapper instance.

        Creates NUM_BANKS independent state machines, all in EMPTY state.
        """
        self._mapper    = mapper
        self._num_banks = mapper.get_num_banks()

        # Per-bank open row: _EMPTY means the bank is in the EMPTY state.
        self._open_row: List[int] = [_EMPTY] * self._num_banks

        # Global counters
        self._hits      = 0
        self._misses    = 0
        self._conflicts = 0

        # Per-bank statistics; each entry is a dict with:
        #   total_accesses, hits, misses, conflicts, unique_rows (set of row_ids)
        self._bank_stats = [
            {
                "total_accesses": 0,
                "hits":           0,
                "misses":         0,
                "conflicts":      0,
                "unique_rows":    set(),
            }
            for _ in range(self._num_banks)
        ]

        # Set of bank_ids that have received at least one access
        self._unique_banks: set = set()

    # ------------------------------------------------------------------
    # Core access processing
    # ------------------------------------------------------------------

    def process_access(self, address: int) -> str:
        """
        Process a single memory access and update state machines.

        Args:
            address: Byte address of the access.

        Returns:
            One of: "hit", "miss", "conflict"

        Raises:
            ValueError: If address is negative.
        """
        bank_id, row_id, _col = self._mapper.map(address)

        bs = self._bank_stats[bank_id]
        bs["total_accesses"] += 1
        bs["unique_rows"].add(row_id)
        self._unique_banks.add(bank_id)

        current = self._open_row[bank_id]

        if current == _EMPTY:
            # Transition T1: EMPTY -> OPEN(row_id)  [miss]
            self._open_row[bank_id] = row_id
            self._misses           += 1
            bs["misses"]           += 1
            return "miss"
        elif current == row_id:
            # Transition T2: OPEN(row_id) -> OPEN(row_id)  [hit]
            self._hits   += 1
            bs["hits"]   += 1
            return "hit"
        else:
            # Transition T3: OPEN(r) + access(r') -> OPEN(r')  [conflict]
            self._open_row[bank_id] = row_id
            self._conflicts        += 1
            bs["conflicts"]        += 1
            return "conflict"

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        """
        Return aggregate statistics across all banks.

        Returns:
            {
                "hits":            int,
                "misses":          int,
                "conflicts":       int,
                "total":           int,   # hits + misses + conflicts
                "hit_rate":        float, # hits / total (0 if total == 0)
                "miss_rate":       float,
                "conflict_rate":   float,
                "locality_score":  float, # hit_rate - conflict_rate
                "unique_rows":     int,   # distinct (bank_id, row_id) pairs seen
                "unique_banks":    int,   # distinct bank_ids accessed
            }
        """
        total = self._hits + self._misses + self._conflicts

        if total > 0:
            hit_rate      = self._hits      / total
            miss_rate     = self._misses    / total
            conflict_rate = self._conflicts / total
        else:
            hit_rate = miss_rate = conflict_rate = 0.0

        locality_score = hit_rate - conflict_rate

        unique_rows = sum(
            len(bs["unique_rows"]) for bs in self._bank_stats
        )

        return {
            "hits":           self._hits,
            "misses":         self._misses,
            "conflicts":      self._conflicts,
            "total":          total,
            "hit_rate":       hit_rate,
            "miss_rate":      miss_rate,
            "conflict_rate":  conflict_rate,
            "locality_score": locality_score,
            "unique_rows":    unique_rows,
            "unique_banks":   len(self._unique_banks),
        }

    def get_per_bank_stats(self) -> list:
        """
        Return per-bank statistics.

        Returns:
            List of dicts, one per bank (indexed by bank_id), each containing:
            {
                "bank_id":        int,
                "total_accesses": int,
                "hits":           int,
                "misses":         int,
                "conflicts":      int,
                "hit_rate":       float,
                "conflict_rate":  float,
                "unique_rows":    int,   # distinct row_ids accessed in this bank
            }
        """
        result = []
        for bank_id, bs in enumerate(self._bank_stats):
            total = bs["total_accesses"]
            if total > 0:
                hit_rate      = bs["hits"]      / total
                conflict_rate = bs["conflicts"] / total
            else:
                hit_rate = conflict_rate = 0.0

            result.append({
                "bank_id":        bank_id,
                "total_accesses": total,
                "hits":           bs["hits"],
                "misses":         bs["misses"],
                "conflicts":      bs["conflicts"],
                "hit_rate":       hit_rate,
                "conflict_rate":  conflict_rate,
                "unique_rows":    len(bs["unique_rows"]),
            })
        return result

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset all bank states to EMPTY and clear all counters."""
        self._open_row  = [_EMPTY] * self._num_banks
        self._hits      = 0
        self._misses    = 0
        self._conflicts = 0
        self._bank_stats = [
            {
                "total_accesses": 0,
                "hits":           0,
                "misses":         0,
                "conflicts":      0,
                "unique_rows":    set(),
            }
            for _ in range(self._num_banks)
        ]
        self._unique_banks = set()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        stats = self.get_stats()
        return (
            f"RowBufferModel(mapper={self._mapper!r}, "
            f"total={stats['total']}, hit_rate={stats['hit_rate']:.3f})"
        )


# ---------------------------------------------------------------------------
# Self-test / demo block
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from analysis.dram_mapping import DRAMMapper

    print("=== RowBufferModel Demo ===\n")

    mapper = DRAMMapper(row_size=8192, num_banks=8, scheme="sequential")
    model  = RowBufferModel(mapper)
    print(f"Mapper: {mapper}")
    print()

    # Sequential access: every access within the same row -> all hits after first miss
    # Row size = 8192 bytes.  Access bytes 0..8191 sequentially.
    print("--- Sequential access within one row (expect 1 miss + 8191 hits) ---")
    for i in range(8192):
        event = model.process_access(i)
    stats = model.get_stats()
    print(f"  hits={stats['hits']} misses={stats['misses']} conflicts={stats['conflicts']}")
    assert stats["misses"] == 1, f"Expected 1 miss, got {stats['misses']}"
    assert stats["hits"]   == 8191, f"Expected 8191 hits, got {stats['hits']}"
    assert stats["conflicts"] == 0
    print("  PASS")

    model.reset()

    # Access every 8192 bytes -> every access goes to a new row -> all misses then conflicts
    print("\n--- Row-strided access (stride = row_size, 16 rows) ---")
    # Access row 0 of bank 0, then row 0 of bank 1, ... then row 1 of bank 0, etc.
    # With 8 banks, accessing 0, 8192, 16384, ... the first 8 are misses,
    # then the next 8 are conflicts (same banks, different rows).
    for i in range(16):
        addr  = i * 8192
        event = model.process_access(addr)
    stats = model.get_stats()
    print(f"  hits={stats['hits']} misses={stats['misses']} conflicts={stats['conflicts']}")
    print(f"  hit_rate={stats['hit_rate']:.3f}  conflict_rate={stats['conflict_rate']:.3f}")
    assert stats["hits"] == 0
    assert stats["misses"] == 8
    assert stats["conflicts"] == 8
    print("  PASS")

    model.reset()

    # Random-like accesses: repeat the same address many times -> pure hits after first miss
    print("\n--- Repeated access to one address ---")
    for _ in range(1000):
        model.process_access(12345)
    stats = model.get_stats()
    print(f"  hits={stats['hits']} misses={stats['misses']} conflicts={stats['conflicts']}")
    assert stats["misses"] == 1
    assert stats["hits"]   == 999
    assert stats["conflicts"] == 0
    print("  PASS")

    print("\n=== All RowBufferModel tests passed ===")
