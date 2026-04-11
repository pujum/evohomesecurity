"""Data classes for evohomesecurity API library."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Event:
    """Dataclass for event data"""
    id: int
    message: str | None = None
    timestamp: datetime | None = None
    picture_id: int | None = None
