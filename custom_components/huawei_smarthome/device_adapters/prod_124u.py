"""User-contributed protocol for Huawei product 124U (豪恩 智能插座).

设备类型: 智能插座 (Socket)
核心服务:
   switch.on            bool RW (0=关, 1=开)   继电器开关
   power.current        int  RW (0-6000)       功率(W)
   consumption.consumption int RW (0-1000)     累计电量(kWh)
   memorySwitch.status  enum RW (0=关,1=开,2=保持上次) 断电记忆

本适配器暴露:
   1. switch 开关
   2. sensor 功率 (W)
   3. sensor 累计电量 (kWh)
   4. select 断电记忆 (关/开/保持上次)
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_MEMORY_OPTIONS = ["关", "开", "保持上次"]


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


async def _turn_on(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 1})


async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 0})


async def _set_memory(context: DeviceContext, data: Mapping[str, Any]) -> None:
    val = {
        "关": 0,
        "开": 1,
        "保持上次": 2,
    }.get(str(data.get("option")))
    if val is None:
        raise ValueError(f"unsupported option: {data.get('option')}")
    await context.async_send_service("memorySwitch", {"status": val})


class Product124UAdapter:
    """124U 豪恩智能插座适配器。"""

    prod_id = "124U"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service("switch"):
            return ()

        def switch_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"is_on": _as_bool(device.value("switch", "on"))}

        def power_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"native_value": _as_int(device.value("power", "current"))}

        def consumption_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"native_value": _as_int(device.value("consumption", "consumption"))}

        def memory_state(device: DeviceContext) -> Mapping[str, Any]:
            status = _as_int(device.value("memorySwitch", "status"))
            return {
                "current_option": _MEMORY_OPTIONS[status]
                if status is not None and 0 <= status < len(_MEMORY_OPTIONS)
                else _MEMORY_OPTIONS[0]
            }

        return (
            EntitySpec(
                platform="switch",
                key="switch",
                name=None,
                state=switch_state,
                actions={"turn_on": _turn_on, "turn_off": _turn_off},
            ),
            EntitySpec(
                platform="sensor",
                key="power",
                name="功率",
                state=power_state,
                metadata={"unit": "W", "device_class": "power"},
            ),
            EntitySpec(
                platform="sensor",
                key="consumption",
                name="累计电量",
                state=consumption_state,
                metadata={"unit": "kWh", "device_class": "energy", "state_class": "total"},
            ),
            EntitySpec(
                platform="select",
                key="memory",
                name="断电记忆",
                state=memory_state,
                metadata={"options": _MEMORY_OPTIONS},
                actions={"select_option": _set_memory},
            ),
        )


ADAPTER = Product124UAdapter()


