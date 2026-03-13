"""
RowScope — DRAM 주소 매핑 모델
================================
프로젝트: RowScope — DRAM Row Buffer Locality Analyzer
파일:    analysis/dram_mapping.py
목적: 가상 바이트 주소를 DRAM (bank_id, row_id, col_offset) 튜플로 매핑한다.
     인터리빙 방식은 설정 가능하다.

지원하는 두 가지 방식 (architecture.md §3):

  "sequential" (기본값):
      col_offset = addr & (ROW_SIZE - 1)               # bits [R-1:0]
      bank_id    = (addr >> R) & (NUM_BANKS - 1)        # bits [R+B-1:R]
      row_id     = addr >> (R + B)                      # bits [31:R+B]
      여기서 R = log2(ROW_SIZE), B = log2(NUM_BANKS)

  "bitwise" (XOR 기반):
      col_offset = addr & (ROW_SIZE - 1)
      raw_bank   = (addr >> R) & (NUM_BANKS - 1)
      xor_bits   = (addr >> (R + B)) & (NUM_BANKS - 1)
      bank_id    = raw_bank ^ xor_bits
      row_id     = addr >> (R + B)

기본 파라미터 (architecture.md §3.2):
    row_size  = 8192  (8 KB)
    num_banks = 16
    scheme    = "sequential"

작성자:  [Implementation Engineer]
날짜:    2026-03-11
"""

from __future__ import annotations

import math
from typing import Tuple


class DRAMMapper:
    """
    바이트 주소를 DRAM (bank_id, row_id, col_offset) 튜플로 매핑한다.

    두 가지 매핑 방식과 동작 예시는 architecture.md §3을 참고한다.
    """

    DEFAULT_ROW_SIZE  = 8192   # 8 KB — DRAM 행 하나
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
        DRAMMapper를 초기화한다.

        Args:
            row_size:  Row buffer 크기 (바이트). 반드시 2의 거듭제곱이어야 한다.
            num_banks: DRAM 뱅크 수. 반드시 2의 거듭제곱이어야 한다.
            scheme:    "sequential" 또는 "bitwise".

        Raises:
            ValueError: row_size 또는 num_banks가 2의 거듭제곱이 아닌 경우,
                        또는 scheme이 유효하지 않은 경우.
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

        # 핫 패스(hot path) 효율을 위해 시프트 양과 마스크를 미리 계산
        self._R         = int(math.log2(row_size))   # 열 비트 수
        self._B         = int(math.log2(num_banks))  # 뱅크 비트 수
        self._col_mask  = row_size - 1
        self._bank_mask = num_banks - 1

    # ------------------------------------------------------------------
    # 핵심 매핑 메서드
    # ------------------------------------------------------------------

    def map(self, address: int) -> Tuple[int, int, int]:
        """
        바이트 주소를 DRAM 좌표로 매핑한다.

        Args:
            address: 바이트 주소 (0 이상의 정수).

        Returns:
            (bank_id, row_id, col_offset) 튜플.

        Raises:
            ValueError: address가 음수인 경우.

        예시 (sequential 방식, row_size=8192, num_banks=16):
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
            # "bitwise" XOR 기반 방식
            raw_bank = (address >> self._R) & self._bank_mask
            xor_bits = (address >> (self._R + self._B)) & self._bank_mask
            bank_id  = raw_bank ^ xor_bits
            row_id   = address >> (self._R + self._B)

        return (bank_id, row_id, col_offset)

    # ------------------------------------------------------------------
    # 접근자 (Accessors)
    # ------------------------------------------------------------------

    def get_row_size(self) -> int:
        """설정된 row 크기를 바이트로 반환한다."""
        return self._row_size

    def get_num_banks(self) -> int:
        """설정된 뱅크 수를 반환한다."""
        return self._num_banks

    def get_scheme(self) -> str:
        """설정된 인터리빙 방식 이름을 반환한다."""
        return self._scheme

    # ------------------------------------------------------------------
    # 정보 조회 헬퍼
    # ------------------------------------------------------------------

    def describe_address(self, address: int) -> str:
        """
        주소가 어떻게 매핑되는지 사람이 읽기 쉬운 분석 결과를 반환한다.

        Args:
            address: 바이트 주소 (0 이상의 정수).

        Returns:
            비트 분해 과정을 설명하는 여러 줄의 문자열.
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
# 셀프 테스트 / 데모 블록
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== DRAMMapper Demo ===\n")

    # 기본 매퍼: row_size=8192, num_banks=16, scheme="sequential"
    mapper = DRAMMapper()
    print(repr(mapper))
    print()

    # architecture.md §3의 동작 예시
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

    # describe_address 동작 확인
    print()
    print(mapper.describe_address(270336))

    # XOR 방식 데모
    print()
    xor_mapper = DRAMMapper(scheme="bitwise")
    print(f"\n{repr(xor_mapper)}")
    print(f"  map(0)      = {xor_mapper.map(0)}")
    print(f"  map(8192)   = {xor_mapper.map(8192)}")
    print(f"  map(131072) = {xor_mapper.map(131072)}")

    # 태스크 명세 검증: row_size=8192, num_banks=8
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
