"""Home Assistant sensor projection for supported Huawei products."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .device_registry import device_identifier, profile_configuration_url

_SENSOR_METADATA = {
    # The 124U H5 profile calls power/current "当前功率" and renders W.
    "current": (
        "Power",
        SensorDeviceClass.POWER,
        UnitOfPower.WATT,
        SensorStateClass.MEASUREMENT,
        1.0,
    ),
    # H5 daily statistics are displayed in kWh and divide the raw Wh value
    # by 1000 before rendering it.
    "consumption": (
        "Energy consumption",
        SensorDeviceClass.ENERGY,
        UnitOfEnergy.KILO_WATT_HOUR,
        SensorStateClass.TOTAL_INCREASING,
        0.001,
    ),
    "pm2p5": (
        "PM2.5",
        SensorDeviceClass.PM25,
        "µg/m³",
        SensorStateClass.MEASUREMENT,
        1.0,
    ),
    "filter_remaining": (
        "Filter remaining",
        None,
        PERCENTAGE,
        SensorStateClass.MEASUREMENT,
        1.0,
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create sensors from instantiated product devices."""

    del hass
    client = entry.runtime_data
    entities = []
    for device in client.hwiot_devices.values():
        for key in getattr(device, "energy_sensor_keys", ()):
            metadata = _SENSOR_METADATA.get(key)
            if metadata is not None:
                entities.append(HuaweiSmartHomeSensor(device, key, metadata))
        for key in getattr(device, "sensor_keys", ()):
            metadata = _SENSOR_METADATA.get(key)
            if metadata is not None:
                entities.append(HuaweiSmartHomeSensor(device, key, metadata))
    async_add_entities(entities)


class HuaweiSmartHomeSensor(SensorEntity):
    """Project one raw product energy characteristic as a sensor."""

    def __init__(self, device: Any, key: str, metadata: tuple[Any, ...]) -> None:
        self._device = device
        self._key = key
        name, device_class, unit, state_class, self._value_scale = metadata
        self._attr_unique_id = f"{device.home_id}_{device.dev_id}_{key}"
        self._attr_name = name
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = state_class
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
    def native_value(self) -> int | float | None:
        value = getattr(self._device, self._key)
        if value is None or self._value_scale == 1.0:
            return value
        return value * self._value_scale

    async def async_added_to_hass(self) -> None:
        self._device.add_state_listener(self._state_changed)

    async def async_will_remove_from_hass(self) -> None:
        self._device.remove_state_listener(self._state_changed)

    def _state_changed(self) -> None:
        self.async_write_ha_state()
