"""
RowScope — Row Buffer 상태 머신 모델
======================================
프로젝트: RowScope — DRAM Row Buffer Locality Analyzer
파일:    analysis/row_buffer_model.py
목적: 뱅크별 row buffer 상태 머신 시뮬레이션.
     각 메모리 접근을 'hit', 'miss', 'conflict' 중 하나로 분류한다.
     상태 머신 정의는 architecture.md §4 참고.

뱅크별 상태 머신 (architecture.md §4.1 / §4.2):
  상태:  EMPTY | OPEN(row_id)
  T1: EMPTY       + access(bank=b, row=r)  -> OPEN(r)     [miss]
  T2: OPEN(r)     + access(bank=b, row=r)  -> OPEN(r)     [hit]
  T3: OPEN(r)     + access(bank=b, row=r') -> OPEN(r')    [conflict]
  (다른 뱅크에 대한 접근은 현재 뱅크의 상태에 영향을 주지 않음)

작성자:  [Implementation Engineer]
날짜:    2026-03-11
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from .dram_mapping import DRAMMapper

# 센티넬 값: 뱅크의 row buffer가 비어있음 (열린 행 없음)
_EMPTY = -1


class RowBufferModel:
    """
    뱅크별 row buffer 상태 머신을 시뮬레이션한다.

    각 뱅크는 독립적으로 현재 열려있는 행(open row)을 추적한다.
    모든 뱅크는 EMPTY 상태로 시작한다.

    사용법:
        mapper = DRAMMapper()
        model  = RowBufferModel(mapper)
        event  = model.process_access(address)   # -> "hit" | "miss" | "conflict"
        stats  = model.get_stats()
    """

    def __init__(self, mapper: "DRAMMapper") -> None:
        """
        DRAMMapper를 사용해 RowBufferModel을 초기화한다.

        Args:
            mapper: 설정된 DRAMMapper 인스턴스.

        NUM_BANKS개의 독립적인 상태 머신을 생성하며, 모두 EMPTY 상태로 시작한다.
        """
        self._mapper    = mapper
        self._num_banks = mapper.get_num_banks()

        # 뱅크별 열린 행: _EMPTY는 해당 뱅크가 EMPTY 상태임을 의미
        self._open_row: List[int] = [_EMPTY] * self._num_banks

        # 전역 카운터
        self._hits      = 0
        self._misses    = 0
        self._conflicts = 0

        # 뱅크별 통계; 각 항목은 아래 키를 갖는 dict:
        #   total_accesses, hits, misses, conflicts, unique_rows (row_id 집합)
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

        # 최소 한 번 이상 접근된 bank_id 집합
        self._unique_banks: set = set()

    # ------------------------------------------------------------------
    # 핵심 접근 처리
    # ------------------------------------------------------------------

    def process_access(self, address: int) -> str:
        """
        단일 메모리 접근을 처리하고 상태 머신을 갱신한다.

        Args:
            address: 접근 대상 바이트 주소.

        Returns:
            "hit", "miss", "conflict" 중 하나.

        Raises:
            ValueError: address가 음수인 경우.
        """
        bank_id, row_id, _col = self._mapper.map(address)

        bs = self._bank_stats[bank_id]
        bs["total_accesses"] += 1
        bs["unique_rows"].add(row_id)
        self._unique_banks.add(bank_id)

        current = self._open_row[bank_id]

        if current == _EMPTY:
            # 전이 T1: EMPTY -> OPEN(row_id)  [miss]
            self._open_row[bank_id] = row_id
            self._misses           += 1
            bs["misses"]           += 1
            return "miss"
        elif current == row_id:
            # 전이 T2: OPEN(row_id) -> OPEN(row_id)  [hit]
            self._hits   += 1
            bs["hits"]   += 1
            return "hit"
        else:
            # 전이 T3: OPEN(r) + access(r') -> OPEN(r')  [conflict]
            self._open_row[bank_id] = row_id
            self._conflicts        += 1
            bs["conflicts"]        += 1
            return "conflict"

    # ------------------------------------------------------------------
    # 통계
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        """
        전체 뱅크에 대한 집계 통계를 반환한다.

        Returns:
            {
                "hits":            int,
                "misses":          int,
                "conflicts":       int,
                "total":           int,   # hits + misses + conflicts
                "hit_rate":        float, # hits / total (total == 0이면 0)
                "miss_rate":       float,
                "conflict_rate":   float,
                "locality_score":  float, # hit_rate - conflict_rate
                "unique_rows":     int,   # 접근된 고유 (bank_id, row_id) 쌍 수
                "unique_banks":    int,   # 접근된 고유 bank_id 수
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
        뱅크별 통계를 반환한다.

        Returns:
            뱅크별 dict 리스트 (bank_id 순서), 각 dict는 아래를 포함:
            {
                "bank_id":        int,
                "total_accesses": int,
                "hits":           int,
                "misses":         int,
                "conflicts":      int,
                "hit_rate":       float,
                "conflict_rate":  float,
                "unique_rows":    int,   # 이 뱅크에서 접근된 고유 row_id 수
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
    # 초기화
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """모든 뱅크 상태를 EMPTY로 초기화하고 카운터를 모두 지운다."""
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
    # 정보 조회
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        stats = self.get_stats()
        return (
            f"RowBufferModel(mapper={self._mapper!r}, "
            f"total={stats['total']}, hit_rate={stats['hit_rate']:.3f})"
        )


# ---------------------------------------------------------------------------
# 셀프 테스트 / 데모 블록
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from analysis.dram_mapping import DRAMMapper

    print("=== RowBufferModel Demo ===\n")

    mapper = DRAMMapper(row_size=8192, num_banks=8, scheme="sequential")
    model  = RowBufferModel(mapper)
    print(f"Mapper: {mapper}")
    print()

    # 순차 접근: 동일 행 내 모든 접근 -> 첫 miss 이후 전부 hit
    # Row 크기 = 8192바이트. 바이트 0..8191을 순서대로 접근.
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

    # 8192바이트마다 접근 -> 매번 새로운 행으로 이동 -> 처음엔 miss, 이후 conflict
    print("\n--- Row-strided access (stride = row_size, 16 rows) ---")
    # 뱅크0의 행0, 뱅크1의 행0, ... 순서로 접근. 8뱅크 기준으로
    # 처음 8번은 miss (각 뱅크의 첫 접근), 다음 8번은 conflict (같은 뱅크, 다른 행).
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

    # 동일 주소 반복 접근: 첫 miss 이후 전부 hit
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
