"""Home Assistant number projection for supported Huawei products."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .device_registry import device_identifier, profile_configuration_url


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create number entities from instantiated product devices."""

    del hass
    client = entry.runtime_data
    entities = []
    for device in client.hwiot_devices.values():
        metadata_by_key = getattr(device, "number_metadata", {})
        for key in getattr(device, "number_keys", ()):
            metadata = metadata_by_key.get(key)
            if metadata is None:
                continue
            entities.append(HuaweiSmartHomeNumber(device, key, metadata))
    async_add_entities(entities)


class HuaweiSmartHomeNumber(NumberEntity):
    """Project one writable product number as a Home Assistant number."""

    def __init__(
        self,
        device: Any,
        key: str,
        metadata: tuple[str, float, float, float, str | None],
    ) -> None:
        self._device = device
        self._key = key
        (
            name,
            minimum,
            maximum,
            step,
            unit,
        ) = metadata
        self._attr_unique_id = f"{device.home_id}_{device.dev_id}_{key}"
        self._attr_name = name
        self._attr_native_min_value = minimum
        self._attr_native_max_value = maximum
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit
        self._attr_has_entity_name = True
        self._attr_should_poll = False

    @property
    def device_info(self) -> DeviceInfo:
        """Return the shared HA device identity."""

        return DeviceInfo(
            identifiers={device_identifier(self._device.descriptor)},
            name=self._device.name,
            manufacturer=self._device.manufacturer,
            model=self._device.model,
            sw_version=self._device.firmware_version,
            configuration_url=profile_configuration_url(
                self._device.prod_id,
            ),
        )

    @property
    def available(self) -> bool:
        return self._device.available

    @property
    def native_value(self) -> float | None:
        return self._device.number_value(self._key)

    async def async_added_to_hass(self) -> None:
        self._device.add_state_listener(self._state_changed)

    async def async_will_remove_from_hass(self) -> None:
        self._device.remove_state_listener(self._state_changed)

    async def async_set_native_value(self, value: float) -> None:
        await self._device.async_set_number(self._key, value)

    def _state_changed(self) -> None:
        self.async_write_ha_state()
