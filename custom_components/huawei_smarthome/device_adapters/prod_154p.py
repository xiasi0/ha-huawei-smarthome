"""User-contributed protocol for Huawei product 154P.

Device: 豪恩燃气泄漏传感器 / iHORN combustible gas detector
(deviceModel ``JT-LH-801``, manufacturer ``iHORN``/豪恩, deviceTypeId ``03A``,
protocolType ``1``/WiFi).
Profile: https://smarthome-drcn.dbankcdn.com/device/guide/154P/154P.json

Profile limitation
------------------
``154P.json`` declares only ``muffling`` and ``checking``.  The device itself
reports eleven services over MQTT, so this adapter is driven by the vendor H5
bundle instead of the truncated Profile.

Enum evidence
-------------
Every ``mean`` table below is copied verbatim from the 154P H5 bundle
``h5_001/static/js/app.*.js`` (module ``SJPu``), which is the authoritative
description of this product's field ranges:

    alarm:    { alarm:          {range:[0,1],      mean:["检测正常","燃气报警"]} }
    muffling: { muffling:       {range:[0,1],      mean:["消音关","消音开"]} }
    checking: { checkingresult: {range:[0,1],      mean:["自检中","自检成功"]},
                checking:       {range:[0,1],      mean:["关","开"]} }
    state:    { state:          {range:[0,1,2,3],  mean:["预热中...","检测正常","故障","失效"]} }
    event:    { event:          {range:[0..6],
                                 mean:["燃气告警","燃气告警解除","故障告警","故障告警解除",
                                       "自检","消音","设备失效"]} }

The bundle also renders the alarm row as 燃气告警 / 燃气告警解除 and the
buttons as 自检 / 消音.

Exposed entities
----------------
* ``binary_sensor`` 燃气告警   <- ``alarm.alarm`` (1 = 燃气报警, device_class gas)
* ``sensor``        燃气状态   <- ``alarm.alarm`` (检测正常 / 燃气报警)
* ``sensor``        设备状态   <- ``state.state``
* ``sensor``        最近事件   <- ``event.event``
* ``sensor``        自检结果   <- ``checking.checkingresult``
* ``button``        自检       -> ``checking.checking = 1``
* ``button``        消音       -> ``muffling.muffling = 1``

Not exposed (no verified semantics / app-managed): ``update``, ``netInfo``,
``timer``, ``delay``, ``diagnose``, ``faultDetection``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_ALARM_SID = "alarm"
_MUFFLING_SID = "muffling"
_STATE_SID = "state"
_CHECKING_SID = "checking"
_EVENT_SID = "event"

# Copied verbatim from the 154P H5 bundle (module ``SJPu``).
_ALARM_MEAN = ("检测正常", "燃气报警")
_CHECKING_RESULT_MEAN = ("自检中", "自检成功")
_CHECKING_MEAN = ("关", "开")
_STATE_MEAN = ("预热中...", "检测正常", "故障", "失效")
_EVENT_MEAN = (
    "燃气告警",
    "燃气告警解除",
    "故障告警",
    "故障告警解除",
    "自检",
    "消音",
    "设备失效",
)


def _number(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _enum_text(raw: Any, table: tuple[str, ...]) -> str | None:
    """Map a numeric enum onto the H5 bundle's label table."""

    value = _number(raw)
    if value is None or value < 0 or value >= len(table):
        return None
    return table[value]


def _alarm_on(context: DeviceContext) -> bool | None:
    """1 = 燃气报警 -> binary_sensor on."""

    value = _number(context.value(_ALARM_SID, "alarm"))
    if value is None:
        return None
    return value == 1


def _alarm_text(context: DeviceContext) -> str | None:
    return _enum_text(context.value(_ALARM_SID, "alarm"), _ALARM_MEAN)


def _state_text(context: DeviceContext) -> str | None:
    return _enum_text(context.value(_STATE_SID, "state"), _STATE_MEAN)


def _event_text(context: DeviceContext) -> str | None:
    return _enum_text(context.value(_EVENT_SID, "event"), _EVENT_MEAN)


def _checking_text(context: DeviceContext) -> str | None:
    running = _enum_text(context.value(_CHECKING_SID, "checking"), _CHECKING_MEAN)
    if running == "开":
        return "自检中"
    return _enum_text(
        context.value(_CHECKING_SID, "checkingresult"),
        _CHECKING_RESULT_MEAN,
    )


async def _press_self_check(
    context: DeviceContext, _data: Mapping[str, Any]
) -> None:
    await context.async_send_service(_CHECKING_SID, {"checking": 1})


async def _press_mute(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(_MUFFLING_SID, {"muffling": 1})


class Product154PAdapter:
    """iHORN JT-LH-801 combustible gas detector."""

    prod_id = "154P"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        entities: list[EntitySpec] = []

        if context.has_service(_ALARM_SID):
            entities.append(
                EntitySpec(
                    platform="binary_sensor",
                    key="gas_alarm",
                    name="燃气告警",
                    state=lambda ctx: {"is_on": _alarm_on(ctx)},
                    metadata={"device_class": "gas"},
                )
            )
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="gas_status",
                    name="燃气状态",
                    state=lambda ctx: {"native_value": _alarm_text(ctx)},
                )
            )

        if context.has_service(_STATE_SID):
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="device_state",
                    name="设备状态",
                    state=lambda ctx: {"native_value": _state_text(ctx)},
                )
            )

        if context.has_service(_EVENT_SID):
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="last_event",
                    name="最近事件",
                    state=lambda ctx: {"native_value": _event_text(ctx)},
                )
            )

        if context.has_service(_CHECKING_SID):
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="self_check_result",
                    name="自检结果",
                    state=lambda ctx: {"native_value": _checking_text(ctx)},
                )
            )
            entities.append(
                EntitySpec(
                    platform="button",
                    key="self_check",
                    name="自检",
                    state=lambda ctx: {},
                    actions={"press": _press_self_check},
                )
            )

        if context.has_service(_MUFFLING_SID):
            entities.append(
                EntitySpec(
                    platform="button",
                    key="mute",
                    name="消音",
                    state=lambda ctx: {},
                    actions={"press": _press_mute},
                )
            )

        return tuple(entities)


ADAPTER = Product154PAdapter()
