"""
RowScope — DRAM Address Mapping Model
======================================
Project: RowScope — DRAM Row Buffer Locality Analyzer
File:    analysis/dram_mapping.py
Purpose: Maps virtual byte addresses to DRAM (bank_id, row_id, col_offset)
         tuples using a configurable interleaving scheme.

Two schemes are supported (architecture.md §3):

  "sequential" (default):
      col_offset = addr & (ROW_SIZE - 1)               # bits [R-1:0]
      bank_id    = (addr >> R) & (NUM_BANKS - 1)        # bits [R+B-1:R]
      row_id     = addr >> (R + B)                      # bits [31:R+B]
      where R = log2(ROW_SIZE), B = log2(NUM_BANKS)

  "bitwise" (XOR-based):
      col_offset = addr & (ROW_SIZE - 1)
      raw_bank   = (addr >> R) & (NUM_BANKS - 1)
      xor_bits   = (addr >> (R + B)) & (NUM_BANKS - 1)
      bank_id    = raw_bank ^ xor_bits
      row_id     = addr >> (R + B)

Default parameters (architecture.md §3.2):
    row_size  = 8192  (8 KB)
    num_banks = 16
    scheme    = "sequential"

Author:  [Implementation Engineer]
Date:    2026-03-11
"""

from __future__ import annotations

import math
from typing import Tuple


class DRAMMapper:
    """
    Maps byte addresses to DRAM (bank_id, row_id, col_offset) tuples.

    See architecture.md §3 for the full specification of both mapping schemes
    and worked examples.
    """

    DEFAULT_ROW_SIZE  = 8192   # 8 KB — one DRAM row
    DEFAULT_NUM_BANKS = 16
    DEFAULT_SCHEME    = "sequential"

    VALID_SCHEMES = frozenset({"sequential", "bitwise"})

    def __init__(
        self,
        row_size:  int = DEFAULT_ROW_SIZE,
        num_banks: int = DEFAULT_NUM_BANKS,
        scheme:    str = DEFAULT_SCHEME,
    ) -> None:
        """
        Initialize DRAMMapper.

        Args:
            row_size:  Row buffer size in bytes.  Must be a power of 2.
            num_banks: Number of DRAM banks.  Must be a power of 2.
            scheme:    "sequential" or "bitwise".

        Raises:
            ValueError: If row_size or num_banks is not a power of 2,
                        or if scheme is not recognized.
        """
        if row_size <= 0 or (row_size & (row_size - 1)) != 0:
            raise ValueError(
                f"row_size must be a positive power of 2, got {row_size}"
            )
        if num_banks <= 0 or (num_banks & (num_banks - 1)) != 0:
            raise ValueError(
                f"num_banks must be a positive power of 2, got {num_banks}"
            )
        if scheme not in self.VALID_SCHEMES:
            raise ValueError(
                f"scheme must be one of {sorted(self.VALID_SCHEMES)}, got {scheme!r}"
            )

        self._row_size  = row_size
        self._num_banks = num_banks
        self._scheme    = scheme

        # Precompute shift amounts and masks for hot-path efficiency
        self._R         = int(math.log2(row_size))   # col_bits
        self._B         = int(math.log2(num_banks))  # bank_bits
        self._col_mask  = row_size - 1
        self._bank_mask = num_banks - 1

    # ------------------------------------------------------------------
    # Core mapping method
    # ------------------------------------------------------------------

    def map(self, address: int) -> Tuple[int, int, int]:
        """
        Map a byte address to DRAM coordinates.

        Args:
            address: Byte address (non-negative integer).

        Returns:
            (bank_id, row_id, col_offset) tuple.

        Raises:
            ValueError: If address is negative.

        Example (sequential scheme, row_size=8192, num_banks=16):
            mapper.map(270336)  -> (1, 2, 0)
            mapper.map(65536)   -> (8, 0, 0)
            mapper.map(0)       -> (0, 0, 0)
        """
        if address < 0:
            raise ValueError(f"address must be non-negative, got {address}")

        col_offset = address & self._col_mask

        if self._scheme == "sequential":
            bank_id = (address >> self._R) & self._bank_mask
            row_id  = address >> (self._R + self._B)
        else:
            # "bitwise" XOR-based scheme
            raw_bank = (address >> self._R) & self._bank_mask
            xor_bits = (address >> (self._R + self._B)) & self._bank_mask
            bank_id  = raw_bank ^ xor_bits
            row_id   = address >> (self._R + self._B)

        return (bank_id, row_id, col_offset)

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_row_size(self) -> int:
        """Return configured row size in bytes."""
        return self._row_size

    def get_num_banks(self) -> int:
        """Return configured number of banks."""
        return self._num_banks

    def get_scheme(self) -> str:
        """Return configured interleaving scheme name."""
        return self._scheme

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------

    def describe_address(self, address: int) -> str:
        """
        Return a human-readable breakdown of how an address is mapped.

        Args:
            address: Byte address (non-negative integer).

        Returns:
            Multi-line string describing the bit decomposition.
        """
        bank_id, row_id, col_offset = self.map(address)
        lines = [
            f"Address:    0x{address:016X}  ({address})",
            f"  Scheme:       {self._scheme}",
            f"  Row size:     {self._row_size} bytes  (R = {self._R} bits)",
            f"  Num banks:    {self._num_banks}  (B = {self._B} bits)",
            f"  col_offset:   {col_offset}  (bits [{self._R - 1}:0])",
            f"  bank_id:      {bank_id}  (bits [{self._R + self._B - 1}:{self._R}])",
            f"  row_id:       {row_id}  (bits [63:{self._R + self._B}])",
        ]
        return "\n".join(lines)

    def __repr__(self) -> str:
        return (
            f"DRAMMapper(row_size={self._row_size}, "
            f"num_banks={self._num_banks}, scheme={self._scheme!r})"
        )


# ---------------------------------------------------------------------------
# Self-test / demo block
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== DRAMMapper Demo ===\n")

    # Default mapper: row_size=8192, num_banks=16, scheme="sequential"
    mapper = DRAMMapper()
    print(repr(mapper))
    print()

    # Worked examples from architecture.md §3
    test_cases = [
        (0,       (0,  0, 0), "addr=0 -> bank=0, row=0, col=0"),
        (8192,    (1,  0, 0), "addr=8192 (1 row) -> bank=1, row=0, col=0"),
        (65536,   (8,  0, 0), "addr=65536 (8 rows) -> bank=8, row=0, col=0"),
        (131072,  (0,  1, 0), "addr=131072 (16 rows) -> bank=0, row=1, col=0"),
        (270336,  (1,  2, 0), "addr=270336 -> bank=1, row=2, col=0"),
        (270340,  (1,  2, 4), "addr=270340 -> bank=1, row=2, col=4"),
    ]

    all_passed = True
    for addr, expected, desc in test_cases:
        result = mapper.map(addr)
        status = "PASS" if result == expected else "FAIL"
        if status == "FAIL":
            all_passed = False
        print(f"  [{status}] {desc}")
        if status == "FAIL":
            print(f"         expected {expected}, got {result}")

    print()
    print(f"All tests passed: {all_passed}")

    # Demonstrate describe_address
    print()
    print(mapper.describe_address(270336))

    # XOR scheme demo
    print()
    xor_mapper = DRAMMapper(scheme="bitwise")
    print(f"\n{repr(xor_mapper)}")
    print(f"  map(0)      = {xor_mapper.map(0)}")
    print(f"  map(8192)   = {xor_mapper.map(8192)}")
    print(f"  map(131072) = {xor_mapper.map(131072)}")

    # Task spec verification: row_size=8192, num_banks=8
    print("\n=== Task spec verification (row_size=8192, num_banks=8) ===")
    m8 = DRAMMapper(row_size=8192, num_banks=8)
    cases8 = [
        (0,         (0, 0, 0), "map(0) -> (0,0,0)"),
        (8192,      (1, 0, 0), "map(8192) -> (1,0,0)"),
        (8192 * 8,  (0, 1, 0), "map(8192*8) -> (0,1,0)"),
    ]
    for addr, expected, desc in cases8:
        result = m8.map(addr)
        status = "PASS" if result == expected else "FAIL"
        print(f"  [{status}] {desc}  got={result}")
