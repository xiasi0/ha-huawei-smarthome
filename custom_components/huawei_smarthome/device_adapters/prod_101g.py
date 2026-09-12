"""User-contributed protocol for Huawei product 101g (红外人体感应传感器).

设备类型: 红外人体感应传感器 (PIR Motion Detector)
制造商: 中安消物联传感, 型号 LH-990ZB
核心服务:
   motionSensor.alarm    int R   (0=无, 1=有人移动)
   battery.lowBattery    int R   (0=正常, 1=低电量)
   battery.capacity      int R   (0-100 电量%)

本适配器暴露:
   1. binary_sensor 人体移动 (device_class=motion)
   2. binary_sensor 低电量   (device_class=battery)
   3. sensor        电量     (unit=%)
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext


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


class Product101GLegacyAdapter:
    """101g 人体红外(1代)适配器。"""

    prod_id = "101G"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service("motionSensor"):
            return ()

        def motion_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"is_on": _as_bool(device.value("motionSensor", "alarm"))}

        def battery_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"is_on": _as_bool(device.value("battery", "lowBattery"))}

        def capacity_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"native_value": _as_int(device.value("battery", "capacity"))}

        return (
            EntitySpec(
                platform="binary_sensor",
                key="motion",
                name="人体移动",
                state=motion_state,
                metadata={"device_class": "motion"},
            ),
            EntitySpec(
                platform="binary_sensor",
                key="battery",
                name="低电量",
                state=battery_state,
                metadata={"device_class": "battery"},
            ),
            EntitySpec(
                platform="sensor",
                key="capacity",
                name="电量",
                state=capacity_state,
                metadata={"unit": "%"},
            ),
        )


ADAPTER = Product101GLegacyAdapter()


