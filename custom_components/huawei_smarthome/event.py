"""Home Assistant event entities for Huawei wireless switch keys."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .device_registry import device_identifier, profile_configuration_url

_EVENT_TYPE = "pressed"
_EVENT_NAMES = {
    "single": "Single press",
    "double": "Double press",
    "long": "Long press",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one event entity for each supported key action."""

    del hass
    client = entry.runtime_data
    entities = []
    for device in client.hwiot_devices.values():
        for action in getattr(device, "button_event_actions", ()):
            entities.append(HuaweiSmartHomeButtonEvent(device, action))
    async_add_entities(entities)


class HuaweiSmartHomeButtonEvent(EventEntity):
    """Expose one wireless key action as an event entity."""

    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = [_EVENT_TYPE]
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, device: Any, action: str) -> None:
        self._device = device
        self._action = action
        self._attr_unique_id = (
            f"{device.home_id}_{device.dev_id}_event_{action}"
        )
        self._attr_name = _EVENT_NAMES.get(action, action)

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

    async def async_added_to_hass(self) -> None:
        self._device.add_event_listener(self._event_received)

    async def async_will_remove_from_hass(self) -> None:
        self._device.remove_event_listener(self._event_received)

    def _event_received(self, event: Any) -> None:
        if event.action != self._action:
            return
        self._trigger_event(
            _EVENT_TYPE,
            {
                "action": event.action,
                "button_id": event.button_id,
                "key_code": event.key_code,
                "name": event.name,
                "timestamp": event.timestamp,
            },
        )
        self.async_write_ha_state()
