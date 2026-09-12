"""User-contributed protocol for Huawei product 113B (门磁 / 门窗传感器).

设备类型: 门磁 (Door Detector)
制造商: 豪恩, 型号 HO-10ZB
核心服务: ``doorSensor`` (门窗传感器) -> 特征:
   status: bool  R  0=关闭, 1=打开     (<- 当前开合状态)
   event : bool      0=关闭, 1=打开     (瞬时事件, 不用)
   tamper: bool      0=正常, 1=拆动     (防拆告警)

本适配器暴露两个 Home Assistant ``binary_sensor``:
   1. 开合状态 (device_class=door)   is_on=True 表示门窗打开
   2. 防拆告警 (device_class=tamper) is_on=True 表示被拆卸
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext


def _bool(value: Any) -> bool | None:
    """容忍 bool / 数字 / 字符串 的开关状态。"""
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


class Product113BAdapter:
    """113B 门磁适配器：开合状态 + 防拆 两个 binary_sensor。"""

    prod_id = "113B"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service("doorSensor"):
            return ()

        def status_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"is_on": _bool(device.value("doorSensor", "status"))}

        def tamper_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"is_on": _bool(device.value("doorSensor", "tamper"))}

        return (
            EntitySpec(
                platform="binary_sensor",
                key="status",
                name="开合状态",
                state=status_state,
                metadata={"device_class": "door"},
            ),
            EntitySpec(
                platform="binary_sensor",
                key="tamper",
                name="防拆",
                state=tamper_state,
                metadata={"device_class": "tamper"},
            ),
        )


ADAPTER = Product113BAdapter()


