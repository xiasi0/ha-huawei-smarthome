"""Home Assistant select projection for supported Huawei products."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
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
    """Create select entities from instantiated product devices."""

    del hass
    client = entry.runtime_data
    entities = []
    for device in client.hwiot_devices.values():
        names = getattr(device, "select_names", {})
        options_by_key = getattr(device, "select_options", {})
        for key in getattr(device, "select_keys", ()):
            options = options_by_key.get(key, ())
            if not options:
                continue
            entities.append(
                HuaweiSmartHomeSelect(
                    device,
                    key,
                    names.get(key, key),
                    options,
                )
            )
    async_add_entities(entities)


class HuaweiSmartHomeSelect(SelectEntity):
    """Project one writable product enum as a Home Assistant select."""

    def __init__(
        self,
        device: Any,
        key: str,
        name: str,
        options: tuple[str, ...],
    ) -> None:
        self._device = device
        self._key = key
        self._attr_unique_id = f"{device.home_id}_{device.dev_id}_{key}"
        self._attr_name = name
        self._attr_options = list(options)
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
    def current_option(self) -> str | None:
        return self._device.select_value(self._key)

    async def async_added_to_hass(self) -> None:
        self._device.add_state_listener(self._state_changed)

    async def async_will_remove_from_hass(self) -> None:
        self._device.remove_state_listener(self._state_changed)

    async def async_select_option(self, option: str) -> None:
        await self._device.async_select_option(self._key, option)

    def _state_changed(self) -> None:
        self.async_write_ha_state()
