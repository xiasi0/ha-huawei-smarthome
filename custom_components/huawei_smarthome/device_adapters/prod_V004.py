"""User-contributed protocol for Huawei product V004.

Product: HUAWEI Vision Smart Screen (deviceModel ``KANT``, prodId ``V004``),
the series sold as 华为智慧屏 S / S65.
Profile: https://smarthome-drcn.dbankcdn.com/device/guide/V004/V004.json

The public Profile only declares six services (messageboard, remotecontrol,
autoconfig, devicestate, generalcommand, logreport), but a live S65 reports
around thirty.  Every entity below is built from the services the device really
publishes, and each one is dropped when its service is missing, so an
unexpected revision degrades to a missing entity instead of a wrong state.

    switch         on                       (1 = 开机, 2 = 待机/关机)
    screen         on / brightness
    speaker        volume / mute / equalizer
    inputSource    defaultSource
    pictureMode    mode
    systemMode     mode
    screenSaver    switch
    childMode      mode / watchTime
    devicestate    screenState              (0 熄屏 / 1 在线 / 2 离线)
    remotecontrol  ip_addr / switchState

Only ``devicestate.screenState`` carries enum labels in the Profile.  The public
Profile declares no ``pictureMode`` service at all, so the picture-mode labels
were measured on a live panel instead of read from it; every other value is
shown exactly as reported.

This adapter is deliberately a pure state reader.  The SmartHome cloud write
channel is not usable for this product yet: the vendor plugin drives the panel
over the LAN using the ``remotecontrol`` access token, and an unverified remote
write comes back rejected (a childMode write was answered with errcode -1 on a
live device).  A control that reports success without acting is worse than a
missing one, so no action is declared until one is confirmed on real hardware.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_POWER_SID = "switch"
_POWER_FIELD = "on"
_POWER_ON = 1

_SCREEN_STATE_SID = "devicestate"
_SCREEN_STATE_FIELD = "screenState"

_SCREEN_SID = "screen"
_SCREEN_BRIGHTNESS_FIELD = "brightness"

_SPEAKER_SID = "speaker"
_SPEAKER_VOLUME_FIELD = "volume"
_SPEAKER_MUTE_FIELD = "mute"
_SPEAKER_EQUALIZER_FIELD = "equalizer"

_INPUT_SOURCE_SID = "inputSource"
_INPUT_SOURCE_FIELD = "defaultSource"

_PICTURE_MODE_SID = "pictureMode"
_PICTURE_MODE_FIELD = "mode"

_SYSTEM_MODE_SID = "systemMode"
_SYSTEM_MODE_FIELD = "mode"

_SCREEN_SAVER_SID = "screenSaver"
_SCREEN_SAVER_FIELD = "switch"
_SCREEN_SAVER_ON = 1

_CHILD_MODE_SID = "childMode"
_CHILD_MODE_FIELD = "mode"
_CHILD_MODE_OFF = "OFF"

# The panel reports a bare number here with nothing in the Profile to resolve it
# against.  These labels were read off a live S65 by switching every preset from
# the TV menu one at a time and noting what the integration received for each:
#
#     0 标准   1 自动   2 柔和   4 鲜艳   5 少儿
#     6 体育   7 照片   8 电影   9 游戏
#
# Nine presets cover nine distinct values, and the run closed back on 自动 = 1,
# which is also what the panel kept reporting on its own afterwards.  Value 3
# was never seen, so it stays a bare number rather than a guess.
_PICTURE_MODE_LABELS = {
    0: "标准",
    1: "自动",
    2: "柔和",
    4: "鲜艳",
    5: "少儿",
    6: "体育",
    7: "照片",
    8: "电影",
    9: "游戏",
}

_REMOTE_CONTROL_SID = "remotecontrol"
_REMOTE_CONTROL_IP_FIELD = "ip_addr"
_REMOTE_CONTROL_SWITCH_FIELD = "switchState"
_REMOTE_CONTROL_ON = 1


def _service(profile: Mapping[str, Any], sid: str) -> Mapping[str, Any] | None:
    for service in profile.get("services", ()):
        if isinstance(service, Mapping) and service.get("serviceId") == sid:
            return service
    return None


def _field(
    profile: Mapping[str, Any],
    sid: str,
    name: str,
) -> Mapping[str, Any] | None:
    service = _service(profile, sid)
    if service is None:
        return None
    for field in service.get("characteristics", ()):
        if isinstance(field, Mapping) and field.get("characteristicName") == name:
            return field
    return None


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.casefold()
        if normalized in {"1", "true", "on"}:
            return True
        if normalized in {"0", "false", "off"}:
            return False
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _text(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (str, int, float)):
        text = str(value).strip()
        return text or None
    return None


def _enum_label(field: Mapping[str, Any], value: Any) -> str | None:
    """Return the Profile label for one enum value."""

    number = _number(value)
    if number is None:
        return None
    for option in field.get("enumList", ()):
        if not isinstance(option, Mapping):
            continue
        if _number(option.get("enumVal")) != number:
            continue
        label = option.get("descCh") or option.get("descEn")
        if isinstance(label, str) and label:
            return label
    return None


def _value_reader(
    sid: str,
    field: str,
    coerce: Callable[[Any], Any],
) -> Callable[[DeviceContext], Any]:
    def read(device: DeviceContext) -> Any:
        return coerce(device.value(sid, field))

    return read


def _sensor_spec(
    key: str,
    name: str,
    read: Callable[[DeviceContext], Any],
    metadata: Mapping[str, Any] | None = None,
) -> EntitySpec:
    def state(device: DeviceContext) -> Mapping[str, Any]:
        return {"native_value": read(device)}

    return EntitySpec(
        platform="sensor",
        key=key,
        name=name,
        state=state,
        metadata=dict(metadata or {}),
    )


def _binary_spec(
    key: str,
    name: str,
    read: Callable[[DeviceContext], Any],
    device_class: str | None = None,
) -> EntitySpec:
    def state(device: DeviceContext) -> Mapping[str, Any]:
        return {"is_on": read(device)}

    metadata = {"device_class": device_class} if device_class else {}
    return EntitySpec(
        platform="binary_sensor",
        key=key,
        name=name,
        state=state,
        metadata=metadata,
    )


def _power_spec() -> EntitySpec:
    def read(device: DeviceContext) -> bool | None:
        value = _number(device.value(_POWER_SID, _POWER_FIELD))
        if value is None:
            return None
        return value == _POWER_ON

    return _binary_spec("power", "电源", read, "power")


def _screen_state_spec(profile: Mapping[str, Any]) -> EntitySpec:
    field = _field(profile, _SCREEN_STATE_SID, _SCREEN_STATE_FIELD) or {}

    def read(device: DeviceContext) -> Any:
        value = _number(device.value(_SCREEN_STATE_SID, _SCREEN_STATE_FIELD))
        if value is None:
            return None
        return _enum_label(field, value) or str(value)

    return _sensor_spec("screen_state", "屏幕状态", read)


def _screen_brightness_spec() -> EntitySpec:
    return _sensor_spec(
        "screen_brightness",
        "屏幕亮度",
        _value_reader(_SCREEN_SID, _SCREEN_BRIGHTNESS_FIELD, _number),
        {"unit": "%", "state_class": "measurement"},
    )


def _volume_spec() -> EntitySpec:
    # The device also exposes a bare ``volume`` service whose field has only
    # ever been reported as "0", while ``speaker`` carries volume together with
    # mute and equalizer.  The coherent speaker reading is the one surfaced.
    return _sensor_spec(
        "volume",
        "音量",
        _value_reader(_SPEAKER_SID, _SPEAKER_VOLUME_FIELD, _number),
        {"unit": "%", "state_class": "measurement"},
    )


def _mute_spec() -> EntitySpec:
    return _binary_spec(
        "mute",
        "静音",
        _value_reader(_SPEAKER_SID, _SPEAKER_MUTE_FIELD, _bool),
        "sound",
    )


def _sound_mode_spec() -> EntitySpec:
    return _sensor_spec(
        "sound_mode",
        "音效模式",
        _value_reader(_SPEAKER_SID, _SPEAKER_EQUALIZER_FIELD, _text),
    )


def _input_source_spec() -> EntitySpec:
    return _sensor_spec(
        "input_source",
        "信号源",
        _value_reader(_INPUT_SOURCE_SID, _INPUT_SOURCE_FIELD, _text),
    )


def _picture_mode_spec() -> EntitySpec:
    def read(device: DeviceContext) -> Any:
        raw = device.value(_PICTURE_MODE_SID, _PICTURE_MODE_FIELD)
        number = _number(raw)
        if isinstance(number, int):
            return _PICTURE_MODE_LABELS.get(number, str(number))
        return _text(raw)

    return _sensor_spec("picture_mode", "图像模式", read)


def _system_mode_spec() -> EntitySpec:
    return _sensor_spec(
        "system_mode",
        "系统模式",
        _value_reader(_SYSTEM_MODE_SID, _SYSTEM_MODE_FIELD, _text),
    )


def _screen_saver_spec() -> EntitySpec:
    def read(device: DeviceContext) -> bool | None:
        value = _number(device.value(_SCREEN_SAVER_SID, _SCREEN_SAVER_FIELD))
        if value is None:
            return None
        return value == _SCREEN_SAVER_ON

    return _binary_spec("screen_saver", "屏保", read)


def _child_mode_spec() -> EntitySpec:
    def read(device: DeviceContext) -> bool | None:
        value = _text(device.value(_CHILD_MODE_SID, _CHILD_MODE_FIELD))
        if value is None:
            return None
        return value.upper() != _CHILD_MODE_OFF

    return _binary_spec("child_mode", "儿童模式", read)


def _ip_address_spec() -> EntitySpec:
    return _sensor_spec(
        "ip_address",
        "设备 IP",
        _value_reader(_REMOTE_CONTROL_SID, _REMOTE_CONTROL_IP_FIELD, _text),
    )


def _remote_control_spec() -> EntitySpec:
    def read(device: DeviceContext) -> bool | None:
        value = _number(
            device.value(_REMOTE_CONTROL_SID, _REMOTE_CONTROL_SWITCH_FIELD)
        )
        if value is None:
            return None
        return value == _REMOTE_CONTROL_ON

    return _binary_spec("remote_control", "遥控开关", read)


class ProductV004Adapter:
    """HUAWEI Vision Smart Screen (KANT) entity choices."""

    prod_id = "V004"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile or {}
        entities: list[EntitySpec] = []
        if context.has_service(_POWER_SID):
            entities.append(_power_spec())
        if context.has_service(_SCREEN_STATE_SID):
            entities.append(_screen_state_spec(profile))
        if context.has_service(_SCREEN_SID):
            entities.append(_screen_brightness_spec())
        if context.has_service(_SPEAKER_SID):
            entities.append(_volume_spec())
            entities.append(_mute_spec())
            entities.append(_sound_mode_spec())
        if context.has_service(_INPUT_SOURCE_SID):
            entities.append(_input_source_spec())
        if context.has_service(_PICTURE_MODE_SID):
            entities.append(_picture_mode_spec())
        if context.has_service(_SYSTEM_MODE_SID):
            entities.append(_system_mode_spec())
        if context.has_service(_SCREEN_SAVER_SID):
            entities.append(_screen_saver_spec())
        if context.has_service(_CHILD_MODE_SID):
            entities.append(_child_mode_spec())
        if context.has_service(_REMOTE_CONTROL_SID):
            entities.append(_ip_address_spec())
            entities.append(_remote_control_spec())
        return tuple(entities)


ADAPTER = ProductV004Adapter()
