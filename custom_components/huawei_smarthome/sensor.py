"""Home Assistant sensor projection for supported Huawei products."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfTemperature,
    LIGHT_LUX,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .device_registry import device_identifier, profile_configuration_url

_SENSOR_METADATA = {
    "energy_consumption": (
        "Energy consumption",
        None,
        None,
        SensorStateClass.TOTAL_INCREASING,
        1.0,
    ),
    "pm2p5": (
        "PM2.5",
        SensorDeviceClass.PM25,
        "µg/m³",
        SensorStateClass.MEASUREMENT,
        1.0,
    ),
    "co2": (
        "Carbon dioxide",
        SensorDeviceClass.CO2,
        "ppm",
        SensorStateClass.MEASUREMENT,
        1.0,
    ),
    "formaldehyde": (
        "Formaldehyde",
        None,
        "mg/m³",
        SensorStateClass.MEASUREMENT,
        1.0,
    ),
    "gas_concentration": (
        "Gas concentration",
        None,
        None,
        SensorStateClass.MEASUREMENT,
        1.0,
    ),
    "temperature": (
        "Temperature",
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
        SensorStateClass.MEASUREMENT,
        1.0,
    ),
    "humidity": (
        "Humidity",
        SensorDeviceClass.HUMIDITY,
        PERCENTAGE,
        SensorStateClass.MEASUREMENT,
        1.0,
    ),
    "power": (
        "Current power",
        None,
        None,
        SensorStateClass.MEASUREMENT,
        1.0,
    ),
    "electric_current": (
        "Current",
        None,
        None,
        SensorStateClass.MEASUREMENT,
        1.0,
    ),
    "voltage": (
        "Voltage",
        None,
        None,
        SensorStateClass.MEASUREMENT,
        1.0,
    ),
    "battery_level": (
        "Battery",
        SensorDeviceClass.BATTERY,
        PERCENTAGE,
        SensorStateClass.MEASUREMENT,
        1.0,
    ),
    "speaker_state": (
        "Speaker state",
        None,
        None,
        None,
        1.0,
    ),
    "illuminance": (
        "Illuminance",
        SensorDeviceClass.ILLUMINANCE,
        LIGHT_LUX,
        SensorStateClass.MEASUREMENT,
        1.0,
    ),
    "tds": (
        "Total dissolved solids",
        None,
        "ppm",
        SensorStateClass.MEASUREMENT,
        1.0,
    ),
}
_PROFILE_UNIT_DEVICE_CLASSES = {
    "electric_current": SensorDeviceClass.CURRENT,
    "energy_consumption": SensorDeviceClass.ENERGY,
    "power": SensorDeviceClass.POWER,
    "voltage": SensorDeviceClass.VOLTAGE,
}


def _with_profile_metadata(
    metadata: tuple[Any, ...],
    unit: str | None,
    name: str | None,
    key: str,
) -> tuple[Any, ...]:
    """Prefer explicit Profile labels and units over semantic fallbacks."""

    profile_device_class = _PROFILE_UNIT_DEVICE_CLASSES.get(key)
    if not unit and not name and profile_device_class is None:
        return metadata
    return (
        name or metadata[0],
        profile_device_class if profile_device_class is not None and unit else metadata[1],
        unit if profile_device_class is not None else unit or metadata[2],
        metadata[3],
        metadata[4],
    )


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
        for key in device.sensor_keys:
            metadata = _SENSOR_METADATA.get(key)
            if metadata is not None:
                metadata = _with_profile_metadata(
                    metadata,
                    device.sensor_units.get(key),
                    device.sensor_names.get(key),
                    key,
                )
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
    def native_value(self) -> str | int | float | None:
        value = self._device.sensor_value(self._key)
        if value is None or self._value_scale == 1.0:
            return value
        return value * self._value_scale

    async def async_added_to_hass(self) -> None:
        self._device.add_state_listener(self._state_changed)

    async def async_will_remove_from_hass(self) -> None:
        self._device.remove_state_listener(self._state_changed)

    def _state_changed(self) -> None:
        self.async_write_ha_state()
