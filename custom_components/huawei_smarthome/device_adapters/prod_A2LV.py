"""User-contributed protocol for Huawei product A2LV (酷宅 门窗传感器).

设备类型: 门窗传感器 (Contact Sensor, 酷宅科技)
核心服务:
   doorContact.status  enum R  0=关闭, 1=打开

暴露实体: 一个 Home Assistant ``binary_sensor`` (device_class=door),
is_on=True 表示门窗打开.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext


def _is_open(value: Any) -> bool | None:
    """容忍 bool / 数字 / 字符串 的门窗状态。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.casefold() in {"1", "true", "on", "open"}:
            return True
        if value.casefold() in {"0", "false", "off", "close"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


class ProductA2LVAdapter:
    """A2LV 门窗传感器: 开合状态 binary_sensor."""

    prod_id = "A2LV"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service("doorContact"):
            return ()

        return (
            EntitySpec(
                platform="binary_sensor",
                key="status",
                name="开合状态",
                state=lambda device: {
                    "is_on": _is_open(device.value("doorContact", "status"))
                },
                metadata={"device_class": "door"},
            ),
        )


ADAPTER = ProductA2LVAdapter()
