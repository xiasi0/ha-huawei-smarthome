"""Huawei Vision SE55 (V0B2 / DESC-250) adapter.

Profile: https://smarthome-drcn.dbankcdn.com/device/guide/V0B2/V0B2.json

Based on the V0B3 adapter. Verified on SE55 hardware.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

# ---------------------------------------------------------------- 服务 / 字段

# 电源：screen.on 是实测有效的写入目标；switch.on / devicestate.screenState 作兜底。
_SCREEN_SID = "screen"
_SCREEN_ON_FIELD = "on"
_LEGACY_SWITCH_SID = "switch"
_LEGACY_SWITCH_ON_FIELD = "on"

_DEVICE_STATE_SID = "devicestate"
_SCREEN_STATE_FIELD = "screenState"
_SCREEN_STATE_ON = 1
_SCREEN_STATE_FALLBACK_LABELS = {0: "熄屏", 1: "在线", 2: "离线"}

_SPEAKER_SID = "speaker"
_SPEAKER_VOLUME_FIELD = "volume"
_SPEAKER_MUTE_FIELD = "mute"
_VOLUME_MAX = 100

_INPUT_SOURCE_SID = "inputSource"
_INPUT_SOURCE_FIELD = "name"
# 厂商面板可切的信号源是封闭集合，此处只列主流 HDMI + AV/TV；写错值云端会回 errcode 非 0。
_INPUT_SOURCES = ("HDMI1", "HDMI2", "HDMI3", "HDMI4", "AV", "TV")

_VIDEO_PLAYER_SID = "videoPlayer"
_AUDIO_PLAYER_SID = "audioPlayer"

# 播放器上报超过这个时长就算陈旧：电视断电后最后一次的剧名会一直留在云端。
_STALE_AFTER = timedelta(minutes=30)

_PLAYER_STATE_MAP = {
    "PLAYING": "playing",
    "PAUSED": "paused",
    "BUFFERING": "buffering",
    "PREPARING": "buffering",
    "STOPPED": "idle",
    "STOP": "idle",
    "FINISHED": "idle",
    "COMPLETED": "idle",
    "IDLE": "idle",
}
_ACTIVE_PLAYER_STATES = frozenset({"PLAYING", "PAUSED", "BUFFERING", "PREPARING"})


# ------------------------------------------------------------------- 取值工具


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


def _json(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        import json

        parsed = json.loads(value)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, Mapping) else {}


def _field(
    profile: Mapping[str, Any],
    sid: str,
    name: str,
) -> Mapping[str, Any] | None:
    for service in profile.get("services", ()):
        if not isinstance(service, Mapping) or service.get("serviceId") != sid:
            continue
        for characteristic in service.get("characteristics", ()):
            if (
                isinstance(characteristic, Mapping)
                and characteristic.get("characteristicName") == name
            ):
                return characteristic
    return None


def _enum_labels(field: Mapping[str, Any] | None) -> dict[int, str]:
    labels: dict[int, str] = {}
    if not field:
        return labels
    for option in field.get("enumList", ()):
        if not isinstance(option, Mapping):
            continue
        value = _number(option.get("enumVal"))
        if not isinstance(value, int):
            continue
        label = option.get("descCh") or option.get("descEn")
        if isinstance(label, str) and label.strip():
            labels[value] = label.strip()
    return labels


def _is_writable(field: Mapping[str, Any] | None) -> bool:
    """Profile ``permission`` 里的 ``P`` 表示允许云端下发。"""

    if not field:
        return False
    permission = field.get("permission")
    return isinstance(permission, str) and "P" in permission.upper()


def _fresh(device: DeviceContext, sid: str) -> bool:
    """设备最近是否推过这个服务（播放器状态不能无限期当"正在播放"）。"""

    stamp = device.service_updated_at(sid)
    if stamp is None:
        return True
    return datetime.now(timezone.utc) - stamp <= _STALE_AFTER


def _active_player(device: DeviceContext) -> tuple[str, Mapping[str, Any]]:
    video = (
        device.service_state(_VIDEO_PLAYER_SID)
        if device.has_service(_VIDEO_PLAYER_SID)
        else {}
    )
    audio = (
        device.service_state(_AUDIO_PLAYER_SID)
        if device.has_service(_AUDIO_PLAYER_SID)
        else {}
    )
    for sid, state in ((_VIDEO_PLAYER_SID, video), (_AUDIO_PLAYER_SID, audio)):
        if (
            str(state.get("state") or "").upper() in _ACTIVE_PLAYER_STATES
            and _fresh(device, sid)
        ):
            return sid, state
    return (_VIDEO_PLAYER_SID, video) if video else (_AUDIO_PLAYER_SID, audio)


# ------------------------------------------------------------------- 读取逻辑


def _screen_on(device: DeviceContext) -> bool | None:
    """电源状态：优先 ``screen.on``（真机真实字段），兜底 ``devicestate.screenState``。"""

    if device.has_service(_SCREEN_SID):
        value = device.value(_SCREEN_SID, _SCREEN_ON_FIELD)
        flag = _bool(value)
        if flag is not None:
            return flag
    state = _number(device.value(_DEVICE_STATE_SID, _SCREEN_STATE_FIELD))
    if state is None:
        return None
    return state == _SCREEN_STATE_ON


def _player_state(device: DeviceContext) -> str | None:
    if _screen_on(device) is False:
        return "off"
    sid, player = _active_player(device)
    mapped = _PLAYER_STATE_MAP.get(str(player.get("state") or "").upper())
    if mapped in {"playing", "paused", "buffering"} and _fresh(device, sid):
        return mapped
    return "on" if _screen_on(device) is True else mapped


def _volume_level(device: DeviceContext) -> float | None:
    volume = _number(device.value(_SPEAKER_SID, _SPEAKER_VOLUME_FIELD))
    if volume is None:
        return None
    return max(0.0, min(1.0, volume / _VOLUME_MAX))


def _media_state(device: DeviceContext) -> Mapping[str, Any]:
    sid, player = _active_player(device)
    is_video = sid == _VIDEO_PLAYER_SID
    playing = _player_state(device) in {"playing", "paused", "buffering"}
    metadata = _json(player.get("metadata")) if playing else {}
    progress = _number(player.get("progress")) if playing else None
    duration = (
        _number(metadata.get("totalTime") if is_video else metadata.get("duration"))
        if playing
        else None
    )
    # 进度单位是毫秒。
    position = None if progress is None else progress / 1000.0

    return {
        "state": _player_state(device),
        "volume_level": _volume_level(device),
        "is_volume_muted": _bool(device.value(_SPEAKER_SID, _SPEAKER_MUTE_FIELD)),
        "media_title": _text(metadata.get("vodName") or metadata.get("title")),
        "media_artist": None if is_video else _text(metadata.get("artist")),
        "media_album_name": None if is_video else _text(metadata.get("album")),
        "media_series_title": _text(metadata.get("vodName")) if is_video else None,
        "media_image_url": _text(metadata.get("titlePicture")) if is_video else None,
        "media_position": position,
        "media_duration": duration,
        "media_position_updated_at": (
            device.service_updated_at(sid) if position is not None else None
        ),
        "source": _text(device.value(_INPUT_SOURCE_SID, _INPUT_SOURCE_FIELD)),
        "source_list": list(_INPUT_SOURCES)
        if device.has_service(_INPUT_SOURCE_SID)
        else None,
    }


# ------------------------------------------------------------------- 写入动作


async def _send_power(device: DeviceContext, *, on: bool) -> None:
    """依次尝试可写通道，任一成功即返回；全部失败时抛出最后一次错误。

    实测（DESC-260）``devicestate.screenState`` 会被设备拒（``errcode=-1``），所以它只
    排最后；同代智慧屏上真正生效的是 ``screen.on``，``switch.on`` 作第二手。
    """

    flag = 1 if on else 0
    attempts = (
        (_SCREEN_SID, {_SCREEN_ON_FIELD: on}),
        (_LEGACY_SWITCH_SID, {_LEGACY_SWITCH_ON_FIELD: flag}),
        (_DEVICE_STATE_SID, {_SCREEN_STATE_FIELD: flag}),
    )
    last_error: Exception | None = None
    for sid, payload in attempts:
        if not device.has_service(sid):
            continue
        try:
            await device.async_send_service(sid, payload)
            return
        except Exception as err:  # noqa: BLE001 - 逐通道退避，保留最后一个错误
            last_error = err
    if last_error is not None:
        raise last_error
    raise ValueError("device reports no usable power channel")


async def _power(device: DeviceContext, _data: Mapping[str, Any]) -> None:
    await _send_power(device, on=True)


async def _power_off(device: DeviceContext, _data: Mapping[str, Any]) -> None:
    await _send_power(device, on=False)


async def _set_volume(device: DeviceContext, _data: Mapping[str, Any]) -> None:
    """HA 交来 0~1 浮点，设备要 0~100。"""

    raw = _data.get("volume")
    level = _number(raw)
    if level is None:
        return
    if isinstance(raw, float) and 0.0 <= raw <= 1.0:
        level = round(raw * _VOLUME_MAX)
    level = min(max(level, 0), _VOLUME_MAX)
    await device.async_send_service(
        _SPEAKER_SID, {_SPEAKER_VOLUME_FIELD: int(level)}
    )


async def _set_mute(device: DeviceContext, _data: Mapping[str, Any]) -> None:
    muted = _bool(_data.get("mute"))
    if muted is None:
        muted = True
    await device.async_send_service(_SPEAKER_SID, {_SPEAKER_MUTE_FIELD: muted})


async def _select_source(device: DeviceContext, _data: Mapping[str, Any]) -> None:
    source = _text(_data.get("source"))
    if source is None:
        return
    await device.async_send_service(_INPUT_SOURCE_SID, {_INPUT_SOURCE_FIELD: source})


# ------------------------------------------------------------------- 实体构造


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


def _screen_state_spec(labels: Mapping[int, str]) -> EntitySpec:
    def read(device: DeviceContext) -> str | None:
        state = _number(device.value(_DEVICE_STATE_SID, _SCREEN_STATE_FIELD))
        if state is None:
            return None
        return labels.get(state) or str(state)

    return _sensor_spec("screen_state", "屏幕状态", read)


def _screen_on_reader(device: DeviceContext) -> Mapping[str, Any]:
    """电源状态读取器（供 switch 实体使用）。"""

    return {"is_on": _screen_on(device)}


def _power_switch_spec() -> EntitySpec:
    async def turn_on(device: DeviceContext, _data: Mapping[str, Any]) -> None:
        await _send_power(device, on=True)

    async def turn_off(device: DeviceContext, _data: Mapping[str, Any]) -> None:
        await _send_power(device, on=False)

    return EntitySpec(
        platform="switch",
        key="power_switch",
        name="电源",
        state=_screen_on_reader,
        metadata={},
        actions={"turn_on": turn_on, "turn_off": turn_off},
        # 熄屏时云端可能把设备标为离线；跟随该标记会让开关失效、再也发不出唤醒命令。
        availability=lambda _device: True,
    )


def _mute_reader(device: DeviceContext) -> Mapping[str, Any]:
    """静音状态读取器（供 switch 实体使用）。"""

    return {"is_on": _bool(device.value(_SPEAKER_SID, _SPEAKER_MUTE_FIELD))}


def _mute_switch_spec() -> EntitySpec:
    async def turn_on(device: DeviceContext, _data: Mapping[str, Any]) -> None:
        await _set_mute(device, {"mute": True})

    async def turn_off(device: DeviceContext, _data: Mapping[str, Any]) -> None:
        await _set_mute(device, {"mute": False})

    return EntitySpec(
        platform="switch",
        key="mute_switch",
        name="静音",
        state=_mute_reader,
        metadata={},
        actions={"turn_on": turn_on, "turn_off": turn_off},
    )


def _media_player_spec() -> EntitySpec:
    return EntitySpec(
        platform="media_player",
        key="tv",
        name="电视",
        state=_media_state,
        metadata={},
        actions={
            "turn_on": _power,
            "turn_off": _power_off,
            "volume": _set_volume,
            "select_source": _select_source,
        },
    )


class ProductV0B2Adapter:
    """华为智慧屏 SE55 (DESC-250)：电源 + 屏幕状态 + 电视播放器 + 静音。"""

    prod_id = "V0B2"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        entities: list[EntitySpec] = []

        if context.has_service(_SCREEN_SID) or context.has_service(_DEVICE_STATE_SID):
            field = _field(profile, _DEVICE_STATE_SID, _SCREEN_STATE_FIELD)
            labels = _enum_labels(field) or _SCREEN_STATE_FALLBACK_LABELS
            entities.append(_screen_state_spec(labels))
            if context.has_service(_SCREEN_SID) or _is_writable(field):
                entities.append(_power_switch_spec())

        if context.has_service(_VIDEO_PLAYER_SID) or context.has_service(
            _AUDIO_PLAYER_SID
        ):
            entities.append(_media_player_spec())

        if context.has_service(_SPEAKER_SID):
            entities.append(_mute_switch_spec())

        return tuple(entities)


ADAPTER = ProductV0B2Adapter()
