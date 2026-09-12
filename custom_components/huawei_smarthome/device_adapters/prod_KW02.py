"""User-contributed protocol for Huawei product KW02.

Product: HUAWEI SmartLock Pro (deviceModel ``AGS-X10``, prodId ``KW02``).
Profile: https://smarthome-drcn.dbankcdn.com/device/guide/KW02/KW02.json

Every entity and command below is derived only from the fields declared by
that public Profile.  Service IDs, enum values and value ranges are read
from the Profile at runtime so an unexpected product revision degrades to a
missing entity instead of a wrong state.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_LOGGER = logging.getLogger(__name__)

_LOCK_STATUS_SID = "lockStatus"
_LOCK_STATUS_FIELD = "status"

# The Profile declares doorBattery.level and catEyeBattery.level, but the lock
# never pushes either service.  Both batteries arrive together through the
# batteryManager service that the device does report:
#   lithiumBatteryLevel     -> 锂电池电量 (60% on this lock, the lock body)
#   accumulatorBatteryLevel -> 干电池电量 (85% on this lock, the cat eye)
# The readings were confirmed against the lock itself and they line up with the
# field names: the rechargeable lithium pack is the one at 60%, the dry cells
# are the ones at 85%.
_BATTERY_SID = "batteryManager"
_LITHIUM_BATTERY_FIELD = "lithiumBatteryLevel"
_DRY_BATTERY_FIELD = "accumulatorBatteryLevel"

_LOCK_ALARM_SID = "lockAlarm"
_LOCK_ALARM_FIELD = "alarm"

_NET_INFO_SID = "netInfo"
_NET_INFO_FIELD = "intensity"

# The Profile names these concepts event.userOperation and event.doorAlarmState,
# but the lock pushes them on the wire under the short names below, split over
# two service ids:
#
#   sid="eventData"  {"data": "{\"uic\":5,\"type\":0,\"rt\":0,\"up\":2,...}"}
#        sent for every event; ``data`` is a JSON string and its ``up`` carries
#        the Profile userOperation code.
#   sid="event"      {"eid":"...","un":"<userName>","cl":"18:22","up":201,...}
#        sent only for credential unlocks, because it is the copy that carries
#        the user name.  Its ``up`` lives in a different code space (201 for a
#        credential unlock, never a Profile value), so it is merged first and
#        contributes ``un``/``cl`` only.
#
# eventData is therefore the source of truth for userOperation and
# doorAlarmState, and it is the only sid that reports interior unlocks.
_EVENT_SID = "event"
_EVENT_DATA_SID = "eventData"
_EVENT_DATA_PAYLOAD_FIELD = "data"
_USER_OPERATION_FIELD = "up"
_DOOR_ALARM_FIELD = "das"

# Profile characteristic names, used only to resolve enum labels.
_USER_OPERATION_PROFILE_FIELD = "userOperation"
_DOOR_ALARM_PROFILE_FIELD = "doorAlarmState"

# lockStatus/status values declared by the KW02 Profile.
_STATUS_DOOR_AJAR_LOCKED = 1  # 门未关异常上锁
_STATUS_UNLOCKED = 2  # 已开锁
_STATUS_LOCKED = 3  # 已上锁
_STATUS_DOOR_CLOSED = 4  # 已关门
_STATUS_DEADBOLTED = 6  # 已反锁

_LOCKED_STATUSES = frozenset(
    {_STATUS_DOOR_AJAR_LOCKED, _STATUS_LOCKED, _STATUS_DEADBOLTED}
)
_UNLOCKED_STATUSES = frozenset({_STATUS_UNLOCKED, _STATUS_DOOR_CLOSED})

# The door leaf itself is unambiguous on these states only: 门未关异常上锁 and
# 已开锁 both mean the lock is not holding a shut door, while 已上锁 / 已关门 /
# 已反锁 can only happen on a closed leaf.
_DOOR_OPEN_STATUSES = frozenset({_STATUS_DOOR_AJAR_LOCKED, _STATUS_UNLOCKED})
_DOOR_CLOSED_STATUSES = frozenset(
    {_STATUS_LOCKED, _STATUS_DOOR_CLOSED, _STATUS_DEADBOLTED}
)

# Every lockStatus value the Profile declares.  AGS-X10 firmware also reports 7,
# which the Profile does not describe and the vendor App has no label for:
# observed only for the 2-7 s between 已上锁 and 已开锁 when the door is opened
# with the interior knob or a key (the interior handle, 室内一握开锁, goes straight to
# 已开锁), with doorEvent arriving at the very same instant.  Publishing it would
# spell a bare "7" in 门锁状态 and, since it describes neither an open nor a shut
# leaf, would also flip 门 and 门锁 to unknown for those seconds.  Undescribed
# values are therefore held back and the last declared state stays on screen,
# which is what the vendor App shows too.
_DECLARED_STATUSES = _LOCKED_STATUSES | _UNLOCKED_STATUSES

# lockAlarm/alarm values declared by the KW02 Profile.
_ALARM_LOW_BATTERY = 2  # 低电量告警

# The lock registers the lockAlarm service but never publishes a value for it:
# every snapshot carries an empty body.  The dry-cell warning is reported on
# batteryManager.lpmStatus instead, and doorAlarmState travels with the event
# record, so those two are the real sources for the alarm entities.
_BATTERY_LPM_FIELD = "lpmStatus"
_LPM_ACTIVE = 1

# The lock reports -1 for doorAlarmState while nothing is wrong.  That is a
# real "no alarm" reading, so it is surfaced as such instead of being dropped
# as an unknown state, which is indistinguishable from missing data in the UI.
_NO_ALARM = "无告警"

# doorBattery/level and catEyeBattery/level declare min = -1, which is not a
# real percentage and is therefore projected as an unknown state.
_BATTERY_UNKNOWN = -1

# event.userOperation values that describe a deliberate unlock.
# The Profile declares 24 = 门内开锁, but AGS-X10 firmware never sends 24: the
# interior handle arrives as 35 and the interior knob as 37.  Verified from the
# wire -- both arrive with lockStatus.status = 2 (已开锁), carry no userName and
# no credential (uic = 0), and follow 25 (反锁) / 26 (解除反锁) when the door was
# deadbolted from inside.  24 is kept as well in case a revision does send it.
# 0-7 = 指纹 / 密码 / 人脸 / 门卡 / 手表手环 / 华为钱包 / 临时密码 / 物理钥匙,
#       all triggered from the outdoor panel -> outdoor.
# Every other value (credential management, deadbolt, arming, doorbell, ...) is
# not an unlock and is projected as unknown; 38 is the auto re-lock that follows
# every unlock after 8-30 s, so it must stay out of the unlock set.
_OPERATION_INDOOR_HANDLE = 35  # 室内一握开锁
_OPERATION_INDOOR_KNOB = 37  # 旋钮或钥匙开锁
_OPERATION_RELOCK = 38  # 上锁

# The Profile's userOperation enum stops at 33, so the interior codes above have
# no Profile label to resolve and would otherwise surface as bare numbers.  The
# labels below are the ones the vendor App (华为智慧生活) shows for the very same
# event, so both UIs name one operation the same way.
_FIRMWARE_OPERATION_LABELS = {
    _OPERATION_INDOOR_HANDLE: "室内一握开锁",
    _OPERATION_INDOOR_KNOB: "旋钮或钥匙开锁",
    _OPERATION_RELOCK: "上锁",
}

_INDOOR_UNLOCK_OPERATIONS = frozenset(
    {24, _OPERATION_INDOOR_HANDLE, _OPERATION_INDOOR_KNOB}
)
_OUTDOOR_UNLOCK_OPERATIONS = frozenset(range(8))


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


def _operation_label(field: Mapping[str, Any], value: Any) -> str | None:
    """Return the label for one userOperation value.

    The Profile only describes the outdoor codes (0-33), so the interior codes
    this firmware reports outside that range fall back to the labels read off
    the wire.
    """

    label = _enum_label(field, value)
    if label is not None:
        return label
    number = _number(value)
    if number is None:
        return None
    return _FIRMWARE_OPERATION_LABELS.get(number)


# The Profile declares lockStatus/status as method=RW, so this adapter is
# entitled to register lock and unlock actions -- and a first version did.
# AGS-X10 firmware accepts that write and then ignores it: the lock itself acks
# the command with errcode=0 and immediately re-reports its unchanged status,
# so the door never moves.  The vendor App (华为智慧生活) exposes no remote unlock
# for this product either, and the securitySetting.enableRemoteUnlock = 1 it
# reports is a static capability flag rather than a usable feature.  A control
# that reports success without acting is worse than a missing one, so the
# Profile's write permission is deliberately not turned into an action and the
# lock entity stays a pure state reader.
def _status_reader() -> Callable[[DeviceContext], Any]:
    """Return a reader that keeps the last declared lockStatus value.

    lockStatus/status is the service every entity of this product reads, and the
    firmware sometimes reports a value the Profile does not declare.  Returning
    the last declared one keeps 门锁 / 门锁状态 / 门 describing the same state
    instead of letting a transitional code blank all three out.
    """

    cache: dict[str, Any] = {"status": None}

    def read(device: DeviceContext) -> Any:
        status = _number(device.value(_LOCK_STATUS_SID, _LOCK_STATUS_FIELD))
        if status in _DECLARED_STATUSES:
            cache["status"] = status
        return cache["status"]

    return read


def _lock_spec(read_status: Callable[[DeviceContext], Any]) -> EntitySpec:
    def lock_state(device: DeviceContext) -> Mapping[str, Any]:
        status = read_status(device)
        if status in _LOCKED_STATUSES:
            return {"is_locked": True}
        if status in _UNLOCKED_STATUSES:
            return {"is_locked": False}
        return {"is_locked": None}

    return EntitySpec(
        platform="lock",
        key="lock",
        name="门锁",
        state=lock_state,
    )


def _lock_status_spec(
    profile: Mapping[str, Any],
    read_status: Callable[[DeviceContext], Any],
) -> EntitySpec:
    field = _field(profile, _LOCK_STATUS_SID, _LOCK_STATUS_FIELD) or {}

    def state(device: DeviceContext) -> Mapping[str, Any]:
        value = read_status(device)
        if value is None:
            return {"native_value": None}
        return {"native_value": _enum_label(field, value) or str(value)}

    return EntitySpec(
        platform="sensor",
        key="lock_status",
        name="门锁状态",
        state=state,
    )


def _battery_spec(field: str, key: str, name: str) -> EntitySpec:
    def state(device: DeviceContext) -> Mapping[str, Any]:
        value = _number(device.value(_BATTERY_SID, field))
        if value is None or value <= _BATTERY_UNKNOWN:
            return {"native_value": None}
        return {"native_value": value}

    return EntitySpec(
        platform="sensor",
        key=key,
        name=name,
        state=state,
        metadata={
            "device_class": "battery",
            "unit": "%",
            "state_class": "measurement",
        },
    )


def _alarm_spec(profile: Mapping[str, Any]) -> EntitySpec:
    lock_field = _field(profile, _LOCK_ALARM_SID, _LOCK_ALARM_FIELD) or {}
    door_field = _field(profile, _EVENT_SID, _DOOR_ALARM_PROFILE_FIELD) or {}

    def state(device: DeviceContext) -> Mapping[str, Any]:
        value = _number(device.value(_LOCK_ALARM_SID, _LOCK_ALARM_FIELD))
        if value is not None and value >= 1:
            return {"native_value": _enum_label(lock_field, value) or str(value)}
        alarm = _number(_event_record(device).get(_DOOR_ALARM_FIELD))
        if alarm is not None and alarm >= 1:
            return {"native_value": _enum_label(door_field, alarm) or str(alarm)}
        if value is None and alarm is None:
            return {"native_value": None}
        return {"native_value": _NO_ALARM}

    return EntitySpec(
        platform="sensor",
        key="alarm",
        name="门锁告警",
        state=state,
    )


def _low_battery_spec() -> EntitySpec:
    def state(device: DeviceContext) -> Mapping[str, Any]:
        alarm = _number(device.value(_LOCK_ALARM_SID, _LOCK_ALARM_FIELD))
        if alarm is not None and alarm >= 1:
            return {"is_on": alarm == _ALARM_LOW_BATTERY}
        level = _number(device.value(_BATTERY_SID, _BATTERY_LPM_FIELD))
        if level is None:
            return {"is_on": False}
        return {"is_on": level == _LPM_ACTIVE}

    return EntitySpec(
        platform="binary_sensor",
        key="low_battery",
        name="低电量告警",
        state=state,
        metadata={"device_class": "battery"},
    )


def _door_spec(read_status: Callable[[DeviceContext], Any]) -> EntitySpec:
    """Expose the door leaf only for Profile states with an unambiguous meaning."""

    def state(device: DeviceContext) -> Mapping[str, Any]:
        status = read_status(device)
        if status in _DOOR_OPEN_STATUSES:
            return {"is_on": True}
        if status in _DOOR_CLOSED_STATUSES:
            return {"is_on": False}
        return {"is_on": None}

    return EntitySpec(
        platform="binary_sensor",
        key="door",
        name="门",
        state=state,
        metadata={"device_class": "door"},
    )


def _wifi_signal_spec() -> EntitySpec:
    def state(device: DeviceContext) -> Mapping[str, Any]:
        value = _number(device.value(_NET_INFO_SID, _NET_INFO_FIELD))
        return {"native_value": value}

    return EntitySpec(
        platform="sensor",
        key="wifi_signal",
        name="Wi-Fi 信号强度",
        state=state,
        metadata={"unit": "%", "state_class": "measurement"},
    )


def _unlock_direction(value: Any) -> str | None:
    """Classify one event.userOperation value as an indoor or outdoor unlock."""

    operation = _number(value)
    if operation is None:
        return None
    if operation in _INDOOR_UNLOCK_OPERATIONS:
        return "室内开门"
    if operation in _OUTDOOR_UNLOCK_OPERATIONS:
        return "室外开门"
    return None


def _event_record(device: DeviceContext) -> Mapping[str, Any]:
    """Return the flat event record, unpacking eventData's nested JSON.

    ``event`` publishes the user-facing fields (``un`` = userName, ``cl`` =
    clock) while ``eventData`` carries the Profile userOperation and
    doorAlarmState codes, so eventData's fields win when both describe the same
    event.  Its copy is normally a JSON string inside ``data``, but a revision
    may deliver it already parsed, so both shapes are accepted.
    """

    record: dict[str, Any] = dict(device.service_state(_EVENT_SID))
    raw = device.value(_EVENT_DATA_SID, _EVENT_DATA_PAYLOAD_FIELD)
    if isinstance(raw, Mapping):
        parsed: Any = raw
    elif isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = None
    else:
        parsed = None
    if isinstance(parsed, Mapping):
        record.update(parsed)
    _LOGGER.debug(
        "KW02 event record: event=%s eventData=%s merged=%s",
        device.service_state(_EVENT_SID),
        raw,
        record,
    )
    return record


def _event_kind(record: Mapping[str, Any]) -> str | None:
    """Classify one lock event record as unlock / lock / alarm / motion.

    The classification mirrors the adapter's own state entities so an event and
    its matching sensor can never disagree about what happened.

    Two wire quirks drive the order of the checks:

    * ``event`` is emitted only for credential unlocks and its ``up`` lives in a
      different code space (201 for a credential unlock, never a Profile value),
      so an ``up`` the Profile cannot place is not "no event" when the record
      carries a user name -- it is an unlock.  ``eventData`` remains the
      authority for operations it does describe.
    * the observed ``event`` payload for a loitering detection also carried
      ``up: 201`` while its ``aid`` embedded ``MOTION_DETECTION``, so the aid
      token is checked first and otherwise such a record would be reported as an
      unlock.
    """

    identifier = record.get("aid")
    if isinstance(identifier, str) and "MOTION_DETECTION" in identifier.upper():
        return "motion"
    alarm = _number(record.get(_DOOR_ALARM_FIELD))
    if alarm is not None and alarm >= 1:
        return "alarm"
    operation = _number(record.get(_USER_OPERATION_FIELD))
    if operation == _OPERATION_RELOCK:
        return "lock"
    if _unlock_direction(operation) is not None:
        return "unlock"
    # An operation the Profile does not describe, together with a user name,
    # is the credential-unlock copy of the event.
    user = record.get("un")
    if isinstance(user, str) and user.strip():
        return "unlock"
    return None


def _event_identifier(record: Mapping[str, Any]) -> str | None:
    """Return the identifier the lock assigns to one occurrence.

    ``event``/``eventData`` carry ``eid``, which increments per event, so it is
    what actually distinguishes two consecutive unlocks.  The nested
    ``aid``/``id`` fields are a fallback for revisions that omit ``eid``.
    """

    for key in ("eid", "aid", "id"):
        value = record.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _lock_event_decoder(
    device: DeviceContext,
    sid: str,
    data: Mapping[str, Any],
    timestamp: str | None,
) -> list[tuple[str, Mapping[str, Any]]]:
    """Turn one lock event push into a Home Assistant event.

    The lock pushes every operation once and never sends the cleared value, so
    the state entities (最近开门方式 / 开门方向 / 最近告警) only describe *what
    happened last*.  Two consecutive unlocks by the same person through the same
    method produce no state change at all, which means an automation built on
    those entities runs once and then stops.

    This decoder supplies the missing half: each accepted push fires an event.

    ``event`` carries the user-facing fields (``un`` = user name, ``cl`` =
    clock) while ``eventData`` carries the operation and alarm codes, so the two
    are merged exactly the way ``_event_record`` does for the state readers.
    """

    if sid not in (_EVENT_SID, _EVENT_DATA_SID):
        return []

    # Decode THIS push, not the standing record.  ``_event_record`` merges both
    # services because the state readers want the latest known picture, but an
    # event must not inherit the previous occurrence: the lock reports a
    # "door closed" record on ``eventData`` right after an unlock, so merging the
    # cached half would relabel that unlock as a lock and reuse its id.
    #
    # The other service is therefore consulted only for fields this push does
    # not carry: ``un``/``cl`` arrive on ``event`` while ``up``/``das`` arrive on
    # ``eventData``, and a push may legitimately carry only one half.
    def _parsed_payload(value: Any) -> Mapping[str, Any]:
        if isinstance(value, Mapping):
            return value
        if isinstance(value, str) and value:
            try:
                parsed = json.loads(value)
            except ValueError:
                return {}
            if isinstance(parsed, Mapping):
                return parsed
        return {}

    current: dict[str, Any] = dict(data)
    if sid == _EVENT_DATA_SID:
        current.pop(_EVENT_DATA_PAYLOAD_FIELD, None)
        current.update(_parsed_payload(data.get(_EVENT_DATA_PAYLOAD_FIELD)))
    elif sid == _EVENT_SID:
        current.update(device.service_state(_EVENT_DATA_SID))
        current.pop(_EVENT_DATA_PAYLOAD_FIELD, None)
        other = _parsed_payload(
            device.value(_EVENT_DATA_SID, _EVENT_DATA_PAYLOAD_FIELD)
        )
        # Only fill in what this push lacks, and never take the *identity* of an
        # event from the other service.
        for key, value in other.items():
            if key in ("eid", "aid", "id", "et"):
                continue
            current.setdefault(key, value)

    merged = current

    kind = _event_kind(merged)
    if kind is None:
        # Credential management, arming, doorbell and similar records are not
        # user-visible door events, so they deliberately produce nothing.
        return []

    operation = _number(merged.get(_USER_OPERATION_FIELD))
    profile_field = _field(
        device.profile or {}, _EVENT_SID, _USER_OPERATION_PROFILE_FIELD
    ) or {}
    alarm_field = _field(
        device.profile or {}, _EVENT_SID, _DOOR_ALARM_PROFILE_FIELD
    ) or {}

    payload: dict[str, Any] = {
        "event_id": _event_identifier(merged),
        "user": merged.get("un"),
        "clock": merged.get("cl"),
        "occurred_at": merged.get("et") or timestamp,
        "method": _operation_label(profile_field, operation),
        "direction": _unlock_direction(operation),
    }
    alarm_code = _number(merged.get(_DOOR_ALARM_FIELD))
    if kind == "alarm":
        payload["alarm"] = _enum_label(alarm_field, alarm_code)
    return [(kind, {k: v for k, v in payload.items() if v is not None})]


def _lock_event_spec() -> EntitySpec:
    """One event entity that fires for every unlock, lock and door alarm."""

    return EntitySpec(
        platform="event",
        key="lock_event",
        name="门锁事件",
        state=lambda device: {},
        metadata={
            "event_types": ["unlock", "lock", "alarm", "motion"],
            "icon": "mdi:door-open",
        },
        event_decoder=_lock_event_decoder,
    )


def _unlock_reader() -> Callable[[DeviceContext], Any]:
    """Return a reader that keeps the latest unlock seen by one entity.

    The lock reports every event on ``eventData``, so reading the field directly
    would let a following record such as "door closed" overwrite the unlock
    code.  The most recent value the Profile recognises as an unlock is cached
    instead, and later non-unlock records leave it untouched.
    """

    cache: dict[str, Any] = {"operation": None}

    def read(device: DeviceContext) -> Any:
        operation = _number(_event_record(device).get(_USER_OPERATION_FIELD))
        if _unlock_direction(operation) is not None:
            cache["operation"] = operation
        return cache["operation"]

    return read


def _open_direction_spec(read_unlock: Callable[[DeviceContext], Any]) -> EntitySpec:
    """Expose whether the latest unlock came from the indoor or outdoor side."""

    def state(device: DeviceContext) -> Mapping[str, Any]:
        return {"native_value": _unlock_direction(read_unlock(device))}

    return EntitySpec(
        platform="sensor",
        key="open_direction",
        name="开门方向",
        state=state,
    )


def _last_open_method_spec(
    profile: Mapping[str, Any],
    read_unlock: Callable[[DeviceContext], Any],
) -> EntitySpec:
    """Expose the Profile label of the latest unlock operation."""

    field = _field(profile, _EVENT_SID, _USER_OPERATION_PROFILE_FIELD) or {}

    def state(device: DeviceContext) -> Mapping[str, Any]:
        value = _number(read_unlock(device))
        if value is None:
            return {"native_value": None}
        return {"native_value": _operation_label(field, value) or str(value)}

    return EntitySpec(
        platform="sensor",
        key="last_open_method",
        name="最近开门方式",
        state=state,
    )


def _door_alarm_spec(profile: Mapping[str, Any]) -> EntitySpec:
    """Expose the doorAlarmState of the latest event while it is still an alarm."""

    field = _field(profile, _EVENT_SID, _DOOR_ALARM_PROFILE_FIELD) or {}

    def state(device: DeviceContext) -> Mapping[str, Any]:
        # The Profile enum starts at 1; the lock reports -1 while nothing is
        # wrong, which is surfaced as an explicit "no alarm" reading.
        value = _number(_event_record(device).get(_DOOR_ALARM_FIELD))
        if value is None:
            return {"native_value": None}
        if value < 1:
            return {"native_value": _NO_ALARM}
        return {"native_value": _enum_label(field, value) or str(value)}

    return EntitySpec(
        platform="sensor",
        key="door_alarm",
        name="最近告警",
        state=state,
    )


class ProductKW02Adapter:
    """HUAWEI SmartLock Pro (AGS-X10) entity and command choices."""

    prod_id = "KW02"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None or not context.has_service(_LOCK_STATUS_SID):
            return ()

        read_status = _status_reader()
        entities: list[EntitySpec] = [
            _lock_spec(read_status),
            _lock_status_spec(profile, read_status),
            _door_spec(read_status),
        ]
        if context.has_service(_BATTERY_SID):
            entities.append(
                _battery_spec(_LITHIUM_BATTERY_FIELD, "lithium_battery", "锂电池电量")
            )
            entities.append(
                _battery_spec(_DRY_BATTERY_FIELD, "dry_battery", "干电池电量")
            )
        if context.has_service(_LOCK_ALARM_SID):
            entities.append(_alarm_spec(profile))
            entities.append(_low_battery_spec())
        if context.has_service(_NET_INFO_SID):
            entities.append(_wifi_signal_spec())
        if context.has_service(_EVENT_SID) or context.has_service(_EVENT_DATA_SID):
            read_unlock = _unlock_reader()
            entities.append(_open_direction_spec(read_unlock))
            entities.append(_last_open_method_spec(profile, read_unlock))
            entities.append(_door_alarm_spec(profile))
            # The state entities above describe the latest operation; this event
            # entity fires on every operation, so an automation runs on each
            # unlock instead of only on the first one.
            entities.append(_lock_event_spec())
        entities.extend(_firmware_specs(context))
        entities.extend(_roster_specs(context))
        entities.extend(_reader_based_specs(context))
        return tuple(entities)


# ---------------------------------------------------------------------------
# Read-only reporting entities.
#
# AGS-X10 firmware reports far more than the public Profile declares: the lock
# pushes 42 services while the Profile documents 21.  The entities below are
# read-only projections of services the lock was observed to report on a real
# device; nothing here writes to the lock and no command is offered, so no
# unverified write can reach the hardware.
#
# Wire details confirmed against the lock (deviating from the Profile):
#   update           currentVersion is a firmware string ("AGS-X10 5.0.0.1(SP65C00)").
#                    The Profile's update.action is deliberately not exposed.
#   users            userList carries every enrolled member (un = name).
#   keyOperate       keyName names the credential used last ("人脸 01").
#   doorEvent        the per-event feed; its userName is the same person the
#                    event/eventData pair reports.
#   lastActionTime   time is the last time the lock was operated.
# ---------------------------------------------------------------------------

_UPDATE_SID = "update"
_USERS_SID = "users"
_FACES_SID = "faces"
_FINGERS_SID = "fingers"
_KEY_OPERATE_SID = "keyOperate"
_DOOR_EVENT_SID = "doorEvent"
_LAST_ACTION_SID = "lastActionTime"


def _firmware_specs(context: DeviceContext) -> list[EntitySpec]:
    """Firmware version of the lock body.

    Read-only on purpose: the Profile's ``update.action`` would let HA start an
    OTA, which has not been validated on this hardware, so only the reported
    version is projected.
    """

    if not context.has_service(_UPDATE_SID):
        return []

    def version(device: DeviceContext) -> Mapping[str, Any]:
        value = device.value(_UPDATE_SID, "currentVersion")
        return {"native_value": value if isinstance(value, str) and value else None}

    return [
        EntitySpec(
            platform="sensor",
            key="firmware_version",
            name="固件版本",
            state=version,
            metadata={"entity_category": "diagnostic"},
        )
    ]


def _roster_specs(context: DeviceContext) -> list[EntitySpec]:
    """Enrolled-credential counts, e.g. how many faces or fingerprints exist."""

    specs: list[EntitySpec] = []

    def make_count(sid: str, field: str, key: str, name: str) -> EntitySpec:
        def state(device: DeviceContext) -> Mapping[str, Any]:
            raw = device.value(sid, field)
            if not isinstance(raw, list):
                return {"native_value": None}
            return {"native_value": len(raw)}

        return EntitySpec(
            platform="sensor",
            key=key,
            name=name,
            state=state,
            metadata={"state_class": "measurement", "entity_category": "diagnostic"},
        )

    if context.has_service(_USERS_SID):
        def users(device: DeviceContext) -> Mapping[str, Any]:
            raw = device.value(_USERS_SID, "userList")
            if not isinstance(raw, list):
                return {"native_value": None}
            names = [
                str(item.get("un"))
                for item in raw
                if isinstance(item, Mapping) and item.get("un")
            ]
            return {
                "native_value": len(names),
                "members": ",".join(names),
            }

        specs.append(
            EntitySpec(
                platform="sensor",
                key="user_count",
                name="用户数",
                state=users,
                metadata={"state_class": "measurement"},
            )
        )
    if context.has_service(_FACES_SID):
        specs.append(make_count(_FACES_SID, "face", "face_count", "人脸数"))
    if context.has_service(_FINGERS_SID):
        specs.append(make_count(_FINGERS_SID, "finger", "finger_count", "指纹数"))
    return specs


def _reader_based_specs(context: DeviceContext) -> list[EntitySpec]:
    """Last-operated metadata reported as plain text.

    These services are event-driven: the lock pushes keyOperate, doorEvent and
    lastActionTime only when something happens, so none of them appears in the
    discovery snapshot and ``has_service`` is false for them at setup time.
    They are therefore always registered and simply report unknown until the
    first event arrives.
    """

    def key_name(device: DeviceContext) -> Mapping[str, Any]:
        value = device.value(_KEY_OPERATE_SID, "keyName")
        return {"native_value": value if isinstance(value, str) and value else None}

    def door_user(device: DeviceContext) -> Mapping[str, Any]:
        value = device.value(_DOOR_EVENT_SID, "userName")
        return {"native_value": value if isinstance(value, str) and value else None}

    def last_action(device: DeviceContext) -> Mapping[str, Any]:
        value = device.value(_LAST_ACTION_SID, "time")
        return {"native_value": value if isinstance(value, str) and value else None}

    return [
        EntitySpec(
            platform="sensor",
            key="last_key",
            name="最近使用钥匙",
            state=key_name,
        ),
        EntitySpec(
            platform="sensor",
            key="door_event_user",
            name="最近门事件人员",
            state=door_user,
        ),
        EntitySpec(
            platform="sensor",
            key="last_action_time",
            name="最近操作时间",
            state=last_action,
            # The lock reports SmartHome stamps ("20260912T094645Z"), not ISO
            # 8601, so device_class=timestamp is deliberately omitted: HA would
            # reject the value and the entity would show unknown.
            metadata={"entity_category": "diagnostic"},
        ),
    ]


ADAPTER = ProductKW02Adapter()
