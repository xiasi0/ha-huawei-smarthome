"""Shared state application for supported SmartHome product devices."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from ..domain.models import RemoteServiceState


class HuaweiDeviceStateMixin:
    """Apply a normalized state snapshot to a product device."""

    def apply_state_snapshot(
        self,
        services: Mapping[str, RemoteServiceState],
        *,
        online: bool | None = None,
    ) -> bool:
        """Merge state by service timestamp and notify listeners once."""

        changed = False
        for sid, service in services.items():
            timestamp = service.reported_timestamp
            previous_timestamp = self._state_timestamps.get(sid)
            if (
                timestamp
                and previous_timestamp
                and timestamp < previous_timestamp
            ):
                continue
            before = self._state.get(sid, {})
            after = {**before, **dict(service.data)}
            if after != before:
                self._state[sid] = after
                changed = True
            if timestamp and timestamp != previous_timestamp:
                self._state_timestamps[sid] = timestamp

        if online is not None and online != self._descriptor.online:
            self._descriptor = replace(self._descriptor, online=online)
            changed = True
        if changed:
            self._notify_state_changed()
        return changed
