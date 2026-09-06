"""Home Assistant switch projection for supported Huawei products."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
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
    """Create switch entities from instantiated product devices."""

    del hass
    client = entry.runtime_data
    entities = []
    for device in client.hwiot_devices.values():
        if (
            getattr(device, "ha_platform", None) == "switch"
            and getattr(device, "expose_aggregate_switch", True)
        ):
            entities.append(HuaweiSmartHomeSwitch(device))
        for key in getattr(device, "switch_keys", ()):
            entities.append(
                HuaweiSmartHomeFeatureSwitch(
                    device,
                    key,
                    getattr(device, "switch_names", {}).get(key, key),
                )
            )
    async_add_entities(entities)


class HuaweiSmartHomeSwitch(SwitchEntity):
    """Project one product device as a Home Assistant switch."""

    def __init__(self, device: Any) -> None:
        self._device = device
        self._attr_unique_id = f"{device.home_id}_{device.dev_id}_switch"
        self._attr_name = "Socket"
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
        return self._device.is_on

    async def async_added_to_hass(self) -> None:
        self._device.add_state_listener(self._state_changed)

    async def async_will_remove_from_hass(self) -> None:
        self._device.remove_state_listener(self._state_changed)

    async def async_turn_on(self, **kwargs: Any) -> None:
        del kwargs
        await self._device.async_turn_on()

    async def async_turn_off(self, **kwargs: Any) -> None:
        del kwargs
        await self._device.async_turn_off()

    def _state_changed(self) -> None:
        self.async_write_ha_state()


class HuaweiSmartHomeFeatureSwitch(SwitchEntity):
    """Project one writable product feature as a Home Assistant switch."""

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
    def is_on(self) -> bool | None:
        return self._device.feature_is_on(self._key)

    async def async_added_to_hass(self) -> None:
        self._device.add_state_listener(self._state_changed)

    async def async_will_remove_from_hass(self) -> None:
        self._device.remove_state_listener(self._state_changed)

    async def async_turn_on(self, **kwargs: Any) -> None:
        del kwargs
        await self._device.async_set_feature(self._key, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        del kwargs
        await self._device.async_set_feature(self._key, False)

    def _state_changed(self) -> None:
        self.async_write_ha_state()
