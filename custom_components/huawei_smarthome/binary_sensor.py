"""Home Assistant binary sensor projection for supported Huawei products."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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
    """Create binary sensors from instantiated product devices."""

    del hass
    client = entry.runtime_data
    async_add_entities(
        HuaweiSmartHomePresenceSensor(device)
        for device in client.hwiot_devices.values()
        if getattr(device, "ha_platform", None) == "binary_sensor"
    )


class HuaweiSmartHomePresenceSensor(BinarySensorEntity):
    """Project one Huawei presence sensor as an occupancy binary sensor."""

    def __init__(self, device: Any) -> None:
        self._device = device
        self._attr_unique_id = f"{device.home_id}_{device.dev_id}_presence"
        self._attr_name = "Presence"
        self._attr_device_class = BinarySensorDeviceClass.OCCUPANCY
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
    def is_on(self) -> bool | None:
        return self._device.is_present

    async def async_added_to_hass(self) -> None:
        self._device.add_state_listener(self._state_changed)

    async def async_will_remove_from_hass(self) -> None:
        self._device.remove_state_listener(self._state_changed)

    def _state_changed(self) -> None:
        self.async_write_ha_state()
