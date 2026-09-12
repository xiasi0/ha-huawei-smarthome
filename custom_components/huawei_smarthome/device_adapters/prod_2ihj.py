"""User-contributed protocol for Huawei product 2IHJ (开合帘 / 电动窗帘电机).

设备类型: 开合帘 (Curtain)
制造商: 广东朗森机电有限公司
核心服务:
   opener (开合度):
     current  int  R   0-100 当前开合度(0=闭合, 100=全开)
     target   int  RW  0-100 目标位置(与 current 同标度)
   action  (开合电机操作):
     action   enum RW  0=关, 1=开, 2=暂停
   stroke  (行程设置): 正常/反转/校准 (本次未使用)

本适配器将该设备暴露为一个 Home Assistant ``cover`` (窗帘) 实体,
支持: 打开 / 关闭 / 暂停 / 指定位置.
注: current/target 的 0-100 方向默认按"0=闭合、100=全开"映射到 HA;
    若实测方向相反, 将 _POS_REVERSED 置 True 即可.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_POS_MIN = 0
_POS_MAX = 100

# 若实测"开合度"方向与 HA 相反(HA: 0=关100=开), 置 True 取反
_POS_REVERSED = False


def _as_int(value: Any) -> int | None:
    """容忍 int / 数字字符串 / bool。"""
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


def _to_ha_position(position: int | None) -> int | None:
    """设备开合度 -> HA cover 位置 (0=关, 100=开)。"""
    if position is None:
        return None
    pos = max(_POS_MIN, min(_POS_MAX, position))
    return _POS_MAX - pos if _POS_REVERSED else pos


def _to_device_position(position: Any) -> int:
    """HA cover 位置 -> 设备 target。"""
    ha = max(_POS_MIN, min(_POS_MAX, int(round(float(position)))))
    return _POS_MAX - ha if _POS_REVERSED else ha


async def _open(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("action", {"action": 1})


async def _close(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("action", {"action": 0})


async def _stop(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("action", {"action": 2})


async def _set_position(context: DeviceContext, data: Mapping[str, Any]) -> None:
    position = data.get("position")
    if position is None:
        return
    await context.async_send_service("opener", {"target": _to_device_position(position)})


class Product2IHJAdapter:
    """2IHJ 开合帘适配器：暴露一个 cover (窗帘) 实体。"""

    prod_id = "2IHJ"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service("opener"):
            return ()

        def cover_state(device: DeviceContext) -> Mapping[str, Any]:
            current = _as_int(device.value("opener", "current"))
            position = _to_ha_position(current)
            return {
                "current_position": position,
                "is_closed": current == 0,
            }

        return (
            EntitySpec(
                platform="cover",
                key="curtain",
                name=None,
                state=cover_state,
                actions={
                    "open": _open,
                    "close": _close,
                    "stop": _stop,
                    "set_position": _set_position,
                },
            ),
        )


ADAPTER = Product2IHJAdapter()


