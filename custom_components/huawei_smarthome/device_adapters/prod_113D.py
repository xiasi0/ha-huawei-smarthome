"""User-contributed protocol for Huawei product 113D (豪恩 温湿度传感器).

设备类型: 豪恩温湿度传感器 (Temperature And Humidity Detector)
用途: 温湿度传感器
核心服务:
   airDetector.temperature    int  R (-20-100°C)
   airDetector.humidity       int  R (0-100%RH)
   battery.lowBattery         bool R (0=无告警, 1=低电量告警)

本适配器暴霨三个 Home Assistant 实体：
- sensor.temperature       温度
- sensor.humidity          湿度
- binary_sensor.low_battery 低电量告警
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, str):
        try:
            return int(round(float(value.strip())))
        except (TypeError, ValueError):
            return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.casefold() in {"1", "true", "on"}:
            return True
        if value.casefold() in {"0", "false", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _temp_spec() -> EntitySpec:
    def state(device: DeviceContext) -> Mapping[str, Any]:
        value = _number(device.value("airDetector", "temperature")/100)
        if value is None:
            return {"native_value": None}
        return {"native_value": value}

    return EntitySpec(
        platform="sensor",
        key="temperature",
        name="温度",
        state=state,
        metadata={
            "device_class": "temperature",
            "unit": "°C",
            "state_class": "measurement",
        },
    )


def _humidity_spec() -> EntitySpec:
    def state(device: DeviceContext) -> Mapping[str, Any]:
        value = _number(device.value("airDetector", "humidity")/100)
        if value is None:
            return {"native_value": None}
        return {"native_value": value}

    return EntitySpec(
        platform="sensor",
        key="humidity",
        name="湿度",
        state=state,
        metadata={
            "device_class": "humidity",
            "unit": "%",
            "state_class": "measurement",
        },
    )


def _low_battery_spec() -> EntitySpec:
    def state(device: DeviceContext) -> Mapping[str, Any]:
        value = _as_bool(device.value("battery", "lowBattery"))
        if value is None:
            return {"is_on": None}
        return {"is_on": value}

    return EntitySpec(
        platform="binary_sensor",
        key="low_battery",
        name="低电量告警",
        state=state,
        metadata={"device_class": "battery"},
    )


class Product113DAdapter:
    """113D 豪恩温湿度传感器适配器：温度、湿度和低电量告警。"""

    prod_id = "113D"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None:
            return ()

        entities = []

        # Temperature sensor
        if context.has_service("airDetector"):
            # Check if temperature characteristic exists (optional, but we assume it does)
            entities.append(_temp_spec())
            # Humidity sensor
            entities.append(_humidity_spec())

        # Low battery binary sensor
        if context.has_service("battery"):
            entities.append(_low_battery_spec())

        return tuple(entities)


ADAPTER = Product113DAdapter()