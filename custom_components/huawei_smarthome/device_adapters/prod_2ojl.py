"""User-contributed protocol for Huawei product 2OJL (加湿器).

设备类型: 加湿器 (Humidifier)
制造商: 上海汉枫电子科技有限公司, 型号 HF-HM-JSQ-002
核心服务:
   switch.on       bool RW   开关 (1=开, 0=关)
   humidity.target  int RW  40-80 目标湿度(%)
   humidity.current int R    0-100 当前湿度(%)
   gear.gear        enum RW  0=恒湿, 1=高档, 2=低档, 3=睡眠 (档位)

本适配器暴露一个 Home Assistant ``humidifier`` 实体,
支持: 开关 / 目标湿度 / 档位.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_HUMI_MIN = 40
_HUMI_MAX = 80
_HUMI_STEP = 5

_GEAR_TO_MODE = {0: "恒湿", 1: "高档", 2: "低档", 3: "睡眠"}
_MODE_TO_GEAR = {mode: gear for gear, mode in _GEAR_TO_MODE.items()}


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


async def _set_humidity(context: DeviceContext, data: Mapping[str, Any]) -> None:
    humidity = data.get("humidity")
    if humidity is None:
        return
    target = max(_HUMI_MIN, min(_HUMI_MAX, int(round(float(humidity) / _HUMI_STEP) * _HUMI_STEP)))
    await context.async_send_service("humidity", {"target": target})


async def _set_mode(context: DeviceContext, data: Mapping[str, Any]) -> None:
    gear = _MODE_TO_GEAR.get(str(data.get("mode")))
    if gear is None:
        raise ValueError(f"unsupported mode: {data.get('mode')}")
    await context.async_send_service("gear", {"gear": gear})


class Product2OJLAdapter:
    """2OJL 加湿器适配器：一个 humidifier 实体。"""

    prod_id = "2OJL"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service("humidity"):
            return ()

        def hum_state(device: DeviceContext) -> Mapping[str, Any]:
            gear = _as_int(device.value("gear", "gear"))
            return {
                "is_on": _as_bool(device.value("switch", "on")),
                "current_humidity": _as_int(device.value("humidity", "current")),
                "target_humidity": _as_int(device.value("humidity", "target")),
                "mode": _GEAR_TO_MODE.get(gear) if gear is not None else None,
            }

        return (
            EntitySpec(
                platform="humidifier",
                key="humidifier",
                name=None,
                state=hum_state,
                metadata={
                    "modes": ["恒湿", "高档", "低档", "睡眠"],
                    "min_humidity": _HUMI_MIN,
                    "max_humidity": _HUMI_MAX,
                },
                actions={
                    "turn_on": _turn_on,
                    "turn_off": _turn_off,
                    "set_humidity": _set_humidity,
                    "set_mode": _set_mode,
                },
            ),
        )


ADAPTER = Product2OJLAdapter()


