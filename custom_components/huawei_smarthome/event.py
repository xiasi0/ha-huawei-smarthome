"""Generic Home Assistant event registration for product adapters."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity_helpers import AdapterEntityMixin, iter_specs


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    del hass
    async_add_entities(HuaweiAdapterEvent(context, spec) for context, spec in iter_specs(entry.runtime_data, "event"))


class HuaweiAdapterEvent(AdapterEntityMixin, EventEntity):
    def __init__(self, context: Any, spec: Any) -> None:
        self._init_adapter_entity(context, spec)
        if spec.metadata.get("device_class"):
            self._attr_device_class = EventDeviceClass(spec.metadata["device_class"])
        self._attr_event_types = list(spec.metadata.get("event_types", ("event",)))
        # Latest marker per event type, used to tell what is new.  Adapters
        # report their outstanding events; the framework fires the difference.
        self._seen_events: dict[str, str] = {}
        # The first reading only establishes a baseline.  Whatever the device
        # last reported happened before Home Assistant started, so firing it
        # would announce a stale event as if it had just occurred.
        self._baseline_taken = False

    def trigger(self, event_type: str = "event", event_data: dict[str, Any] | None = None) -> None:
        self._trigger_event(event_type, event_data or {})

    def _state_changed(self) -> None:
        self._fire_new_events()
        self.async_write_ha_state()

    def _fire_new_events(self) -> None:
        """Trigger every event the adapter reports as newly outstanding.

        Adapters express one-shot occurrences through ``EntitySpec.events``
        because the cloud may push an occurrence once and never send the
        cleared value, so a state-only entity either latches on or loses the
        occurrence entirely.  Comparing against the previous reading lets the
        same occurrence fire once without the adapter owning any state.

        The reading is also skipped when it is not newer than the last one, so
        a re-delivered MQTT message cannot fire a duplicate event.
        """

        reader = getattr(self._spec, "events", None)
        if reader is None:
            return
        try:
            current = reader(self._device_context)
        except Exception:  # adapter errors must never break the HA event loop
            return
        if not isinstance(current, dict):
            return
        if not self._baseline_taken:
            self._baseline_taken = True
            for event_type, data in current.items():
                self._seen_events[event_type] = _event_marker(data)
            return
        for event_type, data in current.items():
            marker = _event_marker(data)
            if self._seen_events.get(event_type) == marker:
                continue
            self._seen_events[event_type] = marker
            self.trigger(event_type, dict(data) if isinstance(data, dict) else {})


def _event_marker(data: Any) -> str:
    """Return a value identifying one occurrence of an event.

    ``alarmId`` and ``id`` are the identifiers the cloud already assigns to an
    occurrence, so they are preferred; anything else falls back to the payload
    contents, which still distinguishes "a new event" from "the same one".
    """

    payload = data if isinstance(data, dict) else {}
    marker = payload.get("alarmId") or payload.get("id")
    if marker is None:
        marker = repr(sorted((str(k), str(v)) for k, v in payload.items()))
    return str(marker)
