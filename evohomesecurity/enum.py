"""Enumerated entities evohomesecurity API library."""

from enum import Enum


class PanelState(Enum):
    """Panel status enum"""
    DISARM = 100
    FULL_ARM = 101
    PARTIAL_ARM = 102
    UNKNOWN = 0
