"""Shared asyncio locks for Home Assistant Store read-modify-write operations."""

from __future__ import annotations

import asyncio


_LOCKS: dict[str, asyncio.Lock] = {}


def storage_lock(key: str) -> asyncio.Lock:
    """Return the process-local lock for one Store key."""

    lock = _LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS[key] = lock
    return lock
