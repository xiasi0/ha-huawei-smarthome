"""Shared state application for supported SmartHome product devices."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from ..domain.models import RemoteServiceState, is_older_remote_timestamp


class HuaweiDeviceStateMixin:
    """Apply a normalized state snapshot to a product device."""

    state_services: frozenset[str] | None = None

    def _merge_service_state(
        self,
        sid: str,
        data: Mapping[str, Any],
        timestamp: str | None = None,
    ) -> bool:
        """Merge one service update without notifying listeners."""

        allowed_services = self.state_services
        if allowed_services is not None and sid not in allowed_services:
            return False
        timestamp = (
            timestamp
            if isinstance(timestamp, str) and timestamp
            else None
        )
        previous_timestamp = self._state_timestamps.get(sid)
        if is_older_remote_timestamp(timestamp, previous_timestamp):
            return False
        before = self._state.get(sid, {})
        after = {**before, **dict(data)}
        changed = after != before
        if changed:
            self._state[sid] = after
        if timestamp and timestamp != previous_timestamp:
            self._state_timestamps[sid] = timestamp
        return changed

    def apply_state_snapshot(
        self,
        services: Mapping[str, RemoteServiceState],
        *,
        online: bool | None = None,
    ) -> bool:
        """Merge state by service timestamp and notify listeners once."""

        changed = False
        for sid, service in services.items():
            changed = (
                self._merge_service_state(
                    sid,
                    service.data,
                    service.reported_timestamp,
                )
                or changed
            )

        if online is not None and online != self._descriptor.online:
            self._descriptor = replace(self._descriptor, online=online)
            changed = True
        if changed:
            self._notify_state_changed()
        return changed
