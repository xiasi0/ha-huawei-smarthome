"""User-contributed protocol for Huawei product A0CQ (美的 COLMO 洗衣机).

产品: 洗衣机
厂商: 美的 (COLMO)
deviceTypeId: 015

═══════════════════════════════════════════════════════════════════
实体清单
═══════════════════════════════════════════════════════════════════

    power       switch   启停（对应物模型 switch.on）
    left_time   sensor   剩余时间（分钟，对应 leftTime.time）

未暴露（宁可不出）：
- ``status.status``：本机上报 1，但厂商未公开取值语义（无法区分
  「待机 / 洗涤 / 脱水 / 完成」），做成 sensor 只会误导，故不出。
- ``mode.mode``：同理，取值含义未公开，不猜。
- ``action.action``：语义未公开。

Matter 规范目前没有洗衣机设备类型（esp-matter 亦未支持），因此不强行
映射为一个假品类，只把**能确定语义的两项**以通用开关与传感器暴露，
保证「能启停、能看剩余时间」这两个最常用动作可用。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_SWITCH_SID = "switch"
_LEFT_TIME_SID = "leftTime"


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
    await context.async_send_service(_SWITCH_SID, {"on": 1})


async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(_SWITCH_SID, {"on": 0})


class ProductA0CQAdapter:
    """A0CQ 洗衣机适配器。"""

    prod_id = "A0CQ"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None:
            return ()

        entities: list[EntitySpec] = []

        if context.has_service(_SWITCH_SID):
            entities.append(
                EntitySpec(
                    platform="switch",
                    key="power",
                    name="启停",
                    state=lambda device: {
                        "is_on": (_as_int(device.value(_SWITCH_SID, "on")) or 0) != 0
                    },
                    actions={"turn_on": _turn_on, "turn_off": _turn_off},
                )
            )

        if context.has_service(_LEFT_TIME_SID):
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="left_time",
                    name="剩余时间",
                    state=lambda device: {
                        "value": _as_int(device.value(_LEFT_TIME_SID, "time"))
                    },
                    metadata={
                        "unit": "min",
                        "device_class": "duration",
                        "state_class": "measurement",
                    },
                )
            )

        return tuple(entities)


ADAPTER = ProductA0CQAdapter()
