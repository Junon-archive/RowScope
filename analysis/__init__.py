"""
RowScope Analysis Package
=========================
Project: RowScope — DRAM Row Buffer Locality Analyzer
File:    analysis/__init__.py
Purpose: Package initialization.  Exposes the two core model classes so
         callers can do:
             from analysis import DRAMMapper, RowBufferModel
Author:  [Implementation Engineer]
Date:    2026-03-11
"""

from .dram_mapping import DRAMMapper
from .row_buffer_model import RowBufferModel

__all__ = ["DRAMMapper", "RowBufferModel"]
