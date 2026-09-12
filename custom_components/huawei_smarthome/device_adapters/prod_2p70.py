"""User-contributed protocol for Huawei product 2P70 (智能马桶).

设备类型: 马桶 (Intelligent Toilet), 型号 R6-300A
核心服务(本次使用的):
   seatStatus.status      enum R  (0=未着座, 1=已着座)  着座检测
   toiletStatus.status    enum R  (盖板/座圈开启关闭状态)
   seatHeating.gear       enum RW (0=常温,1=1挡,2=2挡,3=3挡) 座圈加热
   washSetting.mode       enum RW (0=空闲,1=臀洗,2=妇洗,3=一键智能)
   foamShield.on          bool RW (泡沫盾开关)

本适配器暴露:
   1. binary_sensor 着座检测 (occupancy)
   2. sensor 盖板座圈状态 (状态编号)
   3. select 座圈加热档位
   4. select 冲洗模式
   5. switch 泡沫盾
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_SEAT_GEAR_OPTIONS = ["常温", "1挡", "2挡", "3挡"]
_WASH_OPTIONS = ["空闲", "臀洗", "妇洗", "一键智能"]


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


class Product2P70Adapter:
    """2P70 智能马桶适配器。"""

    prod_id = "2P70"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service("seatStatus"):
            return ()

        def seated_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"is_on": _as_int(device.value("seatStatus", "status")) == 1}

        def lid_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"native_value": _as_int(device.value("toiletStatus", "status"))}

        def seat_gear_state(device: DeviceContext) -> Mapping[str, Any]:
            gear = _as_int(device.value("seatHeating", "gear"))
            return {
                "current_option": _SEAT_GEAR_OPTIONS[gear]
                if gear is not None and 0 <= gear < len(_SEAT_GEAR_OPTIONS)
                else _SEAT_GEAR_OPTIONS[0]
            }

        async def set_seat_gear(device: DeviceContext, data: Mapping[str, Any]) -> None:
            val = {
                "常温": 0,
                "1挡": 1,
                "2挡": 2,
                "3挡": 3,
            }.get(str(data.get("option")))
            if val is None:
                raise ValueError(f"unsupported option: {data.get('option')}")
            await device.async_send_service("seatHeating", {"gear": val})

        def wash_mode_state(device: DeviceContext) -> Mapping[str, Any]:
            mode = _as_int(device.value("washSetting", "mode"))
            return {
                "current_option": _WASH_OPTIONS[mode]
                if mode is not None and 0 <= mode < len(_WASH_OPTIONS)
                else _WASH_OPTIONS[0]
            }

        async def set_wash_mode(device: DeviceContext, data: Mapping[str, Any]) -> None:
            val = {
                "空闲": 0,
                "臀洗": 1,
                "妇洗": 2,
                "一键智能": 3,
            }.get(str(data.get("option")))
            if val is None:
                raise ValueError(f"unsupported option: {data.get('option')}")
            await device.async_send_service("washSetting", {"mode": val})

        def foam_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"is_on": _as_bool(device.value("foamShield", "on"))}

        async def foam_on(device: DeviceContext, _data: Mapping[str, Any]) -> None:
            await device.async_send_service("foamShield", {"on": 1})

        async def foam_off(device: DeviceContext, _data: Mapping[str, Any]) -> None:
            await device.async_send_service("foamShield", {"on": 0})

        return (
            EntitySpec(
                platform="binary_sensor",
                key="seated",
                name="着座检测",
                state=seated_state,
                metadata={"device_class": "occupancy"},
            ),
            EntitySpec(
                platform="sensor",
                key="lid_status",
                name="盖板座圈状态",
                state=lid_state,
            ),
            EntitySpec(
                platform="select",
                key="seat_heating",
                name="座圈加热",
                state=seat_gear_state,
                metadata={"options": _SEAT_GEAR_OPTIONS},
                actions={"select_option": set_seat_gear},
            ),
            EntitySpec(
                platform="select",
                key="wash_mode",
                name="冲洗模式",
                state=wash_mode_state,
                metadata={"options": _WASH_OPTIONS},
                actions={"select_option": set_wash_mode},
            ),
            EntitySpec(
                platform="switch",
                key="foam",
                name="泡沫盾",
                state=foam_state,
                actions={"turn_on": foam_on, "turn_off": foam_off},
            ),
        )


ADAPTER = Product2P70Adapter()


