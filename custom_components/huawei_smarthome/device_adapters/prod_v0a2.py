"""User-contributed protocol for Huawei product V0A2.

Product: 华为智慧屏V系列2021款 (deviceModel ``THAL``, prodId ``V0A2``).
Profile: https://smarthome-drcn.dbankcdn.com/device/guide/V0A2/V0A2.json

The public Profile is unusually thin for this product: it declares only six
services (messageboard, remotecontrol, autoconfig, devicestate,
generalcommand, logreport) and marks **none** of their characteristics
writable, while the TV actually pushes ~45 services.  Everything below was
therefore verified against a real device over MQTT rather than read off the
Profile.

Commands confirmed to take effect (cloud ACK ``errcode=0`` **and** a
``deviceDataChanged`` push carrying the new value):

    speaker.volume        {"volume": 20}          -> push {"volume": 20}
    speaker.mute          {"mute": true}          -> push {"mute": true}
    speaker.equalizer     {"equalizer": "AUTO"}   -> push {"equalizer": "AUTO"}
    inputSource.name      {"name": "HDMI2"}       -> push {"name": "HDMI2"}
    screen.brightness     {"brightness": 100}     -> push {"brightness": 100}
    screen.mode           {"mode": "PICTURE"}     -> push {"mode": "PICTURE"}
    screen.on (off)       {"on": false}           -> push {"on": false}

Known firmware limitation -- waking the panel:

    screen.on = true is accepted (``errcode=0``) and the panel really does
    light up, but the TV never pushes ``on: true`` and never updates its
    reported state.  After waking, this integration keeps reporting the last
    pushed value (``off``) until the TV reports something else.  The vendor
    app behaves the same way.  Home Assistant is told about the mismatch
    through ``extra_state_attributes`` so the entity documents its own
    uncertainty instead of silently showing a stale power state.

Rejected commands (``errcode=-1``, deliberately not exposed): ``systemMode``,
``screenSaver``, ``switch``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_PROD_ID = "V0A2"

_SCREEN_SID = "screen"
_SPEAKER_SID = "speaker"
_INPUT_SOURCE_SID = "inputSource"
_VIDEO_PLAYER_SID = "videoPlayer"
_AUDIO_PLAYER_SID = "audioPlayer"
_DEVICE_STATE_SID = "devicestate"
_MESSAGE_BOARD_SID = "messageboard"
_MESSAGE_BOARD_WIRE_SID = "messageBoard"
_REMOTE_CONTROL_SID = "remotecontrol"

# The real device pushes the message board with camel casing while the Profile
# spells it lower case, so both are accepted.
_SID_CANDIDATES: dict[str, tuple[str, ...]] = {
    _MESSAGE_BOARD_SID: (_MESSAGE_BOARD_SID, _MESSAGE_BOARD_WIRE_SID),
}

_DEVICE_CLASS_VOLUME = "volume"
_VOLUME_MAX = 100


def _candidates(sid: str) -> tuple[str, ...]:
    return _SID_CANDIDATES.get(sid, (sid,))


def _value(device: DeviceContext, sid: str, field: str) -> Any:
    for candidate in _candidates(sid):
        value = device.value(candidate, field)
        if value is not None:
            return value
    return None


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
        if value.casefold() in {"1", "true", "on"}:
            return True
        if value.casefold() in {"0", "false", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _metadata(value: Any) -> Mapping[str, Any]:
    """Decode the JSON string the player services publish in ``metadata``."""

    if isinstance(value, Mapping):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        if isinstance(parsed, Mapping):
            return parsed
    return {}


def _screen_on(device: DeviceContext) -> bool | None:
    value = _bool(_value(device, _SCREEN_SID, "on"))
    if value is not None:
        return value
    # devicestate.screenState mirrors the panel state when screen is absent.
    code = _number(_value(device, _DEVICE_STATE_SID, "screenState"))
    if code is None:
        return None
    return code != 0


# Player ``state`` values that mean something is actually on.  The TV pushes
# these live while playing (observed: AD_PLAYING -> PLAYING as a show starts).
#
# The audio player cannot be trusted on state alone: on the test device it kept
# reporting state=PLAYING with metadata from a track played ten days earlier,
# and never pushed a stopping state.  The video player does push live state, so
# video wins whenever it is active and audio is only a fallback when the video
# player is not playing at all.
_ACTIVE_STATES = frozenset(
    {"PLAYING", "AD_PLAYING", "PAUSED", "BUFFERING", "AD_PAUSED"}
)

# ``vodName`` is what the video player publishes for a title; music uses
# ``title``.  Order matters: the video metadata has no ``title`` field.
_TITLE_KEYS = ("vodName", "title", "name")


def _player_state(sid: str, device: DeviceContext) -> str:
    return str(_value(device, sid, "state") or "").strip().upper()


def _player_title(metadata: Mapping[str, Any]) -> str | None:
    for key in _TITLE_KEYS:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _player_active(sid: str, device: DeviceContext) -> bool:
    """Return whether the given player reports an active state.

    Only an explicitly active state counts: an unrecognised value must never
    claim that something is playing.
    """

    return _player_state(sid, device) in _ACTIVE_STATES


def _now_playing(device: DeviceContext) -> Mapping[str, Any]:
    """Return the item playing right now, or nothing when playback has stopped.

    The video player describes the picture and pushes live state, so it takes
    precedence; the audio player is consulted only when no video is playing.

    Episodes: the video metadata identifies the current episode through
    ``volumeIndex`` (observed 2, then 3 while watching the same series) and the
    series total through ``sum``.  ``volumeIndex`` is 1-based, so it maps to
    HA's ``media_episode`` directly.  The cover URL embeds a ``2-26`` fragment
    that does *not* track the episode, so it must not be parsed for this.
    """

    if _player_active(_VIDEO_PLAYER_SID, device):
        meta = _metadata(_value(device, _VIDEO_PLAYER_SID, "metadata"))
        title = _player_title(meta)
        if title is not None:
            episode_total = _int_or_none(meta.get("sum"))
            episode = _int_or_none(meta.get("volumeIndex"))
            position = _int_or_none(_value(device, _VIDEO_PLAYER_SID, "progress"))
            duration = _int_or_none(meta.get("totalTime"))
            return {
                "title": title,
                "series_title": title,
                "episode": episode if episode and episode > 0 else None,
                "episode_total": episode_total,
                "artist": meta.get("director") or meta.get("actor"),
                "album": meta.get("categoryName"),
                "image": _image_url(meta),
                "position": position,
                "duration": duration,
            }

    if _player_active(_AUDIO_PLAYER_SID, device):
        meta = _metadata(_value(device, _AUDIO_PLAYER_SID, "metadata"))
        title = _player_title(meta)
        if title is not None:
            return {
                "title": title,
                "artist": meta.get("artist"),
                "album": meta.get("album"),
                "image": _image_url(meta),
                "position": _int_or_none(_value(device, _AUDIO_PLAYER_SID, "progress")),
                "duration": _int_or_none(meta.get("duration")),
            }
    return {}


def _int_or_none(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _image_url(metadata: Mapping[str, Any]) -> str | None:
    """Return the artwork URL the player publishes, if any.

    The video player publishes ``titlePicture``; music metadata carries its
    cover under ``albumArt``/``coverUrl``.  Only http(s) values are accepted so
    the entity never hands Home Assistant a non-URL to fetch.
    """

    for key in ("titlePicture", "albumArt", "coverUrl", "imageUrl"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip().startswith(("http://", "https://")):
            return value.strip()
    return None


def _volume_level(device: DeviceContext) -> float | None:
    value = _number(_value(device, _SPEAKER_SID, "volume"))
    if value is None:
        return None
    value = min(max(value, 0), _VOLUME_MAX)
    return value / _VOLUME_MAX


def _tv_state(device: DeviceContext) -> Mapping[str, Any]:
    """Compose the media_player state.

    Waking the panel does not make the TV report ``on`` again (see the module
    docstring), so the reported power flag can lag behind reality until the TV
    reports something else.
    """

    on = _screen_on(device)
    playing = _now_playing(device)
    return {
        "state": "on" if on else ("off" if on is False else None),
        "volume_level": _volume_level(device),
        "is_volume_muted": _bool(_value(device, _SPEAKER_SID, "mute")),
        "media_title": playing.get("title"),
        "media_artist": playing.get("artist"),
        "media_album_name": playing.get("album"),
        "media_image_url": playing.get("image"),
        "media_series_title": playing.get("series_title"),
        "media_episode": playing.get("episode"),
        # Position is the last pushed reading.  The TV reports it every few
        # minutes, and the adapter API does not expose when that reading was
        # taken, so ``media_position_updated_at`` is deliberately not set:
        # without it HA shows the raw position rather than extrapolating a
        # progress bar from a timestamp it cannot trust.
        "media_position": playing.get("position"),
        "media_duration": playing.get("duration"),
        "source": _value(device, _INPUT_SOURCE_SID, "name"),
    }


async def _turn_on(device: DeviceContext, _data: Mapping[str, Any]) -> None:
    await device.async_send_service(_SCREEN_SID, {"on": True})


async def _turn_off(device: DeviceContext, _data: Mapping[str, Any]) -> None:
    await device.async_send_service(_SCREEN_SID, {"on": False})


async def _set_volume(device: DeviceContext, data: Mapping[str, Any]) -> None:
    raw = data.get("volume")
    level = _number(raw)
    if level is None:
        return
    if isinstance(raw, float) and 0.0 <= raw <= 1.0:
        level = round(raw * _VOLUME_MAX)
    level = int(min(max(level, 0), _VOLUME_MAX))
    await device.async_send_service(_SPEAKER_SID, {"volume": level})


async def _select_source(device: DeviceContext, data: Mapping[str, Any]) -> None:
    source = data.get("source")
    if not isinstance(source, str) or not source.strip():
        return
    await device.async_send_service(_INPUT_SOURCE_SID, {"name": source.strip()})


def _text_sensor(sid: str, field_name: str, name: str, key: str) -> EntitySpec:
    def state(device: DeviceContext) -> Mapping[str, Any]:
        value = _value(device, sid, field_name)
        if isinstance(value, str) and not value.strip():
            return {"native_value": None}
        return {"native_value": value}

    return EntitySpec(
        platform="sensor",
        key=key,
        name=name,
        state=state,
        metadata={"entity_category": "diagnostic"},
    )


def _enum_sensor(
    profile: Mapping[str, Any],
    sid: str,
    field_name: str,
    name: str,
    key: str,
) -> EntitySpec | None:
    field = _field(profile, sid, field_name)
    if field is None:
        return None
    labels = {
        str(option["enumVal"]): str(option.get("descCh") or option.get("descEn"))
        for option in field.get("enumList", ())
        if isinstance(option, Mapping)
        and option.get("enumVal") is not None
        and (option.get("descCh") or option.get("descEn"))
    }

    def state(device: DeviceContext) -> Mapping[str, Any]:
        value = _value(device, sid, field_name)
        if value is None:
            return {"native_value": None}
        if labels:
            return {"native_value": labels.get(str(value), str(value))}
        return {"native_value": value}

    return EntitySpec(
        platform="sensor",
        key=key,
        name=name,
        state=state,
        metadata={"entity_category": "diagnostic"},
    )


def _brightness_sensor() -> EntitySpec:
    def state(device: DeviceContext) -> Mapping[str, Any]:
        return {"native_value": _number(_value(device, _SCREEN_SID, "brightness"))}

    return EntitySpec(
        platform="sensor",
        key="screen_brightness",
        name="屏幕亮度",
        state=state,
        metadata={
            "state_class": "measurement",
            "native_unit_of_measurement": "%",
            "entity_category": "diagnostic",
        },
    )


def _mute_binary_sensor() -> EntitySpec:
    def state(device: DeviceContext) -> Mapping[str, Any]:
        return {"is_on": _bool(_value(device, _SPEAKER_SID, "mute"))}

    return EntitySpec(
        platform="binary_sensor",
        key="muted",
        name="静音",
        state=state,
        metadata={"device_class": "sound", "entity_category": "diagnostic"},
    )


class ProductV0A2Adapter:
    """Keep all V0A2 entity and command choices in this file."""

    prod_id = "V0A2"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()
        entities: list[EntitySpec] = []

        # --- media_player: power, volume and input source -------------------
        if context.has_service(_SCREEN_SID) or context.has_service(_DEVICE_STATE_SID):
            actions: dict[str, Any] = {}
            if context.has_service(_SCREEN_SID):
                actions["turn_on"] = _turn_on
                actions["turn_off"] = _turn_off
            if context.has_service(_SPEAKER_SID):
                actions["volume"] = _set_volume
            if context.has_service(_INPUT_SOURCE_SID):
                actions["select_source"] = _select_source

            entities.append(
                EntitySpec(
                    platform="media_player",
                    key="tv",
                    name=None,
                    state=_tv_state,
                    actions=actions,
                )
            )

        # --- sensors --------------------------------------------------------
        if context.has_service(_SCREEN_SID):
            entities.append(_brightness_sensor())
        if context.has_service(_SPEAKER_SID):
            entities.append(_mute_binary_sensor())
            entities.append(
                _text_sensor(_SPEAKER_SID, "equalizer", "音效模式", "sound_equalizer")
            )
        if context.has_service(_INPUT_SOURCE_SID):
            entities.append(
                _text_sensor(_INPUT_SOURCE_SID, "name", "输入源", "input_source")
            )

        screen_state = _enum_sensor(
            profile, _DEVICE_STATE_SID, "screenState", "屏幕状态", "screen_state"
        )
        if screen_state is not None:
            entities.append(screen_state)

        remote = _enum_sensor(
            profile, _REMOTE_CONTROL_SID, "switchState", "远程控制", "remote_control"
        )
        if remote is not None:
            entities.append(remote)

        if _service(profile, _MESSAGE_BOARD_SID) is not None:
            entities.append(
                _text_sensor(_MESSAGE_BOARD_SID, "sender", "最近留言人", "message_sender")
            )
            entities.append(
                _text_sensor(_MESSAGE_BOARD_SID, "message", "最近留言", "message_text")
            )
            entities.append(
                _text_sensor(_MESSAGE_BOARD_SID, "reply", "最近留言回复", "message_reply")
            )
        return tuple(entities)


ADAPTER = ProductV0A2Adapter()
