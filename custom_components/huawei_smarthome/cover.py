"""Home Assistant cover projection for Huawei curtain motors."""

from __future__ import annotations

from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverEntity,
    CoverEntityFeature,
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
    """Create cover entities from instantiated product devices."""

    del hass
    client = entry.runtime_data
    async_add_entities(
        HuaweiSmartHomeCover(device)
        for device in client.hwiot_devices.values()
        if getattr(device, "ha_platform", None) == "cover"
    )


class HuaweiSmartHomeCover(CoverEntity):
    """Project one Huawei curtain motor as a Home Assistant cover."""

    def __init__(self, device: Any) -> None:
        self._device = device
        self._attr_unique_id = f"{device.home_id}_{device.dev_id}_cover"
        self._attr_name = getattr(device, "cover_entity_name", "Curtain")
        self._attr_has_entity_name = True
        self._attr_should_poll = False
        self._attr_supported_features = (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.STOP
            | CoverEntityFeature.SET_POSITION
        )

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
    def is_closed(self) -> bool | None:
        return self._device.is_closed

    @property
    def current_cover_position(self) -> int | None:
        return self._device.current_position

    async def async_added_to_hass(self) -> None:
        self._device.add_state_listener(self._state_changed)

    async def async_will_remove_from_hass(self) -> None:
        self._device.remove_state_listener(self._state_changed)

    async def async_open_cover(self, **kwargs: Any) -> None:
        del kwargs
        await self._device.async_open_cover()

    async def async_close_cover(self, **kwargs: Any) -> None:
        del kwargs
        await self._device.async_close_cover()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        del kwargs
        await self._device.async_stop_cover()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        position = kwargs.get(ATTR_POSITION)
        if position is None:
            raise ValueError("cover position is required")
        await self._device.async_set_cover_position(position)

    def _state_changed(self) -> None:
        self.async_write_ha_state()
