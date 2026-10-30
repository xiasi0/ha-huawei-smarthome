"""User-contributed protocol for Huawei product 2035 (卡赫智能净水器 600G).

核心服务:
   switch.on             开关
   status.status         0制水 1冲洗 2待机 3关闭
   inputTds.tds / outputTds.tds   进/出水 TDS
   purifyWater.current   净水量
   filterElement1-3      leftPer 剩余百分比 / alarm / reset(=1 复位)
   contWater.time        RW 10-120 (连续用水监控时长)
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_STATUS_LABELS = {
    0: "制水",
    1: "冲洗",
    2: "待机",
    3: "关闭",
}

_FILTERS: tuple[tuple[str, str], ...] = (
    ("filterElement1", "滤芯1"),
    ("filterElement2", "滤芯2"),
    ("filterElement3", "滤芯3"),
)


def _is_on(value: Any) -> bool | None:
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


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


async def _turn_on(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 1})


async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 0})


def _status_sensor(device: DeviceContext) -> Mapping[str, Any]:
    value = _number(device.value("status", "status"))
    return {
        "native_value": _STATUS_LABELS.get(int(value)) if value is not None else None
    }


class Product2035Adapter:
    """2035 净水器: 开关 + 状态/TDS/净水量传感器 + 滤芯寿命."""

    prod_id = "2035"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None:
            return ()

        entities: list[EntitySpec] = []
        if context.has_service("switch"):
            entities.append(
                EntitySpec(
                    platform="switch",
                    key="switch",
                    name=None,
                    state=lambda device: {
                        "is_on": _is_on(device.value("switch", "on"))
                    },
                    actions={"turn_on": _turn_on, "turn_off": _turn_off},
                )
            )
        if context.has_service("status"):
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="status",
                    name="工作状态",
                    state=_status_sensor,
                )
            )
        if context.has_service("inputTds"):
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="input_tds",
                    name="进水TDS",
                    state=lambda device: {
                        "native_value": _number(device.value("inputTds", "tds"))
                    },
                    metadata={"unit": "ppm", "state_class": "measurement"},
                )
            )
        if context.has_service("outputTds"):
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="output_tds",
                    name="出水TDS",
                    state=lambda device: {
                        "native_value": _number(device.value("outputTds", "tds"))
                    },
                    metadata={"unit": "ppm", "state_class": "measurement"},
                )
            )
        if context.has_service("purifyWater"):
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="purified_water",
                    name="净水量",
                    state=lambda device: {
                        "native_value": _number(
                            device.value("purifyWater", "current")
                        )
                    },
                    metadata={"unit": "L", "state_class": "total_increasing"},
                )
            )

        for sid, label in _FILTERS:
            if not context.has_service(sid):
                continue
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key=f"{sid}_left",
                    name=f"{label}剩余寿命",
                    state=lambda device, _sid=sid: {
                        "native_value": _number(device.value(_sid, "leftPer"))
                    },
                    metadata={"unit": "%", "state_class": "measurement"},
                )
            )
            entities.append(
                EntitySpec(
                    platform="binary_sensor",
                    key=f"{sid}_alarm",
                    name=f"{label}更换提醒",
                    state=lambda device, _sid=sid: {
                        "is_on": _is_on(device.value(_sid, "alarm"))
                    },
                )
            )

            async def reset(
                device: DeviceContext,
                _data: Mapping[str, Any],
                *,
                _sid: str = sid,
            ) -> None:
                await device.async_send_service(_sid, {"reset": 1})

            entities.append(
                EntitySpec(
                    platform="button",
                    key=f"{sid}_reset",
                    name=f"{label}复位",
                    state=lambda device: {},
                    actions={"press": reset},
                )
            )
        return tuple(entities)


ADAPTER = Product2035Adapter()
