"""User-contributed protocol for Huawei product 2RNH.

Device: 海雀智能摄像头 双雀Pro / Huawei HiLink smart camera
(deviceModel ``AE310``, manufacturer 深圳市海雀科技有限公司,
deviceTypeId ``008``/网络摄像头, protocolType ``1``/WiFi).
Profile: https://smarthome-drcn.dbankcdn.com/device/guide/2RNH/2RNH.json

Field evidence
--------------
All service ids, characteristic names and enum meanings below are taken from
``2RNH.json``.  The device reports 23 services; the ones used here are:

    switch        {on bool RW}                    摄像头开关
    videoSwitch   {on bool RW}                    摄像开关
    shootSwitch   {on bool RW}                    拍照开关
    cruiseSwitch  {on bool RW}                    全景巡航
    cruiseSwitch2 {on bool RW}                    巡航2
    localMode     {on bool RW}                    本地模式
    alarmEvent    {animalAlarm, babyCryAlarm, audioAlarm, videoAlarm,
                   humanBodyAlarm, alarm  — all bool R}
    voip          {voipCall bool RW, calling bool R, message string R}
    visitPoint1..12 {enable bool RW, move bool RW}
    netInfo       {RSSI int R, intensity enum R, SSID/IP/BSSID string R}

``visitPoint`` semantics are declared by the Profile itself:
``enable`` = 预置点已配置(1)/未配置(0); ``move`` = 移到该预置点(1)/无动作(0).

Exposed entities
----------------
* ``switch``        摄像头 / 摄像开关 / 拍照开关 / 全景巡航 / 巡航2 / 本地模式
* ``binary_sensor`` 综合告警 / 婴儿哭声(sound) / 人形侦测(motion) /
                    声音告警(sound) / 移动侦测(motion) / 动物侦测(motion)
* ``binary_sensor`` 视频通话中
* ``button``        视频通话
* ``button``        预置点1..12（仅当 Profile 声明该 visitPoint 服务时创建）
* ``sensor``        信号强度 RSSI / 信号等级 / IP 地址 / Wi-Fi 名称

Not exposed (app-managed or no verified semantics): ``update`` (OTA),
``logReport``, ``diagnose``, ``deviceInfo``, ``alarmEvent2``, ``timer``,
``delay``, ``commonFaultDetection``, ``timeZone``, ``ctlCapability``.
Video streaming itself is not part of this protocol.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext


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


def _enum_text(context: DeviceContext, sid: str, name: str) -> str | None:
    raw = context.value(sid, name)
    if raw is None or isinstance(raw, bool):
        return None
    try:
        key = str(int(str(raw).strip()))
    except (TypeError, ValueError):
        return _text(raw)
    field = _field(context.profile, sid, name)
    if field is None:
        return None
    for option in field.get("enumList", ()) or ():
        if isinstance(option, Mapping) and str(option.get("enumVal")) == key:
            return str(option.get("descCh") or option.get("enumVal"))
    return None


def _switch_spec(
    profile: Any, sid: str, key: str, name: str
) -> EntitySpec | None:
    if _field(profile, sid, "on") is None:
        return None

    async def turn_on(context: DeviceContext, _data: Mapping[str, Any], _sid: str = sid) -> None:
        await context.async_send_service(_sid, {"on": 1})

    async def turn_off(context: DeviceContext, _data: Mapping[str, Any], _sid: str = sid) -> None:
        await context.async_send_service(_sid, {"on": 0})

    return EntitySpec(
        platform="switch",
        key=key,
        name=name,
        state=lambda ctx, _sid=sid: {"is_on": _bool(ctx.value(_sid, "on"))},
        actions={"turn_on": turn_on, "turn_off": turn_off},
    )


def _binary_spec(
    profile: Any,
    sid: str,
    field_name: str,
    name: str,
    **metadata: Any,
) -> EntitySpec | None:
    if _field(profile, sid, field_name) is None:
        return None
    return EntitySpec(
        platform="binary_sensor",
        key=f"{sid}_{field_name}",
        name=name,
        state=lambda ctx, _sid=sid, _fn=field_name: {
            "is_on": _bool(ctx.value(_sid, _fn))
        },
        metadata=metadata,
    )


def _button_spec(
    profile: Any, sid: str, field_name: str, name: str
) -> EntitySpec | None:
    if _field(profile, sid, field_name) is None:
        return None

    async def press(context: DeviceContext, _data: Mapping[str, Any], _sid: str = sid, _fn: str = field_name) -> None:
        await context.async_send_service(_sid, {_fn: 1})

    return EntitySpec(
        platform="button",
        key=f"{sid}_{field_name}",
        name=name,
        state=lambda ctx: {},
        actions={"press": press},
    )


class Product2RNHAdapter:
    """海雀智能摄像头 双雀Pro (AE310)."""

    prod_id = "2RNH"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        specs: list[EntitySpec] = []

        for sid, key, name in (
            ("switch", "camera", "摄像头"),
            ("videoSwitch", "video", "摄像开关"),
            ("shootSwitch", "shoot", "拍照开关"),
            ("cruiseSwitch", "cruise", "全景巡航"),
            ("cruiseSwitch2", "cruise2", "巡航2"),
            ("localMode", "local_mode", "本地模式"),
        ):
            spec = _switch_spec(profile, sid, key, name)
            if spec is not None:
                specs.append(spec)

        for field_name, name, device_class in (
            ("alarm", "综合告警", None),
            ("babyCryAlarm", "婴儿哭声", "sound"),
            ("humanBodyAlarm", "人形侦测", "motion"),
            ("audioAlarm", "声音告警", "sound"),
            ("videoAlarm", "移动侦测", "motion"),
            ("animalAlarm", "动物侦测", "motion"),
        ):
            metadata = {"device_class": device_class} if device_class else {}
            spec = _binary_spec(profile, "alarmEvent", field_name, name, **metadata)
            if spec is not None:
                specs.append(spec)

        calling = _binary_spec(profile, "voip", "calling", "视频通话中")
        if calling is not None:
            specs.append(calling)
        call = _button_spec(profile, "voip", "voipCall", "视频通话")
        if call is not None:
            specs.append(call)

        for service in profile.get("services", ()):
            if not isinstance(service, Mapping):
                continue
            sid = service.get("serviceId")
            if not isinstance(sid, str) or not sid.startswith("visitPoint"):
                continue
            suffix = sid.removeprefix("visitPoint")
            spec = _button_spec(profile, sid, "move", f"预置点{suffix}")
            if spec is not None:
                specs.append(spec)

        if _field(profile, "netInfo", "RSSI") is not None:
            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="rssi",
                    name="信号强度 RSSI",
                    state=lambda device: {
                        "native_value": _number(device.value("netInfo", "RSSI"))
                    },
                    metadata={
                        "unit": "dBm",
                        "device_class": "signal_strength",
                        "state_class": "measurement",
                    },
                )
            )
        if _field(profile, "netInfo", "intensity") is not None:
            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="wifi_level",
                    name="信号等级",
                    state=lambda device: {
                        "native_value": _enum_text(device, "netInfo", "intensity")
                    },
                )
            )
        for char_name, key, label in (
            ("IP", "wifi_ip", "IP 地址"),
            ("SSID", "wifi_ssid", "Wi-Fi 名称"),
        ):
            if _field(profile, "netInfo", char_name) is None:
                continue
            specs.append(
                EntitySpec(
                    platform="sensor",
                    key=key,
                    name=label,
                    state=lambda device, _n=char_name: {
                        "native_value": _text(device.value("netInfo", _n))
                    },
                )
            )

        return tuple(specs)


ADAPTER = Product2RNHAdapter()
