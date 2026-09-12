"""User-contributed protocol for Huawei product 2QTT (箭牌 浴霸).

设备类型: 浴霸 (Bath Heater), 型号 AQW002HM-T
核心服务(本次使用的):
   lightSwitch.on          bool RW  照明
   ventilateSwitch.on      bool RW  换气
   windSwitch.on           bool RW  吹风
   drySwitch.on            bool RW  干燥
   deodorization.on        bool RW  除臭
   nightLightSwitch.on     bool RW  夜灯
   humidity.current        int  R  (0-100 %)   湿度
   heat.current            float R (温度 ℃)    当前温度
   humanSensingStatus.status enum R (0=无人,1=有人) 人在

本适配器暴露:
   6 个 switch (照明/换气/吹风/干燥/除臭/夜灯)
   + 湿度 sensor + 温度 sensor + 人在 binary_sensor
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_SWITCHES = [
    ("lightSwitch", "照明"),
    ("ventilateSwitch", "换气"),
    ("windSwitch", "吹风"),
    ("drySwitch", "干燥"),
    ("deodorization", "除臭"),
    ("nightLightSwitch", "夜灯"),
]


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


class Product2QTTAdapter:
    """2QTT 箭牌浴霸适配器。"""

    prod_id = "2QTT"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service("lightSwitch"):
            return ()

        def _switch_spec(sid: str, label: str) -> EntitySpec:
            def state(device: DeviceContext) -> Mapping[str, Any]:
                return {"is_on": _as_bool(device.value(sid, "on"))}

            async def turn_on(device: DeviceContext, _data: Mapping[str, Any]) -> None:
                await device.async_send_service(sid, {"on": 1})

            async def turn_off(device: DeviceContext, _data: Mapping[str, Any]) -> None:
                await device.async_send_service(sid, {"on": 0})

            return EntitySpec(
                platform="switch",
                key=sid,
                name=label,
                state=state,
                actions={"turn_on": turn_on, "turn_off": turn_off},
            )

        def humidity_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"native_value": _as_int(device.value("humidity", "current"))}

        def temp_state(device: DeviceContext) -> Mapping[str, Any]:
            value = device.value("heat", "current")
            return {"native_value": _as_int(value) if value is not None else None}

        def presence_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"is_on": _as_int(device.value("humanSensingStatus", "status")) == 1}

        specs = [_switch_spec(sid, label) for sid, label in _SWITCHES]
        specs.append(
            EntitySpec(
                platform="sensor",
                key="humidity",
                name="湿度",
                state=humidity_state,
                metadata={"unit": "%", "device_class": "humidity"},
            )
        )
        specs.append(
            EntitySpec(
                platform="sensor",
                key="temperature",
                name="温度",
                state=temp_state,
                metadata={"unit": "°C", "device_class": "temperature"},
            )
        )
        specs.append(
            EntitySpec(
                platform="binary_sensor",
                key="presence",
                name="人在",
                state=presence_state,
                metadata={"device_class": "occupancy"},
            )
        )
        return tuple(specs)


ADAPTER = Product2QTTAdapter()


