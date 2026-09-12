"""User-contributed protocol for Huawei product 113J (海雀 AI 全景摄像头).

设备类型: 海雀 AI 全景摄像头 (Alcidae AI Camera), 型号 C314
核心服务:
   carmera.on            bool RW (0=关, 1=开)  摄像头电源
   carmera.humanBodyAlarm int R   (0=关, 1=开) 人体检测告警态

本适配器暴露:
   1. switch 摄像头电源开关
   2. binary_sensor 人体检测 (device_class=motion)
注: 该集成无 camera 平台, 故以 switch+binary_sensor 形式接入.
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


async def _turn_on(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("carmera", {"on": 1})


async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("carmera", {"on": 0})


class Product113JAdapter:
    """113J 海雀摄像头适配器。"""

    prod_id = "113J"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service("carmera"):
            return ()

        def switch_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"is_on": _as_bool(device.value("carmera", "on"))}

        def motion_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"is_on": _as_bool(device.value("carmera", "humanBodyAlarm"))}

        return (
            EntitySpec(
                platform="switch",
                key="power",
                name="电源",
                state=switch_state,
                actions={"turn_on": _turn_on, "turn_off": _turn_off},
            ),
            EntitySpec(
                platform="binary_sensor",
                key="motion",
                name="人体检测",
                state=motion_state,
                metadata={"device_class": "motion"},
            ),
        )


ADAPTER = Product113JAdapter()


