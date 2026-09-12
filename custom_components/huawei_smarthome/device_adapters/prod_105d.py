"""User-contributed protocol for Huawei product 105D (易百珑 ERC309-H 单路多功能接收器).

设备类型: 开关控制器 (Receiver Controller)
核心服务: ``switch`` (binarySwitch) -> 特征 ``on`` (bool, RW)
   on = 1 开启, on = 0 关闭

本适配器为设备暴露一个 Home Assistant switch 实体，用于开关控制。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext


def _bool(value: Any) -> bool | None:
    """容忍 bool / 数字 / 字符串 形式的开关状态。"""
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


class Product105DAdapter:
    """105D 开关接收器适配器：单个 switch 实体。"""

    prod_id = "105D"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service("switch"):
            return ()

        def switch_state(device: DeviceContext) -> Mapping[str, Any]:
            # HA switch 平台约定：StateReader 返回 is_on
            return {"is_on": _bool(device.value("switch", "on"))}

        return (
            EntitySpec(
                platform="switch",
                key="switch",
                name=None,
                state=switch_state,
                actions={
                    "turn_on": _turn_on,
                    "turn_off": _turn_off,
                },
            ),
        )


ADAPTER = Product105DAdapter()


