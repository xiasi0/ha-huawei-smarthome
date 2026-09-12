"""User-contributed protocol for Huawei product 2G4N.

Product: 海雀AI摄像头 云台超清版 2.5K (deviceModel ``HQ8C``, prodId ``2G4N``).
Profile: https://smarthome-drcn.dbankcdn.com/device/guide/2G4N/2G4N.json

Every entity and command below is derived only from the fields declared by
that public Profile.  Service IDs, enum values and value ranges are read
from the Profile at runtime so an unexpected product revision degrades to a
missing entity instead of a wrong state.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_PROD_ID = "2G4N"
_CAMERA_SID = "carmera"
_ALARM_SID = "alarmEvent"
_VOIP_SID = "voip"
_NET_INFO_SID = "netInfo"
_VISIT_POINT_SID = re.compile(r"visitPoint\d+\Z")

_TRIGGER_ON = 1
_TRIGGER_OFF = 0


def _field(
    profile: Mapping[str, Any],
    sid: str,
    name: str,
) -> Mapping[str, Any] | None:
    for service in profile.get("services", ()):
        if not isinstance(service, Mapping) or service.get("serviceId") != sid:
            continue
        for field in service.get("characteristics", ()):
            if isinstance(field, Mapping) and field.get("characteristicName") == name:
                return field
    return None


def _has_service(profile: Mapping[str, Any], sid: str) -> bool:
    return any(
        isinstance(service, Mapping) and service.get("serviceId") == sid
        for service in profile.get("services", ())
    )


def _profile_on_off_values(
    field: Mapping[str, Any],
) -> tuple[Any, Any]:
    """Resolve the on/off payload values from the Profile enum list."""
    on_value: Any = None
    off_value: Any = None
    for option in field.get("enumList", ()):
        if not isinstance(option, Mapping) or option.get("enumVal") is None:
            continue
        label_en = str(option.get("descEn") or "").casefold()
        label_ch = str(option.get("descCh") or "")
        value = option.get("enumVal")
        if on_value is None and ("on" in label_en or label_ch == "开"):
            on_value = value
        elif off_value is None and ("off" in label_en or label_ch == "关"):
            off_value = value
    if on_value is None and off_value is None:
        # Boolean characteristic without an enum list follows the 0/1
        # wire format shared by this product family.
        on_value, off_value = _TRIGGER_ON, _TRIGGER_OFF
    return on_value, off_value


def _coerce_payload_value(value: Any, field: Mapping[str, Any]) -> Any:
    """Encode a command value using the Profile-declared characteristic type."""

    data_type = str(field.get("characteristicType") or "").casefold()
    if data_type in {"bool", "int", "integer", "enum"}:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return value
        return int(number) if number.is_integer() else number
    return value


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.strip() in {"1", "true", "on", "开"}:
            return True
        if value.strip() in {"0", "false", "off", "关"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _switch_spec(
    profile: Mapping[str, Any],
    sid: str,
    field_name: str,
    name: str,
) -> EntitySpec | None:
    field = _field(profile, sid, field_name)
    if field is None or "W" not in str(field.get("method") or ""):
        return None
    on_value, off_value = _profile_on_off_values(field)

    def state(device: DeviceContext) -> Mapping[str, Any]:
        return {"is_on": _bool(device.value(sid, field_name))}

    async def turn_on(device: DeviceContext, _data: Mapping[str, Any]) -> None:
        await device.async_send_service(
            sid, {field_name: _coerce_payload_value(on_value, field)}
        )

    async def turn_off(device: DeviceContext, _data: Mapping[str, Any]) -> None:
        await device.async_send_service(
            sid, {field_name: _coerce_payload_value(off_value, field)}
        )

    key = sid if field_name == "on" else f"{sid}_{field_name}"
    return EntitySpec(
        platform="switch",
        key=key,
        name=name,
        state=state,
        actions={"turn_on": turn_on, "turn_off": turn_off},
    )


def _trigger_button_spec(
    profile: Mapping[str, Any],
    sid: str,
    field_name: str,
    name: str | None,
) -> EntitySpec | None:
    """One-shot button backed by a boolean trigger characteristic."""

    field = _field(profile, sid, field_name)
    if field is None or "W" not in str(field.get("method") or ""):
        return None
    on_value, _ = _profile_on_off_values(field)

    async def press(device: DeviceContext, _data: Mapping[str, Any]) -> None:
        await device.async_send_service(
            sid, {field_name: _coerce_payload_value(on_value, field)}
        )

    return EntitySpec(
        platform="button",
        key=f"{sid}_{field_name}",
        name=name,
        state=lambda device: {},
        actions={"press": press},
    )


def _visit_point_buttons(
    profile: Mapping[str, Any],
) -> list[EntitySpec]:
    """One button per configured visit point, labelled by its device name."""

    buttons: list[EntitySpec] = []
    for service in profile.get("services", ()):
        if not isinstance(service, Mapping):
            continue
        sid = service.get("serviceId")
        if not isinstance(sid, str) or _VISIT_POINT_SID.fullmatch(sid) is None:
            continue
        move_field = _field(profile, sid, "move")
        if move_field is None or "W" not in str(move_field.get("method") or ""):
            continue
        on_value, _ = _profile_on_off_values(move_field)

        async def press(
            device: DeviceContext,
            _data: Mapping[str, Any],
            _sid: str = sid,
            _field: Mapping[str, Any] = move_field,
            _on: Any = on_value,
        ) -> None:
            await device.async_send_service(
                _sid, {"move": _coerce_payload_value(_on, _field)}
            )

        buttons.append(
            EntitySpec(
                platform="button",
                key=f"{sid}_move",
                name=None,  # resolved per device below
                state=lambda device: {},
                actions={"press": press},
            )
        )
    return buttons


def _binary_sensor_spec(
    sid: str,
    field_name: str,
    name: str,
) -> EntitySpec:
    def state(device: DeviceContext) -> Mapping[str, Any]:
        return {"is_on": _bool(device.value(sid, field_name))}

    return EntitySpec(
        platform="binary_sensor",
        key=f"{sid}_{field_name}",
        name=name,
        state=state,
    )


def _profile_enum_label(
    field: Mapping[str, Any] | None,
    value: Any,
) -> str | None:
    """Resolve one reported value to its Profile enum label.

    ``alarmEvent`` fields are declared as ``0/1`` enums whose ``descCh``
    already carries the user-facing wording ("无人形检测告警" /
    "有人形检测告警"), so the label is read from the Profile rather than
    being hardcoded here.
    """

    if field is None:
        return None
    for option in field.get("enumList", ()):
        if not isinstance(option, Mapping):
            continue
        if str(option.get("enumVal")) != str(value):
            continue
        label = option.get("descCh") or option.get("descEn")
        if isinstance(label, str) and label.strip():
            return label.strip()
    return None


def _alarm_sensor_spec(
    profile: Mapping[str, Any],
    field_name: str,
    name: str,
) -> EntitySpec:
    """Expose one ``alarmEvent`` field as its Profile-labelled state.

    A sensor rather than a binary_sensor on purpose: the cloud pushes an
    alarm once and never reports the cleared value, so a binary_sensor would
    latch on after the first detection and never change state again, silently
    breaking automations built on it.  Reporting the Profile label keeps the
    entity truthful -- it shows the last reported alarm state instead of
    claiming a detection is happening right now.
    """

    field = _field(profile, _ALARM_SID, field_name)

    def state(device: DeviceContext) -> Mapping[str, Any]:
        value = device.value(_ALARM_SID, field_name)
        if value is None:
            return {"native_value": None}
        label = _profile_enum_label(field, value)
        if label is not None:
            return {"native_value": label}
        number = _number(value)
        return {"native_value": number if number is not None else value}

    return EntitySpec(
        platform="sensor",
        key=f"{_ALARM_SID}_{field_name}",
        name=name,
        state=state,
    )


# The alarm fields this adapter reports, mapped to the event type each one
# fires.  Home Assistant event types must be stable snake_case tokens.
_ALARM_EVENTS: tuple[tuple[str, str], ...] = (
    ("humanBodyAlarm", "human_body"),
    ("audioAlarm", "audio"),
    ("videoAlarm", "video"),
    ("babyCryAlarm", "baby_cry"),
)

# ``alarmId`` arrives as "<camera id>::<epoch ms>"; the epoch is what actually
# distinguishes one detection from the next, and the camera id is constant, so
# the timestamp half is the stable part of the identifier.
_ALARM_ID_SEPARATOR = "::"


def _alarm_event_decoder(
    device: DeviceContext,
    sid: str,
    data: Mapping[str, Any],
    timestamp: str | None,
) -> list[tuple[str, Mapping[str, Any]]]:
    """Turn one ``alarmEvent`` push into Home Assistant events.

    ``alarmEvent`` is a one-shot signal: the cloud pushes it when something is
    detected and never sends the cleared value.  The sensors declared beside
    this decoder therefore only describe *what was last reported* and cannot
    drive an automation that should run on every detection -- a later
    detection that sets the same field produces no state change at all.

    This decoder supplies the missing half: each accepted push is reported as
    an event, so an automation can trigger on every occurrence and read
    ``alarm_id`` to tell them apart.
    """

    if sid != _ALARM_SID:
        return []

    alarm_id = data.get("alarmId")
    alarm_ref = str(alarm_id) if alarm_id is not None else None
    detected_at = None
    if isinstance(alarm_id, str) and _ALARM_ID_SEPARATOR in alarm_id:
        detected_at = alarm_id.rsplit(_ALARM_ID_SEPARATOR, 1)[-1] or None

    events: list[tuple[str, Mapping[str, Any]]] = []
    for field_name, event_type in _ALARM_EVENTS:
        # Any field the Profile declares as ``0/1`` may arrive as a bool, an int
        # or a numeric string, so ``_bool`` is used rather than a truthiness
        # test that would treat the string "0" as raised.
        if _bool(data.get(field_name)) is not True:
            continue
        # A single push can carry several raised fields (a camera reports
        # audio and video together), so every raised one is reported; the
        # shared alarm id keeps them recognisable as one occurrence.
        events.append(
            (
                event_type,
                {
                    "alarm_id": alarm_ref,
                    "detected_at": detected_at,
                    "received_at": timestamp,
                    "camera": device.name,
                },
            )
        )
    return events


def _alarm_event_spec() -> EntitySpec:
    """One event entity that fires for every reported detection."""

    return EntitySpec(
        platform="event",
        key="alarm",
        name="告警事件",
        state=lambda device: {},
        metadata={"event_types": [event_type for _, event_type in _ALARM_EVENTS]},
        event_decoder=_alarm_event_decoder,
    )


def _online_spec() -> EntitySpec:
    """One connectivity sensor backed by the device's online flag."""

    def state(device: DeviceContext) -> Mapping[str, Any]:
        return {"is_on": bool(device.available)}

    return EntitySpec(
        platform="binary_sensor",
        key="online",
        name="在线状态",
        state=state,
        metadata={"device_class": "connectivity"},
    )


class Product2G4NAdapter:
    """Keep all 2G4N entity and command choices in this file."""

    prod_id = "2G4N"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()
        entities: list[EntitySpec] = []

        entities.append(_online_spec())

        if _has_service(profile, _CAMERA_SID):
            power = _switch_spec(profile, _CAMERA_SID, "on", "电源")
            if power is not None:
                entities.append(power)
            cruise = _switch_spec(profile, _CAMERA_SID, "cruise", "巡航")
            if cruise is not None:
                entities.append(cruise)
            shoot = _trigger_button_spec(
                profile, _CAMERA_SID, "shoot", "拍照"
            )
            if shoot is not None:
                entities.append(shoot)

        if _has_service(profile, _ALARM_SID):
            # The sensors describe the last reported alarm state -- they cannot
            # be binary_sensors (the cloud never sends the cleared value, so a
            # binary_sensor would latch on after the first detection and never
            # change again) and they cannot drive an automation that must run on
            # every detection, because a repeated detection changes nothing.
            entities.append(
                _alarm_sensor_spec(profile, "humanBodyAlarm", "人形检测")
            )
            entities.append(
                _alarm_sensor_spec(profile, "audioAlarm", "异常声音")
            )
            entities.append(
                _alarm_sensor_spec(profile, "videoAlarm", "视频告警")
            )
            entities.append(
                _alarm_sensor_spec(profile, "babyCryAlarm", "婴儿哭声")
            )
            # The event entity supplies that missing half: it fires on every
            # accepted alarmEvent push, so automations trigger per detection.
            entities.append(_alarm_event_spec())
        if _has_service(profile, _VOIP_SID):
            entities.append(_binary_sensor_spec(_VOIP_SID, "calling", "呼叫中"))
            # voip.voipCall (RW) triggers a video call to the phone app; the
            # camera ACKs the command but never pushes a voip state change,
            # so the call state cannot be verified over MQTT.  Exposed as
            # fire-and-forget buttons after real-device confirmation that the
            # call reaches the bound phone.
            trigger = _field(profile, _VOIP_SID, "voipCall")
            if trigger is not None and "W" in str(trigger.get("method") or ""):
                call_value, hangup_value = _profile_on_off_values(trigger)

                async def press_call(
                    device: DeviceContext,
                    _data: Mapping[str, Any],
                    _value: Any = call_value,
                    _field: Mapping[str, Any] = trigger,
                ) -> None:
                    await device.async_send_service(
                        _VOIP_SID,
                        {"voipCall": _coerce_payload_value(_value, _field)},
                    )

                async def press_hangup(
                    device: DeviceContext,
                    _data: Mapping[str, Any],
                    _value: Any = hangup_value,
                    _field: Mapping[str, Any] = trigger,
                ) -> None:
                    await device.async_send_service(
                        _VOIP_SID,
                        {"voipCall": _coerce_payload_value(_value, _field)},
                    )

                entities.extend(
                    (
                        EntitySpec(
                            platform="button",
                            key=f"{_VOIP_SID}_call",
                            name="呼叫",
                            state=lambda device: {},
                            actions={"press": press_call},
                        ),
                        EntitySpec(
                            platform="button",
                            key=f"{_VOIP_SID}_hangup",
                            name="挂断",
                            state=lambda device: {},
                            actions={"press": press_hangup},
                        ),
                    )
                )

        entities.extend(_visit_point_buttons(profile))

        # Resolve per-device visit point labels; points that the device
        # reports as not configured (enable=0) are skipped entirely, which
        # matches the vendor app hiding unconfigured presets.
        resolved: list[EntitySpec] = []
        for spec in entities:
            if spec.key.endswith("_move") and spec.name is None:
                sid = spec.key[: -len("_move")]
                if _bool(context.value(sid, "enable")) is not True:
                    continue
                label = context.value(sid, "name")
                resolved.append(
                    EntitySpec(
                        platform=spec.platform,
                        key=spec.key,
                        name=label.strip()
                        if isinstance(label, str) and label.strip()
                        else sid,
                        state=spec.state,
                        metadata=spec.metadata,
                        actions=spec.actions,
                    )
                )
            else:
                resolved.append(spec)
        return tuple(resolved)


ADAPTER = Product2G4NAdapter()
