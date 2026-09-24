"""User-contributed protocol for Huawei product A0CP (格力智能空调).

产品: 智能空调
厂商: 格力
型号: deviceTypeId 012 / platform GreeEco (protocolType WiFi)

═══════════════════════════════════════════════════════════════════
数据来源与验证状态
═══════════════════════════════════════════════════════════════════

字段名、取值范围与枚举含义取自该产品的物模型 (profile)：

    services: switch / mode / temperature / fan

``switch.on`` / ``mode.mode`` / ``temperature.target`` / ``fan.gear`` /
``fan.direction`` 的实时取值已在多台在线设备上通过云端动态状态查询核对
（例如 ``{"on": 1, "mode": 2, "target": 25, "gear": 5, "direction": 2}``）。

写帧遵循「只带要改的字段，同一服务内的其它字段沿用当前值」：``fan`` 服务
同时承载 ``gear`` 与 ``direction``，因此改风速会带上当前摆风、改摆风会带上
当前风速，避免把另一个字段刷回默认值。

**未经真实设备逐项验证的部分**：风速五档、摆风四档下发后的设备实际表现未
逐项实测；模式/温度/风速/摆风写入时若设备处于关机状态，会先补一帧
``switch.on=1``（与项目内 115J 适配器的 ``_wake_power`` 行为一致），该补帧
在真机上未单独验证。

═══════════════════════════════════════════════════════════════════
核心服务（取自真机物模型）
═══════════════════════════════════════════════════════════════════

    switch.on            bool RW (1=开, 0=关)
    mode.mode            enum RW (1=自动, 2=制冷, 3=制热, 4=通风, 5=除湿)
    temperature.target   int  RW (16-32, step1)
    fan.gear             enum RW (0=自动, 1=低风, 2=中低风, 3=中风, 4=中高风, 5=高风)
    fan.direction        enum RW (1=固定, 2=左右扫风, 3=上下扫风, 4=左右+上下)

═══════════════════════════════════════════════════════════════════
实体清单
═══════════════════════════════════════════════════════════════════

    climate  air_conditioner   开关 / 模式 / 目标温度 / 风速 / 摆风
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_TEMP_MIN = 16
_TEMP_MAX = 32

# 设备 mode(1-5) <-> HA HVAC
_DEV_TO_HVAC = {1: "auto", 2: "cool", 3: "heat", 4: "fan_only", 5: "dry"}
_HVAC_TO_DEV = {value: key for key, value in _DEV_TO_HVAC.items()}

# 设备 fan.gear(0-5) <-> HA fan
_DEV_TO_FAN = {
    0: "auto",
    1: "low",
    2: "medium_low",
    3: "medium",
    4: "medium_high",
    5: "high",
}
_FAN_TO_DEV = {value: key for key, value in _DEV_TO_FAN.items()}

# 设备 fan.direction(1-4) <-> HA swing
_DEV_TO_SWING = {1: "off", 2: "horizontal", 3: "vertical", 4: "both"}
_SWING_TO_DEV = {value: key for key, value in _DEV_TO_SWING.items()}


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


def _is_on(context: DeviceContext) -> bool | None:
    """当前开关状态；读不到就返回 None，让调用方决定要不要补开机帧。"""

    value = _as_int(context.value("switch", "on"))
    if value is None:
        return None
    return value != 0


async def _wake_if_off(context: DeviceContext) -> None:
    """设备关机时先开机，否则模式/温度/风速的下发会被忽略。"""

    if _is_on(context) is False:
        await context.async_send_service("switch", {"on": 1})


async def _turn_on(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 1})


async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 0})


async def _set_hvac_mode(context: DeviceContext, data: Mapping[str, Any]) -> None:
    hvac_mode = str(data.get("hvac_mode"))
    if hvac_mode == "off":
        await _turn_off(context, data)
        return
    dev_mode = _HVAC_TO_DEV.get(hvac_mode)
    if dev_mode is None:
        raise ValueError(f"unsupported hvac_mode: {hvac_mode}")
    await _wake_if_off(context)
    await context.async_send_service("mode", {"mode": dev_mode})


async def _set_temperature(context: DeviceContext, data: Mapping[str, Any]) -> None:
    temperature = _as_float(data.get("temperature"))
    if temperature is None:
        return
    target = max(_TEMP_MIN, min(_TEMP_MAX, int(round(temperature))))
    await _wake_if_off(context)
    await context.async_send_service("temperature", {"target": target})


async def _set_fan_mode(context: DeviceContext, data: Mapping[str, Any]) -> None:
    gear = _FAN_TO_DEV.get(str(data.get("fan_mode")))
    if gear is None:
        raise ValueError(f"unsupported fan_mode: {data.get('fan_mode')}")
    direction = _as_int(context.value("fan", "direction"))
    frame: dict[str, Any] = {"gear": gear}
    if direction is not None:
        frame["direction"] = direction
    await _wake_if_off(context)
    await context.async_send_service("fan", frame)


async def _set_swing_mode(context: DeviceContext, data: Mapping[str, Any]) -> None:
    direction = _SWING_TO_DEV.get(str(data.get("swing_mode")))
    if direction is None:
        raise ValueError(f"unsupported swing_mode: {data.get('swing_mode')}")
    gear = _as_int(context.value("fan", "gear"))
    frame: dict[str, Any] = {"direction": direction}
    if gear is not None:
        frame["gear"] = gear
    await _wake_if_off(context)
    await context.async_send_service("fan", frame)


class ProductA0CPAdapter:
    """A0CP 智能空调适配器。"""

    prod_id = "A0CP"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service("mode"):
            return ()

        def climate_state(device: DeviceContext) -> Mapping[str, Any]:
            on = _as_int(device.value("switch", "on"))
            mode = _as_int(device.value("mode", "mode"))
            if on == 0:
                hvac_mode: str | None = "off"
            elif on is None:
                hvac_mode = None
            else:
                hvac_mode = _DEV_TO_HVAC.get(mode)
            return {
                "hvac_mode": hvac_mode,
                "target_temperature": _as_float(device.value("temperature", "target")),
                "fan_mode": _DEV_TO_FAN.get(_as_int(device.value("fan", "gear"))),
                "swing_mode": _DEV_TO_SWING.get(
                    _as_int(device.value("fan", "direction"))
                ),
            }

        return (
            EntitySpec(
                platform="climate",
                key="air_conditioner",
                name=None,
                state=climate_state,
                metadata={
                    "hvac_modes": ["off", *list(_DEV_TO_HVAC.values())],
                    "fan_modes": list(_DEV_TO_FAN.values()),
                    "swing_modes": list(_DEV_TO_SWING.values()),
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


ADAPTER = ProductA0CPAdapter()
