"""Generic Home Assistant sensor registration for product adapters."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity_helpers import device_info, entity_available, iter_specs


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
        return entity_available(self._device_context, self._spec)

    @property
    def native_value(self) -> Any:
        return self._spec.state(self._device_context).get("native_value")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        # Everything the adapter returns besides native_value rides along as an
        # attribute.  Event-driven specs use this to publish a per-event id next
        # to a latched state value, so automations can trigger on the attribute
        # changing while the state keeps naming the last value.
        state = self._spec.state(self._device_context)
        return {key: value for key, value in state.items() if key != "native_value"}

    async def async_added_to_hass(self) -> None:
        self._device_context.add_state_listener(self._state_changed)

    async def async_will_remove_from_hass(self) -> None:
        self._device_context.remove_state_listener(self._state_changed)

    def _state_changed(self) -> None:
        self.async_write_ha_state()
