"""User-contributed protocol for Huawei product 100X (晾霸晾衣机 HW50 / HBL-2).

核心服务 clothesHanger:
   action   (int  RW)  0=升, 1=降, 2=暂停
   height   (int  RW)  1=最高(打开), 2=最低(关闭), 0=行程中
   airDry / disinfect / drying / lighting (bool RW)
   airDryTime / disinfectTime / dryTime          (int RW, 设定时长, 分钟)
   airDryTimeLeft / disinfectTimeLeft / dryTimeLeft (int R, 剩余时长, 分钟)

暴露实体:
   cover  晾衣架 (升/降/暂停)
   switch 风干 / 消毒 / 烘干 / 照明
   sensor 风干剩余 / 消毒剩余 / 烘干剩余 (分钟)
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_ACTION_UP = 0
_ACTION_DOWN = 1
_ACTION_PAUSE = 2

_SWITCH_FIELDS: tuple[tuple[str, str], ...] = (
    ("airDry", "风干"),
    ("disinfect", "消毒"),
    ("drying", "烘干"),
    ("lighting", "照明"),
)

_TIME_LEFT_FIELDS: tuple[tuple[str, str], ...] = (
    ("airDryTimeLeft", "风干剩余"),
    ("disinfectTimeLeft", "消毒剩余"),
    ("dryTimeLeft", "烘干剩余"),
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


async def _open(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("clothesHanger", {"action": _ACTION_UP})


async def _close(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("clothesHanger", {"action": _ACTION_DOWN})


async def _stop(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("clothesHanger", {"action": _ACTION_PAUSE})


def _cover_state(device: DeviceContext) -> Mapping[str, Any]:
    height = _number(device.value("clothesHanger", "height"))
    # height: 1=最高(视为打开), 2=最低(视为关闭), 0=行程中(未知)
    if height == 1:
        return {"is_closed": False}
    if height == 2:
        return {"is_closed": True}
    return {"is_closed": None}


class Product100XAdapter:
    """100X 晾衣机: cover + 4 开关 + 3 个剩余时长传感器."""

    prod_id = "100x"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service("clothesHanger"):
            return ()

        entities: list[EntitySpec] = [
            EntitySpec(
                platform="cover",
                key="hanger",
                name="晾衣架",
                state=_cover_state,
                actions={"open": _open, "close": _close, "stop": _stop},
            )
        ]

        for field, label in _SWITCH_FIELDS:

            async def turn_on(
                device: DeviceContext,
                _data: Mapping[str, Any],
                *,
                _field: str = field,
            ) -> None:
                await device.async_send_service("clothesHanger", {_field: 1})

            async def turn_off(
                device: DeviceContext,
                _data: Mapping[str, Any],
                *,
                _field: str = field,
            ) -> None:
                await device.async_send_service("clothesHanger", {_field: 0})

            def state(
                device: DeviceContext,
                *,
                _field: str = field,
            ) -> Mapping[str, Any]:
                return {"is_on": _is_on(device.value("clothesHanger", _field))}

            entities.append(
                EntitySpec(
                    platform="switch",
                    key=field,
                    name=label,
                    state=state,
                    actions={"turn_on": turn_on, "turn_off": turn_off},
                )
            )

        for field, label in _TIME_LEFT_FIELDS:
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key=field,
                    name=label,
                    state=lambda device, _field=field: {
                        "native_value": _number(
                            device.value("clothesHanger", _field)
                        )
                    },
                    metadata={
                        "unit": "min",
                        "state_class": "measurement",
                        "device_class": "duration",
                    },
                )
            )
        return tuple(entities)


ADAPTER = Product100XAdapter()
