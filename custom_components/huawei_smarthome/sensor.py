"""Generic Home Assistant sensor registration for product adapters."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity_helpers import device_info, iter_specs


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    del hass
    async_add_entities(
        HuaweiAdapterSensor(context, spec)
        for context, spec in iter_specs(entry.runtime_data, "sensor")
    )


class HuaweiAdapterSensor(SensorEntity):
    def __init__(self, context: Any, spec: Any) -> None:
        self._device_context = context
        self._spec = spec
        metadata = spec.metadata
        self._attr_unique_id = f"{context.home_id}_{context.dev_id}_{spec.key}"
        self._attr_name = spec.name or spec.key
        self._attr_native_unit_of_measurement = metadata.get("unit")
        if metadata.get("device_class"):
            self._attr_device_class = SensorDeviceClass(metadata["device_class"])
        if metadata.get("state_class"):
            self._attr_state_class = SensorStateClass(metadata["state_class"])
        self._attr_has_entity_name = True
        self._attr_should_poll = False

    @property
    def device_info(self):
        return device_info(self._device_context)

    @property
    def available(self) -> bool:
        return self._device_context.available

    @property
    def native_value(self) -> Any:
        return self._spec.state(self._device_context).get("native_value")

    async def async_added_to_hass(self) -> None:
        self._device_context.add_state_listener(self._state_changed)

    async def async_will_remove_from_hass(self) -> None:
        self._device_context.remove_state_listener(self._state_changed)

    def _state_changed(self) -> None:
        self.async_write_ha_state()
