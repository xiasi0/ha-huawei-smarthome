"""User-contributed protocol for Huawei product KW59 (华为智能门锁E211).

Product: 华为智能门锁E211 (deviceModel ``AGS-E211``, prodId ``KW59``,
deviceTypeId ``A0B``, manufacturer 华为).
Profile: https://smarthome-drcn.dbankcdn.com/device/guide/KW59/KW59.json

Family member of the SmartLock series already covered by this repository
(KW02 / AGS-X10, KW5L, and the KW38/KW4X set from PR #82).  The Profile
declares the same 20 services; ``lockStatus`` and ``event`` carry identical
enum spaces.  All entity logic mirrors the KW02 adapter.

Verification status -- every read below was checked against a live wire
snapshot of a real AGS-E211 (services the lock actually reported):

    lockStatus.status   4 -> 已关门 (updateTime travels alongside)
    batteryManager      lithiumBatteryLevel=22, accumulatorBatteryLevel=92,
                        lpmStatus=0 -- pushed although the Profile does not
                        declare the service at all
    doorBattery/catEyeBattery / lockAlarm / faces(空)
                        declared by the Profile, never pushed (the KW02
                        pitfall, confirmed on this model too)
    netInfo             intensity=100, RSSI=-41
    update              currentVersion "AGS-E211 5.0.0.1(SP43C00)"
    event               {"eid":"2991","das":-1,"up":200,"aid":
                        "...MOTION_DETECTION_...","uic":0} -- 猫眼移动侦测;
                        the aid token identifies it (up=200 is outside the
                        Profile enum, like KW02's loitering 201)
    eventData           {"uic":0,"up":43,"eid":"3013","das":-1} -- 43 is
                        outside the Profile enum (0-33); it arrived one
                        second before lockStatus -> 已关门 with no alarm and
                        no credential, so it reads as a door-close-class
                        operation.  It is deliberately NOT labelled and NOT
                        classified as an unlock; if the vendor App ever shows
                        a name for 43 it can be added as a verified label.
    doorEvent           {"eventType":1,"id":1,"event":7,"userName":"Chris"}
                        -- the event code space is undocumented, so only
                        userName is read.
    lastActionTime      time "20260915T232350Z" (SmartHome stamp)
    users/fingers/ciphers/watchs/walletKeys
                        roster lists pushed on the wire (keyCards/faces
                        declared but empty so far)

Door-leaf ordering (2026-10, real-door automation requirement): the lock
delivers lockStatus and the event services as separate pushes, and the
status copy can win the race, so an automation triggering on 门-已打开 used
to read a stale 开门方向 / 最近开门方式.  The 门 entity therefore holds a
leaf transition back until the event feed has delivered the record that
explains the new status -- the unlock itself for an opening, any event-feed
record (event/eventData/doorEvent/lastActionTime) for a closing -- and
publishes it in the same update cycle in which 开门方向 / 最近开门方式 are
written.  Home Assistant runs trigger callbacks only after that cycle, so
they always read fresh values, in both wire orders.  A transition whose
event push never arrives stays held until the next operation pushes new
event data; a snapshot resync that already carries the matching event data
publishes immediately.

Unverified on this model (family-informed, kept from KW02/KW38):

    * unlock operation codes.  0-7 and 24 (门内开锁) come from this product's
      Profile; 35 (室内一握开锁) / 37 (旋钮或钥匙开锁) are codes the KW02
      firmware was observed to use for interior unlocks.  CONFIRMED on the
      AGS-E211 (2026-09-17, real-door test, full automation chain verified):
      an interior knob unlock reported the KW02 code 37 and an outdoor
      fingerprint unlock reported the Profile code 0 -- 开门方向 / 最近开门
      方式 / 门锁事件 all updated correctly for both.
    * the automatic re-lock after an unlock reports up=43 on this lock (the
      unlabelled door-close-class code above), not KW02's 38: the logbook
      shows lockStatus returning to 已关门 with no lock event.  38 stays in
      the lock set on family evidence; 43 deliberately produces nothing.
    * alarm labels (das 1-15) come from the Profile enum; only das=-1 (无
      告警) has been observed on the wire so far.

Read-only on purpose: the Profile declares lockStatus and update.action as
RW, but on the KW02 the firmware acks such writes and ignores them (假成功),
and the vendor App exposes no remote control for the series either.  The lock
entity therefore registers explicit refusal actions -- HA always renders
上锁/解锁 buttons, and pressing them raises a self-explanatory error instead
of the generic "adapter action is unavailable" or, far worse, a silent fake
success.  The refusal never sends anything to the lock (covered by a test),
and OTA stays unmapped entirely.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from .api import EntitySpec
from .context import DeviceContext
from ..domain.models import parse_remote_timestamp

_LOGGER = logging.getLogger(__name__)

_LOCK_STATUS_SID = "lockStatus"
_LOCK_STATUS_FIELD = "status"

# Battery readings, two possible sources in this family.
#
# The Profile declares doorBattery.level (lock body) and catEyeBattery.level
# (cat eye), and the KW5J firmware reads them there.  On the AGS-E211 (and
# KW02) neither service is ever pushed -- both levels arrive through
# batteryManager, which the Profile does not declare at all:
#   lithiumBatteryLevel     -> 锂电池电量 (锁体)
#   accumulatorBatteryLevel -> 干电池电量 (猫眼)
# Both sources are consulted: the Profile's own services first (they are what
# the vendor documents for this product), then batteryManager as the fallback
# this lock was observed to use.  Wire check on the AGS-E211: batteryManager
# is the live source (lithium 22%, dry 92%).
_BATTERY_SID = "batteryManager"
_LITHIUM_BATTERY_FIELD = "lithiumBatteryLevel"
_DRY_BATTERY_FIELD = "accumulatorBatteryLevel"

# Profile-declared battery services, tried first (never pushed on this lock).
_DOOR_BATTERY_SID = "doorBattery"
_CAT_EYE_BATTERY_SID = "catEyeBattery"
_BATTERY_LEVEL_FIELD = "level"

# The dry-cell warning rides batteryManager.lpmStatus; doorAlarmState travels
# with the event record.  The Profile's lockAlarm service is registered but
# never pushed (empty body on every known family member).
_LOCK_ALARM_SID = "lockAlarm"
_LOCK_ALARM_FIELD = "alarm"
_BATTERY_LPM_FIELD = "lpmStatus"
_LPM_ACTIVE = 1

_NET_INFO_SID = "netInfo"
_NET_INFO_FIELD = "intensity"

# The Profile names these concepts event.userOperation and event.doorAlarmState,
# but the lock pushes them on the wire under the short names below, split over
# two service ids:
#
#   sid="eventData"  {"data": "{\"uic\":0,\"up\":43,\"eid\":\"3013\",...}"}
#        sent for every operation; ``data`` is a JSON string whose ``up``
#        carries the Profile userOperation code.
#   sid="event"      {"eid":"...","up":200,"aid":"...MOTION_DETECTION_..."}
#        the user-facing copy; on this lock it also carries cat-eye records
#        whose ``up`` lives outside the Profile enum.
#
# eventData is therefore the source of truth for userOperation and
# doorAlarmState, and it is the only sid that reports interior unlocks.
_EVENT_SID = "event"
_EVENT_DATA_SID = "eventData"
_EVENT_DATA_PAYLOAD_FIELD = "data"
_USER_OPERATION_FIELD = "up"
_DOOR_ALARM_FIELD = "das"
_EVENT_ID_FIELD = "eid"
_EVENT_TIME_FIELD = "et"

# The event feed: every lock operation is reported on at least one of these
# services, so the door-leaf gate below treats a push on any of them as "the
# record explaining the new lockStatus has arrived".  doorEvent and
# lastActionTime also feed the read-only entities further down.
_DOOR_EVENT_SID = "doorEvent"
_LAST_ACTION_SID = "lastActionTime"
_EVENT_FEED_SIDS = frozenset(
    {_EVENT_SID, _EVENT_DATA_SID, _DOOR_EVENT_SID, _LAST_ACTION_SID}
)

# Profile characteristic names, used only to resolve enum labels.
_USER_OPERATION_PROFILE_FIELD = "userOperation"
_DOOR_ALARM_PROFILE_FIELD = "doorAlarmState"

# lockStatus/status values declared by the KW59 Profile (identical to KW02).
_STATUS_DOOR_AJAR_LOCKED = 1  # 门未关异常上锁
_STATUS_UNLOCKED = 2  # 已开锁
_STATUS_LOCKED = 3  # 已上锁
_STATUS_DOOR_CLOSED = 4  # 已关门
_STATUS_DEADBOLTED = 6  # 已反锁

_LOCKED_STATUSES = frozenset(
    {_STATUS_DOOR_AJAR_LOCKED, _STATUS_LOCKED, _STATUS_DEADBOLTED}
)
_UNLOCKED_STATUSES = frozenset({_STATUS_UNLOCKED, _STATUS_DOOR_CLOSED})

# The door leaf itself is unambiguous on these states only.
_DOOR_OPEN_STATUSES = frozenset({_STATUS_DOOR_AJAR_LOCKED, _STATUS_UNLOCKED})
_DOOR_CLOSED_STATUSES = frozenset(
    {_STATUS_LOCKED, _STATUS_DOOR_CLOSED, _STATUS_DEADBOLTED}
)

# Every lockStatus value the Profile declares.  Undescribed transitional
# values (KW02's firmware reports a bare 7 between 已上锁 and 已开锁) are held
# back and the last declared state stays on screen, which is what the vendor
# App shows too.
_DECLARED_STATUSES = _LOCKED_STATUSES | _UNLOCKED_STATUSES

# lockAlarm/alarm values declared by the Profile.
_ALARM_LOW_BATTERY = 2  # 低电量告警

# The lock reports -1 for doorAlarmState while nothing is wrong.  That is a
# real "no alarm" reading, so it is surfaced as such instead of being dropped
# as an unknown state.
_NO_ALARM = "无告警"

# How long a latched ``lockAlarm`` reading keeps counting as current.  The
# cloud raises the alarm once and never sends the cleared value.
_ALARM_PULSE_WINDOW = timedelta(hours=12)

# doorBattery/level and catEyeBattery/level declare min = -1, which is not a
# real percentage and is therefore projected as an unknown state.
_BATTERY_UNKNOWN = -1

# event.userOperation values that describe a deliberate unlock.  0-7 and 24
# are declared by this product's Profile; 35/37 are interior-unlock codes the
# KW02 firmware was observed to use (no AGS-E211 unlock captured yet -- see
# the module docstring).  Everything else is not an unlock.
_OPERATION_INDOOR_HANDLE = 35  # 室内一握开锁 (KW02 wire, unverified here)
_OPERATION_INDOOR_KNOB = 37  # 旋钮或钥匙开锁 (KW02 wire, unverified here)
_OPERATION_RELOCK = 38  # 上锁 (KW02 wire; AGS-E211 shows 43 instead, unlabelled)

# The Profile's userOperation enum stops at 33, so interior codes have no
# Profile label.  The labels below are KW02 family observations, not AGS-E211
# wire facts; an AGS-E211 unlock reporting an unknown code will surface as a
# bare number until someone reads the vendor App's name for it.
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

    The Profile only describes codes 0-33, so interior codes this firmware
    may report fall back to the family labels read off the KW02 wire.
    """

    label = _enum_label(field, value)
    if label is not None:
        return label
    number = _number(value)
    if number is None:
        return None
    return _FIRMWARE_OPERATION_LABELS.get(number)


# The Profile declares lockStatus/status as RW, so this adapter would be
# entitled to register lock and unlock actions -- and the KW02 one did, once.
# That firmware accepts the write and then ignores it: the lock acks the
# command with errcode=0 and immediately re-reports its unchanged status, and
# the vendor App exposes no remote unlock for the series either.  HA's lock
# entity always renders 上锁/解锁 buttons, so the actions below exist solely
# to refuse with a self-explanatory error: pressing them raises instead of
# sending anything, which is both honest and safer than the generic
# "adapter action is unavailable" (and far safer than a silent fake success).
def _refusal_action(verb: str):
    async def refuse(context: DeviceContext, data: Mapping[str, Any]) -> None:
        del context, data
        raise ValueError(f"该门锁不支持远程{verb}，请直接使用门锁面板操作")

    return refuse


def _lock_spec() -> EntitySpec:
    def lock_state(device: DeviceContext) -> Mapping[str, Any]:
        status = _read_status(device)
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
        actions={
            "lock": _refusal_action("上锁"),
            "unlock": _refusal_action("开锁"),
        },
    )


# ---------------------------------------------------------------------------
# Per-device shared state.
#
# ``DeviceContext.entity_specs`` rebuilds the entity specs on every read, so
# a closure cache dies with each rebuild and two platforms (the door binary
# sensor and the direction/method sensors) would keep private, diverging
# copies.  All latches below therefore live in one module-level dict keyed
# by dev_id, and every entity instance reads the same picture.
# ---------------------------------------------------------------------------
_DEVICE_STATE: dict[str, dict[str, Any]] = {}


def _device_state(device: DeviceContext) -> dict[str, Any]:
    """Return the shared latch/sequence state for one device."""

    state = _DEVICE_STATE.get(device.dev_id)
    if state is None:
        state = {
            "status": None,  # last declared lockStatus (live push or snapshot)
            "live_status": None,  # last declared lockStatus seen on a live push
            "door": None,  # last published door-leaf state
            "unlock": None,  # latched latest unlock {operation, eid, time}
            "seq": 0,  # monotonic count of accepted live service updates
            "status_seq": 0,  # seq of the last live lockStatus update
            "event_seq": 0,  # seq of the last live event-feed update
            "unlock_seq": 0,  # seq of the update that delivered ``unlock``
            "settled_seq": 0,  # seq when the door leaf last changed
            "tracked": False,  # live updates are being sequenced
            "gated": False,  # the door leaf waits for its event data
        }
        _DEVICE_STATE[device.dev_id] = state
    return state


def _read_status(device: DeviceContext) -> Any:
    """Read lockStatus, keeping the last declared value.

    lockStatus/status is the service every entity of this product reads, and
    the firmware may report a value the Profile does not declare (KW02
    observes a transitional 7).  Returning the last declared one keeps 门锁 /
    门锁状态 / 门 describing the same state instead of letting a transitional
    code blank all three out.
    """

    state = _device_state(device)
    status = _number(device.value(_LOCK_STATUS_SID, _LOCK_STATUS_FIELD))
    if status in _DECLARED_STATUSES:
        state["status"] = status
    return state["status"]


def _lock_status_spec(profile: Mapping[str, Any]) -> EntitySpec:
    field = _field(profile, _LOCK_STATUS_SID, _LOCK_STATUS_FIELD) or {}

    def state(device: DeviceContext) -> Mapping[str, Any]:
        value = _read_status(device)
        if value is None:
            return {"native_value": None}
        return {"native_value": _enum_label(field, value) or str(value)}

    return EntitySpec(
        platform="sensor",
        key="lock_status",
        name="门锁状态",
        state=state,
    )


def _battery_level(device: DeviceContext, profile_field: str) -> int | float | None:
    """Read one battery from the Profile service, then batteryManager.

    Either source reporting nothing yields None (unknown) rather than a wrong
    number; the Profile's min=-1 placeholder is not a real percentage.
    """

    value = _number(device.value(profile_field, _BATTERY_LEVEL_FIELD))
    if value is not None and value > _BATTERY_UNKNOWN:
        return value
    return None


def _battery_spec(
    profile_field: str,
    manager_field: str,
    key: str,
    name: str,
) -> EntitySpec:
    def state(device: DeviceContext) -> Mapping[str, Any]:
        value = _battery_level(device, profile_field)
        if value is None:
            value = _number(device.value(_BATTERY_SID, manager_field))
            if value is not None and value <= _BATTERY_UNKNOWN:
                value = None
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


def _lock_alarm_is_stale(device: DeviceContext) -> bool:
    """Report whether a ``lockAlarm`` reading is older than the pulse window.

    ``lockAlarm`` latches: the lock raises it once and the cloud never
    sends the cleared value.  An unparsable timestamp is *not* evidence of
    staleness (the live MQTT ``ts`` carries fractional digits
    ``parse_remote_timestamp`` rejects), so it keeps the latched state.

    Both 门锁告警 and 低电量告警 gate their ``lockAlarm`` branch on this:
    past the window a latched reading stops describing the present, so it
    must not keep a replaced battery's low-power alarm on forever nor mask
    a fresh ``lpmStatus`` reading.
    """

    when = device.service_updated_at(_LOCK_ALARM_SID)
    if when is None:
        return False
    return datetime.now(timezone.utc) - when > _ALARM_PULSE_WINDOW


def _alarm_spec(profile: Mapping[str, Any]) -> EntitySpec:
    lock_field = _field(profile, _LOCK_ALARM_SID, _LOCK_ALARM_FIELD) or {}
    door_field = _field(profile, _EVENT_SID, _DOOR_ALARM_PROFILE_FIELD) or {}

    def state(device: DeviceContext) -> Mapping[str, Any]:
        value = _number(device.value(_LOCK_ALARM_SID, _LOCK_ALARM_FIELD))
        if value is not None and value >= 1 and not _lock_alarm_is_stale(device):
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
        # ``lockAlarm`` latches, so past the pulse window a latched reading
        # must stop answering for the battery and yield to the live
        # ``lpmStatus`` (same window the alarm sensor applies).
        if alarm is not None and alarm >= 1 and not _lock_alarm_is_stale(device):
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


def _door_spec() -> EntitySpec:
    """Expose the door leaf, holding a transition until its event data lands.

    The lock pushes lockStatus and the event services in separate messages
    and the status copy can win the race, so an automation triggering on
    门-已打开 used to read a stale 开门方向 / 最近开门方式.  A leaf
    transition is therefore held back until the event feed has delivered the
    record that explains the new status: an opening waits for the unlock
    itself, a closing waits for any event-feed record.  All entities of one
    push are written in the same synchronous update cycle and Home Assistant
    runs trigger callbacks only afterwards, so when the leaf finally flips,
    every value read off the door trigger is already up to date.

    The gate only ever *delays* a transition; it cannot block one forever in
    the wrong direction, because the next operation pushes new event data
    and a snapshot resync that already carries the matching event data
    publishes immediately (``status != live_status``).
    """

    def state(device: DeviceContext) -> Mapping[str, Any]:
        state_ = _device_state(device)
        status = _read_status(device)
        # Warm the unlock latch from the standing record: a snapshot resync
        # can carry both the new status and its event data in one merge.
        _read_unlock(device)

        desired: bool | None = None
        if status in _DOOR_OPEN_STATUSES:
            desired = True
        elif status in _DOOR_CLOSED_STATUSES:
            desired = False

        held = state_["door"]
        if desired is None or held is None or desired == held:
            if held is None and desired is not None:
                # First evaluation after startup: the standing snapshot is
                # self-consistent, so publish it as-is.
                state_["door"] = desired
                state_["settled_seq"] = state_["seq"]
            return {"is_on": state_["door"]}

        if not state_["gated"] or status != state_["live_status"]:
            # No live tracking, or the new status arrived through a snapshot
            # whose event data was merged alongside it: publish now.
            passed = True
        elif desired:
            # Opening: the unlock that explains it must have arrived.
            passed = state_["unlock_seq"] > state_["settled_seq"]
        else:
            # Closing: any event-feed record for the close must have arrived.
            passed = state_["event_seq"] > state_["settled_seq"]
        if passed:
            state_["door"] = desired
            state_["settled_seq"] = state_["seq"]
        return {"is_on": state_["door"]}

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

    ``event`` publishes the user-facing fields while ``eventData`` carries the
    Profile userOperation and doorAlarmState codes, so eventData's fields win
    when both describe the same event.  Its copy is normally a JSON string
    inside ``data``, but a revision may deliver it already parsed.
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
        "KW59 event record: event=%s eventData=%s merged=%s",
        device.service_state(_EVENT_SID),
        raw,
        record,
    )
    return record


def _event_kind(record: Mapping[str, Any]) -> str | None:
    """Classify one lock event record as unlock / lock / alarm / motion.

    The classification mirrors the adapter's own state entities so an event
    and its matching sensor can never disagree about what happened.

    Wire quirks driving the order of the checks (both observed on the
    AGS-E211): the cat-eye motion copy carries ``up: 200`` with the
    ``MOTION_DETECTION`` token inside ``aid``, and ``eventData`` reports
    door-close-class operations such as ``up: 43`` with no user name -- those
    must not surface as unlocks, so the aid token is checked first and an
    unknown operation without a user name produces nothing.
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
    """Return the identifier the lock assigns to one occurrence."""

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
    the state entities only describe *what happened last*.  This decoder
    supplies the missing half: each accepted push fires an event.

    ``event`` carries the user-facing fields (``un`` = user name, ``cl`` =
    clock) while ``eventData`` carries the operation and alarm codes.  A push
    is decoded on its own fields; the other service only fills in what this
    push lacks, and never its identity (``eid``/``aid``/``et``).
    """

    if sid not in (_EVENT_SID, _EVENT_DATA_SID):
        return []

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
        # The other service only fills in what this push lacks -- its flat
        # fields included, not just the parsed ``data`` payload.
        for key, value in device.service_state(_EVENT_DATA_SID).items():
            if key == _EVENT_DATA_PAYLOAD_FIELD:
                continue
            current.setdefault(key, value)
        other = _parsed_payload(
            device.value(_EVENT_DATA_SID, _EVENT_DATA_PAYLOAD_FIELD)
        )
        for key, value in other.items():
            if key in ("eid", "aid", "id", "et"):
                continue
            current.setdefault(key, value)

    merged = current

    kind = _event_kind(merged)
    if kind is None:
        # Credential management, door-close bookkeeping (up=43 on this lock),
        # arming, doorbell and similar records produce nothing.
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


def _read_unlock(device: DeviceContext) -> Mapping[str, Any]:
    """Return the latched latest unlock, refreshing it from the standing record.

    The lock reports every operation on ``eventData``, so reading the field
    directly would let a following record such as the door-close copy (up=43)
    overwrite the unlock code.  The most recent value recognised as an unlock
    is latched instead -- per device, so a rebuild of the entity specs (or a
    reconnect) cannot forget it.

    A *new* unlock also advances ``unlock_seq``: live pushes do so through
    the tracker, and this path covers a snapshot resync that already merged
    the matching event data, letting a held-back door transition publish.
    """

    state = _device_state(device)
    record = _event_record(device)
    operation = _number(record.get(_USER_OPERATION_FIELD))
    if _unlock_direction(operation) is not None:
        latch = {
            "operation": operation,
            "eid": record.get(_EVENT_ID_FIELD),
            "time": record.get(_EVENT_TIME_FIELD),
        }
        if state["unlock"] != latch:
            state["unlock"] = latch
            state["unlock_seq"] = max(state["unlock_seq"], state["seq"])
    # An empty mapping before the first unlock: callers read ``.get`` off the
    # return value, and a None would raise inside the entity's state property,
    # which Home Assistant renders as an unavailable (离线) entity.
    return state["unlock"] or {}


def _unlock_attribute_state(
    unlock: Mapping[str, Any],
    native_value: Any,
) -> dict[str, Any]:
    """Publish the event id where the sensor platform can see it.

    Two unlocks through the same method leave 开门方向 / 最近开门方式
    unchanged, so a state trigger on the value alone never fires for the
    second one.  The triggering event's id and clock ride along as
    attributes instead: they change on every unlock, and both come from one
    state read, so they always describe the same event.
    """

    if native_value is None:
        return {"native_value": None}
    attributes: dict[str, Any] = {}
    event_id = unlock.get("eid")
    event_time = unlock.get("time")
    if event_id is not None and str(event_id).strip():
        attributes["last_event_id"] = str(event_id).strip()
    if event_time is not None and str(event_time).strip():
        attributes["last_event_time"] = str(event_time).strip()
    result: dict[str, Any] = {"native_value": native_value}
    if attributes:
        result["extra_state_attributes"] = attributes
    return result


def _push_user_operation(sid: str, data: Mapping[str, Any]) -> Any:
    """Return the userOperation code carried by one push itself.

    The gate must not consult the merged standing record here: ``event``
    pushes carry their own ``up`` in a different code space (200 is cat-eye
    motion), and the merged record would still hold the previous eventData
    unlock, so a motion push would masquerade as a fresh unlock.
    """

    if sid == _EVENT_DATA_SID:
        raw = data.get(_EVENT_DATA_PAYLOAD_FIELD)
        record: Any = raw
        if isinstance(raw, str) and raw:
            try:
                record = json.loads(raw)
            except ValueError:
                return None
    elif sid == _EVENT_SID:
        record = data
    else:
        return None
    if not isinstance(record, Mapping):
        return None
    return _number(record.get(_USER_OPERATION_FIELD))


def _install_tracker(device: DeviceContext) -> None:
    """Sequence live service updates for the door-leaf gate, once per context.

    ``DeviceContext`` notifies its service-update listeners -- in push order
    -- before any entity writes state, so the counters below are always
    ahead of what the entities read.  Without the listener API there is no
    sequence to gate on and the door keeps publishing immediately (the
    pre-gate behaviour).
    """

    state = _device_state(device)
    if getattr(device, "_kw59_tracker_installed", False):
        return
    device._kw59_tracker_installed = True
    installer = getattr(device, "add_service_update_listener", None)
    if installer is None:
        state["tracked"] = False
        return
    state["tracked"] = True

    def on_service_update(
        sid: str,
        data: Mapping[str, Any],
        timestamp: str | None,
    ) -> None:
        del timestamp
        state["seq"] += 1
        if sid == _LOCK_STATUS_SID:
            state["status_seq"] = state["seq"]
            status = _number(data.get(_LOCK_STATUS_FIELD))
            if status in _DECLARED_STATUSES:
                state["live_status"] = status
            return
        if sid in _EVENT_FEED_SIDS:
            state["event_seq"] = state["seq"]
        if _unlock_direction(_push_user_operation(sid, data)) is not None:
            state["unlock_seq"] = state["seq"]

    installer(on_service_update)


def _open_direction_spec() -> EntitySpec:
    """Expose whether the latest unlock came from the indoor or outdoor side."""

    def state(device: DeviceContext) -> Mapping[str, Any]:
        unlock = _read_unlock(device)
        return _unlock_attribute_state(
            unlock, _unlock_direction(unlock.get("operation"))
        )

    return EntitySpec(
        platform="sensor",
        key="open_direction",
        name="开门方向",
        state=state,
    )


def _last_open_method_spec(profile: Mapping[str, Any]) -> EntitySpec:
    """Expose the Profile label of the latest unlock operation."""

    field = _field(profile, _EVENT_SID, _USER_OPERATION_PROFILE_FIELD) or {}

    def state(device: DeviceContext) -> Mapping[str, Any]:
        unlock = _read_unlock(device)
        value = _number(unlock.get("operation"))
        if value is None:
            return _unlock_attribute_state(unlock, None)
        return _unlock_attribute_state(
            unlock, _operation_label(field, value) or str(value)
        )

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


class ProductKW59Adapter:
    """HUAWEI SmartLock E211 (AGS-E211) entity and command choices."""

    prod_id = "KW59"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None or not context.has_service(_LOCK_STATUS_SID):
            return ()

        has_event_feed = context.has_service(_EVENT_SID) or context.has_service(
            _EVENT_DATA_SID
        )
        _install_tracker(context)
        # The door gate needs both the live-update sequence and the event
        # services it waits for; without either the leaf publishes as before.
        state = _device_state(context)
        state["gated"] = state["tracked"] and has_event_feed
        entities: list[EntitySpec] = [
            _lock_spec(),
            _lock_status_spec(profile),
            _door_spec(),
        ]
        if context.has_service(_DOOR_BATTERY_SID) or context.has_service(
            _BATTERY_SID
        ):
            entities.append(
                _battery_spec(
                    _DOOR_BATTERY_SID,
                    _LITHIUM_BATTERY_FIELD,
                    "lithium_battery",
                    "锂电池电量",
                )
            )
            entities.append(
                _battery_spec(
                    _CAT_EYE_BATTERY_SID,
                    _DRY_BATTERY_FIELD,
                    "dry_battery",
                    "干电池电量",
                )
            )
        if context.has_service(_LOCK_ALARM_SID):
            entities.append(_alarm_spec(profile))
            entities.append(_low_battery_spec())
        if context.has_service(_NET_INFO_SID):
            entities.append(_wifi_signal_spec())
        if has_event_feed:
            entities.append(_open_direction_spec())
            entities.append(_last_open_method_spec(profile))
            entities.append(_door_alarm_spec(profile))
            # The state entities above describe the latest operation; this
            # event entity fires on every operation, so an automation runs on
            # each unlock instead of only on the first one.
            entities.append(_lock_event_spec())
        entities.extend(_firmware_specs(context))
        entities.extend(_roster_specs(context))
        entities.extend(_reader_based_specs(context))
        return tuple(entities)


# ---------------------------------------------------------------------------
# Read-only reporting entities.
#
# The AGS-E211 pushes 34 services while the Profile documents 20.  Everything
# below is a read-only projection of services observed on the real lock; no
# command is offered anywhere in this adapter.
#
# Wire details confirmed against the lock (deviating from the Profile):
#   update         currentVersion is a firmware string
#                  ("AGS-E211 5.0.0.1(SP43C00)").  update.action is not mapped.
#   users          userList carries every enrolled member (un = name).
#   ciphers / keyCards / watchs / walletKeys
#                  further credential rosters this model pushes.
#   doorEvent      the per-event feed; only its userName is read (the event
#                  code space is undocumented).
#   lastActionTime time is the last time the lock was operated.
# ---------------------------------------------------------------------------

_UPDATE_SID = "update"
_USERS_SID = "users"
_FACES_SID = "faces"
_FINGERS_SID = "fingers"
_CIPHERS_SID = "ciphers"
_KEY_CARDS_SID = "keyCards"
_WATCHS_SID = "watchs"
_WALLET_KEYS_SID = "walletKeys"


def _firmware_specs(context: DeviceContext) -> list[EntitySpec]:
    """Firmware version of the lock body.

    Read-only on purpose: the Profile's ``update.action`` would let HA start
    an OTA, which has not been validated on this hardware.
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
    """Enrolled-credential counts, e.g. how many fingerprints exist."""

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
    if context.has_service(_CIPHERS_SID):
        specs.append(make_count(_CIPHERS_SID, "cipher", "cipher_count", "密码数"))
    if context.has_service(_KEY_CARDS_SID):
        specs.append(make_count(_KEY_CARDS_SID, "keyCard", "keycard_count", "门卡数"))
    if context.has_service(_WATCHS_SID):
        specs.append(
            make_count(_WATCHS_SID, "watch", "watch_count", "手表手环数")
        )
    if context.has_service(_WALLET_KEYS_SID):
        specs.append(
            make_count(_WALLET_KEYS_SID, "walletKey", "wallet_key_count", "钱包钥匙数")
        )
    return specs


def _reader_based_specs(context: DeviceContext) -> list[EntitySpec]:
    """Last-operated metadata reported as plain text.

    These services are event-driven: the lock pushes doorEvent and
    lastActionTime only when something happens, so none of them appears in
    the discovery snapshot and ``has_service`` is false for them at setup
    time.  They are therefore always registered and simply report unknown
    until the first event arrives.
    """

    def door_user(device: DeviceContext) -> Mapping[str, Any]:
        value = device.value(_DOOR_EVENT_SID, "userName")
        return {"native_value": value if isinstance(value, str) and value else None}

    def last_action(device: DeviceContext) -> Mapping[str, Any]:
        value = device.value(_LAST_ACTION_SID, "time")
        if not isinstance(value, str) or not value:
            return {"native_value": None}
        # The lock reports SmartHome stamps ("20260915T232350Z"), not ISO
        # 8601.  Parsing them lets the entity carry device_class=timestamp so
        # Home Assistant renders a relative time.  An unparsable stamp
        # reports None rather than a string HA would reject under this class.
        return {"native_value": parse_remote_timestamp(value)}

    return [
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
            metadata={"entity_category": "diagnostic", "device_class": "timestamp"},
        ),
    ]


ADAPTER = ProductKW59Adapter()
