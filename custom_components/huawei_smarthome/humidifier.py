"""Home Assistant humidifier projection for Profile-backed devices."""

from __future__ import annotations

from typing import Any

from homeassistant.components.humidifier import (
    HumidifierEntity,
    HumidifierEntityFeature,
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
    """Create humidifiers from Profile-backed runtime compositions."""

    del hass
    client = entry.runtime_data
    async_add_entities(
        HuaweiSmartHomeHumidifier(device)
        for device in client.hwiot_devices.values()
        if "humidifier" in device.ha_platforms
    )


class HuaweiSmartHomeHumidifier(HumidifierEntity):
    """Project one Profile-backed humidifier."""

    def __init__(self, device: Any) -> None:
        self._device = device
        self._attr_unique_id = f"{device.home_id}_{device.dev_id}_humidifier"
        self._attr_name = "Humidifier"
        self._attr_has_entity_name = True
        self._attr_should_poll = False
        self._attr_supported_features = HumidifierEntityFeature.MODES if device.humidifier_modes else HumidifierEntityFeature(0)
        self._attr_available_modes = list(device.humidifier_modes)
        if device.min_target_humidity is not None:
            self._attr_min_humidity = device.min_target_humidity
        if device.max_target_humidity is not None:
            self._attr_max_humidity = device.max_target_humidity

    @property
    def device_info(self) -> DeviceInfo:
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
        return self._device.humidifier_is_on

    @property
    def current_humidity(self) -> int | None:
        return self._device.current_humidity

    @property
    def target_humidity(self) -> int | None:
        return self._device.target_humidity

    @property
    def mode(self) -> str | None:
        return self._device.humidifier_mode

    async def async_added_to_hass(self) -> None:
        self._device.add_state_listener(self._state_changed)

    async def async_will_remove_from_hass(self) -> None:
        self._device.remove_state_listener(self._state_changed)

    async def async_turn_on(self, **kwargs: Any) -> None:
        del kwargs
        await self._device.async_humidifier_turn_on()

    async def async_turn_off(self, **kwargs: Any) -> None:
        del kwargs
        await self._device.async_humidifier_turn_off()

    async def async_set_humidity(self, humidity: int) -> None:
        await self._device.async_set_humidity(humidity)

    async def async_set_mode(self, mode: str) -> None:
        await self._device.async_set_humidifier_mode(mode)

    def _state_changed(self) -> None:
        self.async_write_ha_state()
