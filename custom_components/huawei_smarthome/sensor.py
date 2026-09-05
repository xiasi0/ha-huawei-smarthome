"""Home Assistant sensor projection for supported Huawei products."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .device_registry import device_identifier, profile_configuration_url

_SENSOR_NAMES = {
    "current": "Current",
    "consumption": "Consumption",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create energy sensors from instantiated product devices."""

    del hass
    client = entry.runtime_data
    entities = []
    for device in client.hwiot_devices.values():
        for key in getattr(device, "energy_sensor_keys", ()):
            name = _SENSOR_NAMES.get(key)
            if name is not None:
                entities.append(HuaweiSmartHomeSensor(device, key, name))
    async_add_entities(entities)


class HuaweiSmartHomeSensor(SensorEntity):
    """Project one raw product energy characteristic as a sensor."""

    def __init__(self, device: Any, key: str, name: str) -> None:
        self._device = device
        self._key = key
        self._attr_unique_id = f"{device.home_id}_{device.dev_id}_{key}"
        self._attr_name = name
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
            configuration_url=profile_configuration_url(self._device.prod_id),
        )

    @property
    def available(self) -> bool:
        return self._device.available

    @property
    def native_value(self) -> int | None:
        return getattr(self._device, self._key)

    async def async_added_to_hass(self) -> None:
        self._device.add_state_listener(self._state_changed)

    async def async_will_remove_from_hass(self) -> None:
        self._device.remove_state_listener(self._state_changed)

    def _state_changed(self) -> None:
        self.async_write_ha_state()
