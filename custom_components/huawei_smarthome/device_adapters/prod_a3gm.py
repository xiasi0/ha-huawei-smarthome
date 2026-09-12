"""User-contributed protocol for Huawei product A3GM (美的 中央空调).

设备类型: 中央空调 (Central Air-conditioning), 型号 MJV/MDVH-xxx
核心服务:
   switch.on            bool RW (1=开, 0=关)
   mode.mode            enum RW (1=自动,2=制冷,3=制热,4=送风,5=抽湿)
   temperature.target   float RW (16.0-30.0, step0.5)
   temperature.current  float R  (室温 ℃)
   fan.speed            int  RW (1-100 % 连续风速, climate 平台不便映射, 未接)

本适配器暴露一个 Home Assistant ``climate`` 实体:
支持 开关 / 模式 / 目标温度, 并上报当前室温.
注: 风速为连续 1-100%, 该 climate 实体未暴露风速; 自动风服务未映射.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_TEMP_MIN = 16.0
_TEMP_MAX = 30.0

_DEV_TO_HVAC = {1: "auto", 2: "cool", 3: "heat", 4: "fan_only", 5: "dry"}
_HVAC_TO_DEV = {v: k for k, v in _DEV_TO_HVAC.items()}


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
    target = max(_TEMP_MIN, min(_TEMP_MAX, round(float(temp) * 2) / 2))
    await context.async_send_service("temperature", {"target": target})


class ProductA3GMAdapter:
    """A3GM 美的中央空调适配器。"""

    prod_id = "A3GM"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service("mode"):
            return ()

        def climate_state(device: DeviceContext) -> Mapping[str, Any]:
            mode = _as_int(device.value("mode", "mode"))
            return {
                "current_temperature": _as_float(device.value("temperature", "current")),
                "target_temperature": _as_float(device.value("temperature", "target")),
                "hvac_mode": _DEV_TO_HVAC.get(mode, "auto"),
            }

        return (
            EntitySpec(
                platform="climate",
                key="air_conditioner",
                name=None,
                state=climate_state,
                metadata={
                    "hvac_modes": ["auto", "cool", "heat", "fan_only", "dry"],
                    "min_temp": _TEMP_MIN,
                    "max_temp": _TEMP_MAX,
                },
                actions={
                    "turn_on": _turn_on,
                    "turn_off": _turn_off,
                    "set_hvac_mode": _set_hvac_mode,
                    "set_temperature": _set_temperature,
                },
            ),
        )


ADAPTER = ProductA3GMAdapter()


