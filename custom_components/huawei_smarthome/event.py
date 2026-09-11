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

    def trigger(self, event_type: str = "event", event_data: dict[str, Any] | None = None) -> None:
        self._trigger_event(event_type, event_data or {})
