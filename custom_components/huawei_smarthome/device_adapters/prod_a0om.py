"""User-contributed protocol for Huawei product A0OM (酷宅科技 智能插排 / 4路).

设备类型: 智能插排 (MultiSocket)
制造商: 酷宅科技, 型号 Smart socket
核心服务:
   switch.on   bool RW 总开关
   switchN.on  bool RW (N=1..4) 分路开关

本适配器暴露 5 个 Home Assistant ``switch``:
   总开关 + switch1..switch4.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_SWITCH_SERVICES = [
    ("switch", "总开关"),
    ("switch1", "开关1"),
    ("switch2", "开关2"),
    ("switch3", "开关3"),
    ("switch4", "开关4"),
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


class ProductA0OMAdapter:
    """A0OM 4路智能插排适配器。"""

    prod_id = "A0OM"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service("switch"):
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

        return tuple(_switch_spec(sid, label) for sid, label in _SWITCH_SERVICES)


ADAPTER = ProductA0OMAdapter()


