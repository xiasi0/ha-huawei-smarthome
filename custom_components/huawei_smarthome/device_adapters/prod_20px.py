"""User-contributed protocol for Huawei product 20PX.

Device: 亚摩斯降糖电饭煲 / Yamous low-sugar rice cooker
(deviceModel ``AS-WFT30L``, manufacturer 合肥荣电, deviceTypeId ``026``/电饭煲,
protocolType ``1``/WiFi).
Profile: https://smarthome-drcn.dbankcdn.com/device/guide/20PX/20PX.json

Field evidence
--------------
Every service, characteristic, enum and range below is taken from ``20PX.json``:

    status        {status enum R}   0待机 1工作中 2预约中 3保温中 4制作完成
    action        {action enum RW}  0停止 1开始工作
    mode          {mode enum RW}    3稀饭 4热饭 5煮粥 6煲汤 7蒸煮 10快速饭
                                    100煲仔饭 101糙米饭 102低糖饭 103宝宝粥
                                    104酸奶 105蛋糕 106保温 107小米粥 108杂粮粥
                                    109八宝粥 110排骨海带汤 111百合鸡汤
                                    112药膳乳鸽 113银耳枸杞雪梨茶
    workTime      {time int R}      0~1440 min 制作时长
    setWorkTime   {time int RW}     25~720 min step 5 工作时长调节
    leftTime      {time int R}      0~1440 min 剩余时间
    warmTime      {warmTime int R}  0~720 min 已保温
    presetSwitch  {on bool RW}      预约开关
    preTimeEnd    {time int RW}     50~1440 min step 10 预约完成时间
    faultDetection{code enum R, status bool R}
                                    0正常 100底传感器短路 101底传感器开路
                                    102顶传感器短路 103顶传感器开路 104操作无效

Exposed entities
----------------
* ``switch``        电饭煲      <- ``action.action`` (1 开始工作 / 0 停止)
* ``sensor``        工作状态    <- ``status.status``
* ``select``        烹饪模式    <- ``mode.mode``
* ``number``        工作时长    <- ``setWorkTime.time`` (25~720 min, step 5)
* ``sensor``        剩余时间    <- ``leftTime.time``
* ``sensor``        制作时长    <- ``workTime.time``
* ``switch``        预约        <- ``presetSwitch.on``
* ``number``        预约完成时间 <- ``preTimeEnd.time`` (50~1440 min, step 10)
* ``sensor``        已保温      <- ``warmTime.warmTime``
* ``binary_sensor`` 故障告警    <- ``faultDetection.status``
* ``sensor``        故障代码    <- ``faultDetection.code``
* ``sensor``        信号强度 RSSI / 信号等级 / IP 地址 / Wi-Fi 名称

Not exposed (app-managed): ``update`` (OTA), ``netInfo`` 中的 BSSID,
``timer``, ``delay``, ``diagnose``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_STATUS_SID = "status"
_ACTION_SID = "action"
_MODE_SID = "mode"
_WORK_TIME_SID = "workTime"
_SET_WORK_TIME_SID = "setWorkTime"
_LEFT_TIME_SID = "leftTime"
_PRESET_SID = "presetSwitch"
_PRE_TIME_END_SID = "preTimeEnd"
_WARM_TIME_SID = "warmTime"
_FAULT_SID = "faultDetection"
_NET_SID = "netInfo"

_SET_WORK_TIME_RANGE = (25.0, 720.0)
_SET_WORK_TIME_STEP = 5.0
_PRE_TIME_END_RANGE = (50.0, 1440.0)
_PRE_TIME_END_STEP = 10.0


def _service(profile: Any, sid: str) -> Mapping[str, Any] | None:
    if profile is None:
        return None
    for service in profile.get("services", ()):
        if isinstance(service, Mapping) and service.get("serviceId") == sid:
            return service
    return None


def _field(profile: Any, sid: str, name: str) -> Mapping[str, Any] | None:
    service = _service(profile, sid)
    if service is None:
        return None
    for characteristic in service.get("characteristics", ()):
        if (
            isinstance(characteristic, Mapping)
            and characteristic.get("characteristicName") == name
        ):
            return characteristic
    return None


def _bool(value: Any) -> bool | None:
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
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        return value or None
    return str(value)


def _enum_label(profile: Any, sid: str, name: str, raw: Any) -> str | None:
    """Resolve an enum value through the Profile's own enumList."""

    value = _number(raw)
    if value is None:
        return None
    field = _field(profile, sid, name)
    if field is not None:
        for option in field.get("enumList", ()) or ():
            if not isinstance(option, Mapping):
                continue
            if str(option.get("enumVal")) == str(int(value)):
                return str(option.get("descCh") or option.get("enumVal"))
    return None


def _mode_options(profile: Any) -> tuple[tuple[str, int], ...]:
    """Return (label, value) pairs straight from the Profile's enumList."""

    field = _field(profile, _MODE_SID, "mode") or {}
    options: list[tuple[str, int]] = []
    for option in field.get("enumList", ()) or ():
        if not isinstance(option, Mapping):
            continue
        raw = _number(option.get("enumVal"))
        if raw is None:
            continue
        label = str(option.get("descCh") or option.get("enumVal"))
        options.append((label, int(raw)))
    return tuple(options)


# ---------------- actions ----------------

async def _start_cooking(
    context: DeviceContext, _data: Mapping[str, Any]
) -> None:
    await context.async_send_service(_ACTION_SID, {"action": 1})


async def _stop_cooking(
    context: DeviceContext, _data: Mapping[str, Any]
) -> None:
    await context.async_send_service(_ACTION_SID, {"action": 0})


async def _select_mode(
    context: DeviceContext, data: Mapping[str, Any]
) -> None:
    option = data.get("option")
    if not isinstance(option, str):
        return
    for label, value in _mode_options(context.profile):
        if label == option:
            await context.async_send_service(_MODE_SID, {"mode": value})
            return
    raise ValueError(f"unknown cooking mode: {option}")


async def _set_work_time(
    context: DeviceContext, data: Mapping[str, Any]
) -> None:
    value = _number(data.get("value"))
    if value is None:
        return
    minimum, maximum = _SET_WORK_TIME_RANGE
    clamped = max(minimum, min(maximum, float(value)))
    snapped = minimum + round((clamped - minimum) / _SET_WORK_TIME_STEP) * _SET_WORK_TIME_STEP
    await context.async_send_service(
        _SET_WORK_TIME_SID, {"time": int(snapped)}
    )


async def _set_pre_time_end(
    context: DeviceContext, data: Mapping[str, Any]
) -> None:
    value = _number(data.get("value"))
    if value is None:
        return
    minimum, maximum = _PRE_TIME_END_RANGE
    clamped = max(minimum, min(maximum, float(value)))
    snapped = minimum + round((clamped - minimum) / _PRE_TIME_END_STEP) * _PRE_TIME_END_STEP
    await context.async_send_service(_PRE_TIME_END_SID, {"time": int(snapped)})


async def _preset_on(
    context: DeviceContext, _data: Mapping[str, Any]
) -> None:
    await context.async_send_service(_PRESET_SID, {"on": 1})


async def _preset_off(
    context: DeviceContext, _data: Mapping[str, Any]
) -> None:
    await context.async_send_service(_PRESET_SID, {"on": 0})


class Product20PXAdapter:
    """Yamous AS-WFT30L low-sugar rice cooker."""

    prod_id = "20PX"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        specs: list[EntitySpec] = []

        # 1) 启动 / 停止
        if _field(profile, _ACTION_SID, "action") is not None:
            specs.append(
                EntitySpec(
                    platform="switch",
                    key="cooking",
                    name="电饭煲",
                    state=lambda ctx: {
                        "is_on": _number(ctx.value(_ACTION_SID, "action")) == 1
                    },
                    actions={
                        "turn_on": _start_cooking,
                        "turn_off": _stop_cooking,
                    },
                )
            )

        # 2) 工作状态
        if _field(profile, _STATUS_SID, "status") is not None:
            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="work_status",
                    name="工作状态",
                    state=lambda ctx: {
                        "native_value": _enum_label(
                            ctx.profile, _STATUS_SID, "status",
                            ctx.value(_STATUS_SID, "status"),
                        )
                    },
                )
            )

        # 3) 烹饪模式
        options = _mode_options(profile)
        if options:
            def mode_state(ctx: DeviceContext, _opts: tuple[tuple[str, int], ...] = options) -> Mapping[str, Any]:
                label = _enum_label(
                    ctx.profile, _MODE_SID, "mode", ctx.value(_MODE_SID, "mode")
                )
                if label not in {name for name, _ in _opts}:
                    return {"current_option": None}
                return {"current_option": label}

            specs.append(
                EntitySpec(
                    platform="select",
                    key="cooking_mode",
                    name="烹饪模式",
                    state=mode_state,
                    metadata={"options": tuple(label for label, _ in options)},
                    actions={"select_option": _select_mode},
                )
            )

        # 4) 工作时长
        if _field(profile, _SET_WORK_TIME_SID, "time") is not None:
            specs.append(
                EntitySpec(
                    platform="number",
                    key="set_work_time",
                    name="工作时长",
                    state=lambda ctx: {
                        "native_value": _number(
                            ctx.value(_SET_WORK_TIME_SID, "time")
                        )
                    },
                    metadata={
                        "min": _SET_WORK_TIME_RANGE[0],
                        "max": _SET_WORK_TIME_RANGE[1],
                        "step": _SET_WORK_TIME_STEP,
                        "unit": "min",
                    },
                    actions={"set_value": _set_work_time},
                )
            )

        # 5) 剩余时间
        if _field(profile, _LEFT_TIME_SID, "time") is not None:
            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="left_time",
                    name="剩余时间",
                    state=lambda ctx: {
                        "native_value": _number(ctx.value(_LEFT_TIME_SID, "time"))
                    },
                    metadata={"unit": "min", "state_class": "measurement"},
                )
            )

        # 6) 制作时长
        if _field(profile, _WORK_TIME_SID, "time") is not None:
            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="work_time",
                    name="制作时长",
                    state=lambda ctx: {
                        "native_value": _number(ctx.value(_WORK_TIME_SID, "time"))
                    },
                    metadata={"unit": "min", "state_class": "measurement"},
                )
            )

        # 7) 预约开关
        if _field(profile, _PRESET_SID, "on") is not None:
            specs.append(
                EntitySpec(
                    platform="switch",
                    key="preset",
                    name="预约",
                    state=lambda ctx: {
                        "is_on": _bool(ctx.value(_PRESET_SID, "on"))
                    },
                    actions={"turn_on": _preset_on, "turn_off": _preset_off},
                )
            )

        # 8) 预约完成时间
        if _field(profile, _PRE_TIME_END_SID, "time") is not None:
            specs.append(
                EntitySpec(
                    platform="number",
                    key="pre_time_end",
                    name="预约完成时间",
                    state=lambda ctx: {
                        "native_value": _number(
                            ctx.value(_PRE_TIME_END_SID, "time")
                        )
                    },
                    metadata={
                        "min": _PRE_TIME_END_RANGE[0],
                        "max": _PRE_TIME_END_RANGE[1],
                        "step": _PRE_TIME_END_STEP,
                        "unit": "min",
                    },
                    actions={"set_value": _set_pre_time_end},
                )
            )

        # 9) 已保温
        if _field(profile, _WARM_TIME_SID, "warmTime") is not None:
            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="warm_time",
                    name="已保温",
                    state=lambda ctx: {
                        "native_value": _number(
                            ctx.value(_WARM_TIME_SID, "warmTime")
                        )
                    },
                    metadata={"unit": "min", "state_class": "measurement"},
                )
            )

        # 10) 故障
        if _field(profile, _FAULT_SID, "status") is not None:
            specs.append(
                EntitySpec(
                    platform="binary_sensor",
                    key="fault_problem",
                    name="故障告警",
                    state=lambda ctx: {
                        "is_on": _bool(ctx.value(_FAULT_SID, "status"))
                    },
                    metadata={"device_class": "problem"},
                )
            )
        if _field(profile, _FAULT_SID, "code") is not None:
            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="fault_code",
                    name="故障代码",
                    state=lambda ctx: {
                        "native_value": _enum_label(
                            ctx.profile, _FAULT_SID, "code",
                            ctx.value(_FAULT_SID, "code"),
                        )
                    },
                )
            )

        # 11) 网络
        if _field(profile, _NET_SID, "RSSI") is not None:
            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="wifi_rssi",
                    name="信号强度 RSSI",
                    state=lambda ctx: {
                        "native_value": _number(ctx.value(_NET_SID, "RSSI"))
                    },
                    metadata={
                        "unit": "dBm",
                        "device_class": "signal_strength",
                        "state_class": "measurement",
                    },
                )
            )
        if _field(profile, _NET_SID, "intensity") is not None:
            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="wifi_level",
                    name="信号等级",
                    state=lambda ctx: {
                        "native_value": _enum_label(
                            ctx.profile, _NET_SID, "intensity",
                            ctx.value(_NET_SID, "intensity"),
                        )
                    },
                )
            )
        for char_name, key, label in (
            ("IP", "wifi_ip", "IP 地址"),
            ("SSID", "wifi_ssid", "Wi-Fi 名称"),
        ):
            if _field(profile, _NET_SID, char_name) is None:
                continue
            specs.append(
                EntitySpec(
                    platform="sensor",
                    key=key,
                    name=label,
                    state=lambda ctx, _n=char_name: {
                        "native_value": _text(ctx.value(_NET_SID, _n))
                    },
                )
            )

        return tuple(specs)


ADAPTER = Product20PXAdapter()
