"""Home Assistant fan projection for supported Huawei air purifiers."""

from __future__ import annotations

from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
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
    """Create fan entities from instantiated product devices."""

    del hass
    client = entry.runtime_data
    async_add_entities(
        HuaweiSmartHomeFan(device)
        for device in client.hwiot_devices.values()
        if getattr(device, "ha_platform", None) == "fan"
    )


class HuaweiSmartHomeFan(FanEntity):
    """Project one Huawei air purifier as a Home Assistant fan."""

    def __init__(self, device: Any) -> None:
        self._device = device
        self._attr_unique_id = f"{device.home_id}_{device.dev_id}_fan"
        self._attr_name = getattr(device, "fan_entity_name", "Air purifier")
        self._attr_has_entity_name = True
        self._attr_should_poll = False
        self._attr_supported_features = (
            FanEntityFeature.SET_SPEED | FanEntityFeature.PRESET_MODE
        )
        self._attr_percentage_step = device.percentage_step

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
        return self._device.is_on

    @property
    def percentage(self) -> int | None:
        return self._device.percentage

    @property
    def preset_modes(self) -> tuple[str, ...]:
        return self._device.preset_modes

    @property
    def preset_mode(self) -> str | None:
        return self._device.preset_mode

    async def async_added_to_hass(self) -> None:
        self._device.add_state_listener(self._state_changed)

    async def async_will_remove_from_hass(self) -> None:
        self._device.remove_state_listener(self._state_changed)

    async def async_turn_on(self, **kwargs: Any) -> None:
        percentage = kwargs.pop("percentage", None)
        preset_mode = kwargs.pop("preset_mode", None)
        del kwargs
        await self._device.async_turn_on()
        if preset_mode is not None:
            await self._device.async_set_preset_mode(preset_mode)
        if percentage is not None:
            await self._device.async_set_percentage(percentage)

    async def async_turn_off(self, **kwargs: Any) -> None:
        del kwargs
        await self._device.async_turn_off()

    async def async_set_percentage(self, percentage: int) -> None:
        await self._device.async_set_percentage(percentage)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        await self._device.async_set_preset_mode(preset_mode)

    def _state_changed(self) -> None:
        self.async_write_ha_state()
