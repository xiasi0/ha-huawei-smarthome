"""User-contributed protocol for Huawei product A3RC (美的 柜机空调).

设备类型: 柜机空调 (Cabinet Air Conditioner), 型号 KFR-51LW/N8MFA3
核心服务:
   switch.on            bool RW (1=开, 0=关)
   mode.mode            enum RW (1=自动,2=制冷,3=制热,4=送风,5=抽湿)
   fan.gear             enum RW (0=自动,2=低风,3=中风,4=高风,5=强劲风)
   fan.direction        enum RW (1=停止摆风,2=左右,3=上下,4=全面)
   temperature.target   float RW (17.0-30.0, step1)

本适配器暴露一个 Home Assistant ``climate`` 实体,
支持: 开关 / 模式 / 目标温度 / 风速 / 摆风.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_TEMP_MIN = 17.0
_TEMP_MAX = 30.0

# 设备 mode(1-5) <-> HA HVAC
_DEV_TO_HVAC = {1: "auto", 2: "cool", 3: "heat", 4: "fan_only", 5: "dry"}
_HVAC_TO_DEV = {v: k for k, v in _DEV_TO_HVAC.items()}

# 设备 fan.gear(0,2,3,4,5) <-> HA fan
_DEV_TO_FAN = {0: "auto", 2: "low", 3: "medium", 4: "high", 5: "strong"}
_FAN_TO_DEV = {v: k for k, v in _DEV_TO_FAN.items()}

# 设备 fan.direction(1-4) <-> HA swing
_DEV_TO_SWING = {1: "stop", 2: "horizontal", 3: "vertical", 4: "both"}
_SWING_TO_DEV = {v: k for k, v in _DEV_TO_SWING.items()}


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


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(int(value))
    try:
        return float(value)
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


async def _turn_on(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 1})


async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 0})


async def _set_hvac_mode(context: DeviceContext, data: Mapping[str, Any]) -> None:
    dev = _HVAC_TO_DEV.get(str(data.get("hvac_mode")))
    if dev is None:
        raise ValueError(f"unsupported hvac_mode: {data.get('hvac_mode')}")
    await context.async_send_service("mode", {"mode": dev})


async def _set_temperature(context: DeviceContext, data: Mapping[str, Any]) -> None:
    temp = data.get("temperature")
    if temp is None:
        return
    target = max(_TEMP_MIN, min(_TEMP_MAX, round(float(temp), 1)))
    await context.async_send_service("temperature", {"target": target})


async def _set_fan_mode(context: DeviceContext, data: Mapping[str, Any]) -> None:
    gear = _FAN_TO_DEV.get(str(data.get("fan_mode")))
    if gear is None:
        raise ValueError(f"unsupported fan_mode: {data.get('fan_mode')}")
    await context.async_send_service("fan", {"gear": gear})


async def _set_swing_mode(context: DeviceContext, data: Mapping[str, Any]) -> None:
    direction = _SWING_TO_DEV.get(str(data.get("swing_mode")))
    if direction is None:
        raise ValueError(f"unsupported swing_mode: {data.get('swing_mode')}")
    await context.async_send_service("fan", {"direction": direction})


class ProductA3RCAdapter:
    """A3RC 美的柜机空调适配器。"""

    prod_id = "A3RC"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service("mode"):
            return ()

        def climate_state(device: DeviceContext) -> Mapping[str, Any]:
            mode = _as_int(device.value("mode", "mode"))
            gear = _as_int(device.value("fan", "gear"))
            direction = _as_int(device.value("fan", "direction"))
            return {
                "target_temperature": _as_float(device.value("temperature", "target")),
                "hvac_mode": _DEV_TO_HVAC.get(mode, "auto"),
                "fan_mode": _DEV_TO_FAN.get(gear, "auto"),
                "swing_mode": _DEV_TO_SWING.get(direction, "stop"),
            }

        return (
            EntitySpec(
                platform="climate",
                key="air_conditioner",
                name=None,
                state=climate_state,
                metadata={
                    "hvac_modes": ["auto", "cool", "heat", "fan_only", "dry"],
                    "fan_modes": ["auto", "low", "medium", "high", "strong"],
                    "swing_modes": ["stop", "horizontal", "vertical", "both"],
                    "min_temp": _TEMP_MIN,
                    "max_temp": _TEMP_MAX,
                },
                actions={
                    "turn_on": _turn_on,
                    "turn_off": _turn_off,
                    "set_hvac_mode": _set_hvac_mode,
                    "set_temperature": _set_temperature,
                    "set_fan_mode": _set_fan_mode,
                    "set_swing_mode": _set_swing_mode,
                },
            ),
        )


ADAPTER = ProductA3RCAdapter()


