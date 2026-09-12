"""User-contributed protocol for Huawei product A0NN (酷宅科技 智能插座 / 1路).

设备类型: 智能插座 (Socket)
制造商: 酷宅科技, 型号 Smart socket
核心服务:
   switch.on bool RW (1=开, 0=关)

本适配器暴露 1 个 Home Assistant ``switch`` 开关实体.
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
    await context.async_send_service("switch", {"on": 1})


async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 0})


class ProductA0NNAdapter:
    """A0NN 1路智能插座适配器。"""

    prod_id = "A0NN"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service("switch"):
            return ()

        def switch_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"is_on": _as_bool(device.value("switch", "on"))}

        return (
            EntitySpec(
                platform="switch",
                key="switch",
                name=None,
                state=switch_state,
                actions={"turn_on": _turn_on, "turn_off": _turn_off},
            ),
        )


ADAPTER = ProductA0NNAdapter()


