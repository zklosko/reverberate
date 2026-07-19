"""
In-memory model for ETC Echo's EII module.

This is the single source of truth that both the UDP listener (writer)
and the FastAPI routes touch. Everything is guarded by asyncio.Lock.
"""

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Any, Deque, Dict, Optional, Union
from enum import Enum

class EomOption(Enum):
    CR = "\r"
    LF = "\n"
    CRLF = "\r\n"
    # TODO: more once you remember


@dataclass
class PacketLogEntry:
    direction: str          # "rx" or "tx"
    timestamp: float
    addr: str
    raw: bytes
    parsed: Optional[Dict[str, Any]] = None
    # note: Optional[str] = None  # e.g. "dropped", "malformed reply", "delayed 500ms"


@dataclass
class Space:
    """Type definations for a SINGLE space."""
    active_preset: int = 0
    zones: Dict[int, int] = field(default_factory=lambda: {i: 0 for i in range(1, 17)})
    sequences: Dict[int, bool] = field(default_factory=lambda: {i: False for i in range(1, 5)})


@dataclass
class FixtureState:
    # "Fixtures" track intensities, active preset, and sequence status (on/off)
    # Presets are 1-64, or 0 if current state does not match a preset
    # Intensities are 8-bit integers, 0-255
    spaces: Dict[int, Space] = field(default_factory=lambda: {i: Space() for i in range(1, 17)})

    log: Deque[PacketLogEntry] = field(default_factory=lambda: deque(maxlen=500))

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    eom: EomOption = EomOption.CR  # set EOL character here

    async def record(self, entry: PacketLogEntry) -> None:
        async with self.lock:
            self.log.append(entry)

    async def snapshot(self) -> Dict[str, Any]:
        async with self.lock:
            clean_spaces = {key: asdict(value) for key, value in self.spaces.items()}
            return {
                "spaces": clean_spaces,
            }

    async def recent_log(self, n: int = 50):
        async with self.lock:
            return list(self.log)[-n:]
    
    # State setting methods
    async def set_active_preset(self, space_num: int, preset: int) -> None:
        async with self.lock:
            if space_num not in self.spaces:
                raise ValueError(f"Invalid space number: {space_num}")
            if preset not in range(1, 65):
                raise ValueError(f"Invalid preset number: {preset}")
            self.spaces[space_num].active_preset = preset

    async def set_space_off(self, space_num: int) -> None:
        async with self.lock:
            if space_num not in self.spaces:
                raise ValueError(f"Invalid space number: {space_num}")
            space = self.spaces[space_num]
            for zone in space.zones:
                space.zones[zone] = 0
            space.active_preset = 0
            # TODO: does this affect sequences too?

    async def set_seq(self, space_num: int, seq_num: int, active: bool) -> None:
        async with self.lock:
            if space_num not in self.spaces:
                raise ValueError(f"Invalid space number: {space_num}")
            if seq_num not in range(1, 5):
                raise ValueError(f"Invalid sequence number: {seq_num}")
            space = self.spaces[space_num]
            space.sequences[seq_num] = active

    async def set_zone_int(self, space_num: int, zone_num: int, level: int) -> None:
        async with self.lock:
            if space_num not in self.spaces:
                raise ValueError(f"Invalid space number: {space_num}")
            if zone_num not in range(1, 17):
                raise ValueError(f"Invalid zone number: {zone_num}")
            if level not in range(0, 256):
                raise ValueError(f"Invalid level value: {level}")
            space = self.spaces[space_num]
            space.zones[zone_num] = level


fixture_state = FixtureState()
