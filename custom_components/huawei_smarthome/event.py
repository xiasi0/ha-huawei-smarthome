"""Generic Home Assistant event registration for product adapters."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity_helpers import AdapterEntityMixin, iter_specs

_LOGGER = logging.getLogger(__name__)


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
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._device_context.add_service_update_listener(
            self._service_update_received
        )

    async def async_will_remove_from_hass(self) -> None:
        self._device_context.remove_service_update_listener(
            self._service_update_received
        )
        await super().async_will_remove_from_hass()

    def _service_update_received(
        self,
        sid: str,
        data: Mapping[str, Any],
        timestamp: str | None,
    ) -> None:
        decoder = self._spec.event_decoder
        if decoder is None:
            return
        try:
            events = decoder(self._device_context, sid, data, timestamp)
            for event_type, event_data in events:
                self.trigger(event_type, dict(event_data))
        except Exception:  # noqa: BLE001 - adapter events must not break MQTT
            _LOGGER.exception(
                "Huawei SmartHome event decoder failed: prod_id=%s "
                "entity=%s sid=%s",
                self._device_context.prod_id,
                self.entity_id,
                sid,
            )
