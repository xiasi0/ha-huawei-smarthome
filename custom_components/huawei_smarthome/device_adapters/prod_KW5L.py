"""Product adapter for the HUAWEI SmartLock 2 Pro (KW5L / AGS-X20).

Profile: https://smarthome-drcn.dbankcdn.com/device/guide/KW5L/KW5L.json
Device type: A0B 智能门锁 (SmartLock), manufacturer 华为.

Scope and evidence
------------------
Everything mapped below comes from the Profile this adapter receives at
runtime; nothing is hard-coded from another product's wire capture.  The
SmartLock family already in this repository (KW02 / KW38 / KW4X / KW5J /
KW59) agrees on the parts that matter here: the ``lockStatus`` value space,
the ``alarmEventSetting`` / ``catEyeSetting`` switches, the volume block and
the ``event`` record.  Those family observations are cited explicitly where
they are used, and every field that is only known from the Profile is marked
as unverified.

Security decisions (why this adapter writes less than the Profile allows)
------------------------------------------------------------------------
1. **No remote lock/unlock.**  The Profile declares ``lockStatus/status`` as
   RW, so HA's lock entity *could* offer 上锁/解锁.  A first version of this
   file sent them.  That is refused here, for the same reason KW02/KW38/KW4X/
   KW5J/KW59 refuse it: on this family the firmware acks such a write with
   ``errcode=0`` and then re-reports its unchanged state (假成功), and the
   vendor App exposes no remote unlock either.  A control that reports success
   without moving the bolt is worse than a missing control -- and on a door
   lock an *automated* unlock that silently succeeds is a physical-security
   event.  This adapter therefore creates no ``lock`` entity at all: 门锁状态 /
   门 / 反锁 report the state, and there is no control that can be pressed into
   doing nothing.

2. **No credential material in Home Assistant state.**  The Profile exposes
   ``ciphers`` (``cp`` = the verification value), ``faces``/``fingers``
   (``cp`` = template payload), ``keyCards``/``watchs``/``walletKeys``,
   ``users`` (``uid``) and ``temporaryCipher`` (``ct`` = the temporary
   password itself).  Reading any of those into an entity would copy door
   credentials into the HA state machine, the recorder database, logbook
   exports and every backup -- the same conclusion ``prod_2265.py`` reaches.
   Only *counts* of the enrolled rosters are surfaced; ``cp``, ``ct``,
   ``auth``, ``uid`` and the raw lists are never read.

3. **No remote OTA.**  ``update/action`` is declared RW and a first version
   of this file exposed 检查新版本 / 启动固件升级 buttons.  Starting an
   unverified firmware flash on a door lock can leave the bolt uncontrollable,
   and the sibling adapters leave OTA unmapped.  Firmware version is
   reported read-only instead.

4. **No write to ``securitySetting``.**  This service is admin-gated: its
   ``isAuth`` characteristic selects 需要携带管理员密码 and ``auth`` is a
   400-character admin credential that the command would have to carry.
   Writing it would put an admin password into the command body (and into any
   debug capture of it), and the gate itself is unverified for this product.
   ``deploymentSwitch``, ``faceIdentifySwitch``, ``enableSenserOpenSwitch``,
   ``doubleCheckSwitch``, ``passwordVerificationSwitch`` and
   ``enableLockoutSwitch`` are therefore surfaced **read-only**: they stay
   visible in HA (and usable in automations as conditions), but nothing here
   can remotely weaken the lock's verification requirements.

5. **Writes are limited to preferences that cannot weaken access.**  After the
   App comparison the writable set is exactly three things: the message-push
   window on ``alarmEventSetting`` (``messagePushTime`` plus ``startTime`` /
   ``endTime``), 逗留抓拍 on ``catEyeSetting``, and 夜间自动调低音量 with its
   window on ``volumeSetting``.  ``messagePushSwitch`` is read-only: it is the
   master switch, and silently disabling every lock alert from an automation
   platform is a monitoring regression rather than a convenience.

Real-device findings
--------------------
The message-push window is exposed as the ``消息推送时间`` selector (全天 /
自定义时间, Profile default 全天) plus two writable text entities for
``startTime`` / ``endTime``.  The vendor App (华为智慧生活) shows the same three
controls on one page -- an earlier version of this file exposed the window
*without* the selector, which left it with no reachable caller and made the
pair look inert; both halves are mapped together now.  The 夜间自动调低音量 window
(``volumeSetting.startTime`` / ``endTime``) is mapped the same way, next to the
switch it belongs to.

Later App passes dropped everything the App has no counterpart for: the ``lock``
entity (its 上锁/解锁 buttons could only ever raise), every writable alert
switch (门未关 / 开锁 / 防撬 / 非法开锁 / 警戒模式 / 门外开门 / 低电量), both
pending-window delays (门外/门内告警延时), 异常抓拍
(``alarmEventSetting.takeSnapshotSwitch``), the 猫眼拍照 / 实时视频 / 微光全彩
/ 畸变校正 switches (实时视频 is an action in the App rather than a lasting
setting, so no switch can track it), 当前铃声 and all three volumes (铃声音量 /
按键音量 / 语音音量), and the 拍摄间隔 / 通话有效期 / 检测距离 / 逗留多久开始录像 /
录像最大时长 selects.  Do not re-add any of them from the Profile alone.

逗留多久开始录像 (``stayDuration``) deserves its own note: the App offers
立即录像 / 3 / 6 / 9 / 15 / 20 / 30 / 60 秒, which does not overlap this Profile's
enumList (0..12 = 3..15 秒), so the option table could not be built from either
source alone.  A temporary probe was added to read the device's raw values, but
the entity was retired before that capture happened.  If it is ever restored,
capture the raw values first -- do not map the App's order onto 0..7, because the
Profile states 0 = 3 秒.

The ``catEyeSetting`` window (``startTime`` / ``endTime``) stays unmapped: the
App exposes no matching control for it, the Profile declares no value format,
and ``prod_D0AM.py`` records the same-shaped ``maxLength: 8`` field reporting
``"10001200"`` on real hardware with unconfirmed meaning.  Do not re-add it
from the Profile alone.

What is exposed
---------------
    sensor              门锁状态 / 网络状态 / 门锁告警 / 最近门锁告警
    sensor              门锁电池 / 猫眼电池 / 网络信号强度 / WiFi RSSI / IP 地址
    binary_sensor       门 / 反锁 / 门未关异常上锁 / 低电量告警
    sensor              固件版本 / 用户数 / 人脸数 / 指纹数 / 密码数 /
                        门卡数 / 手表手环数 / 钱包钥匙数 / 临时密码数
    sensor              开门方向 / 最近开门方式 / 最近门锁事件
    event               门锁事件 (unlock / lock / alarm / motion / doorbell /
                        arm / disarm / call / record)
    binary_sensor       消息推送总开关 (只读)
    select              消息推送时间
    text                消息推送开始/结束时间 (消息推送时间为「自定义时间」时生效)
    switch              夜间自动调低音量 / 逗留抓拍
    text                夜间自动调低音量开始/结束时间 (该开关开启时生效;
                        shares its prefix on purpose -- the device page sorts by name)
    binary_sensor       布防模式 / 人脸识别 / 感应开锁 / 双重验证 / 密码验证 /
                        锁定保护 (只读)
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from ..domain.models import parse_remote_timestamp
from .api import EntitySpec
from .context import DeviceContext

# =============================================================================
# Service and characteristic names (all from this product's Profile)
# =============================================================================

_LOCK_STATUS_SID = "lockStatus"
_LOCK_STATUS_FIELD = "status"

_NET_STATE_SID = "networkConnectState"
_NET_STATE_FIELD = "state"

_LOCK_ALARM_SID = "lockAlarm"
_LOCK_ALARM_FIELD = "alarm"

_ALARM_SETTING_SID = "alarmEventSetting"
_CAT_EYE_SETTING_SID = "catEyeSetting"
_SECURITY_SETTING_SID = "securitySetting"
_VOLUME_SETTING_SID = "volumeSetting"

_EVENT_SID = "event"
_EVENT_DATA_SID = "eventData"
_EVENT_DATA_PAYLOAD_FIELD = "data"
# This lock pushes a third per-event service the Profile does not declare.  A live
# capture shows it carrying {"eventType": 0|1, "event": N}: ``eventType`` is usable
# (0 = opening, 1 = locking), while ``event`` is **not** -- its code space is
# undocumented and does not share the Profile's ``userOperation`` numbering, so an
# observed ``event: 6`` read as an operation code would be mislabelled 临时密码开门.
# Only ``eventType`` is consulted, and only to refine a classification.
_DOOR_EVENT_SID = "doorEvent"
_DOOR_EVENT_TYPE_FIELD = "eventType"
_DOOR_EVENT_TYPE_OPEN = 0
_DOOR_EVENT_TYPE_LOCK = 1

_NET_INFO_SID = "netInfo"
_UPDATE_SID = "update"

_USERS_SID = "users"


# =============================================================================
# Enum spaces
# =============================================================================

# lockStatus/status: every value the Profile declares -- 1 门未关异常上锁,
# 2 已开锁, 3 已上锁, 4 已关门, 6 已反锁.  Anything else is a transitional reading
# this firmware can emit (the KW02 family does).
#
# Bolt position is only unambiguous where the name states it: 2 and 4 retract or
# hold the bolt, 3 and 6 drive it.  1 names an anomaly rather than a position --
# like every sibling lock adapter (KW02/KW38/KW4X/KW59) it is read as
# bolt-locked, and it also gets its own 门未关异常上锁 binary sensor so the anomaly
# is never hidden behind the generic locked state.
_DECLARED_STATUSES = frozenset({1, 2, 3, 4, 6})

_STATUS_DOOR_AJAR_LOCKED = 1
_STATUS_DEADLOCK = 6

# The leaf itself is unambiguous only in these states; 4 reports "closed"
# explicitly, which is the one status whose name states the leaf position.
_DOOR_LEAF_OPEN = frozenset({1, 2})
_DOOR_LEAF_CLOSED = frozenset({3, 4, 6})

# networkConnectState/state: 0 = offline, 1 = sleeping, 2 = online.
# A battery lock is asleep most of the time, so 休眠 must stay usable;
# only an explicit 离线 marks the entities unavailable.
_NET_STATE_SLEEPING = 1
_NET_STATE_ONLINE = 2
_NET_AVAILABLE_STATES = frozenset({_NET_STATE_SLEEPING, _NET_STATE_ONLINE})

# lockAlarm/alarm.  The Profile describes three conditions; the sibling
# adapters observe that this service is never actually pushed (they read the
# same concepts from batteryManager.lpmStatus and event.doorAlarmState), so it
# is surfaced only when the device really does report it.
_ALARM_LOW_BATTERY = 2

# low-battery detection bounds, shared with the sibling lock adapters.
_BATTERY_UNKNOWN = -1
_LOW_BATTERY_PERCENT = 10
_LOW_BATTERY_THRESHOLD = 5
_STALE_HOURS = 24.0

# event/userOperation codes that are deliberate unlocks.  0-7 and 24 are
# declared by this product's Profile; 35/37/38 are interior/relock codes the
# KW02 firmware was observed to send outside the Profile enum, kept for the
# same family reason (unverified on KW5L).
_OUTDOOR_UNLOCK_OPERATIONS = frozenset(range(8))
_OPERATION_INDOOR_HANDLE = 35
_OPERATION_INDOOR_KNOB = 37
_OPERATION_RELOCK = 38
_INDOOR_UNLOCK_OPERATIONS = frozenset(
    {24, _OPERATION_INDOOR_HANDLE, _OPERATION_INDOOR_KNOB}
)
_FAMILY_OPERATION_LABELS = {
    _OPERATION_INDOOR_HANDLE: "室内一握开锁",
    _OPERATION_INDOOR_KNOB: "旋钮或钥匙开锁",
    _OPERATION_RELOCK: "上锁",
}

# Codes this adapter knows are *not* an unlock.  Anything else the lock reports
# on the operation slot is treated as an unlock whose name is still missing, so
# 开门方向 says 未知 while 最近开门方式 shows the raw code (see
# ``_looks_like_unlock``).  Derived here because the tables above are defined
# after ``_KNOWN_NON_UNLOCK_OPERATIONS``'s first use site would be.
_KNOWN_NON_UNLOCK_OPERATIONS = frozenset(
    {22, 29, 30}          # 门铃响铃 / 敲门 / 连续按门铃
    | {27, 28}            # 开启布防 / 解除布防
    | {31, 32, 33}        # 门内 sensor 靠近 / 视频通话 / 视频录制
    | {43}                # 自动回锁 bookkeeping (sibling locks)
    | {_OPERATION_RELOCK}
    | {25, 26}            # 反锁 / 解除反锁
)

# Keys the two event transports use for the same concepts.  The Profile names
# them userOperation / doorAlarmState / userName / eventTime; the wire record
# observed on this family uses up / das / un / et (and nests it in
# eventData.data as a JSON string).  Both spellings are accepted.
_OPERATION_KEYS = ("userOperation", "up")
_ALARM_KEYS = ("doorAlarmState", "das")
_USER_KEYS = ("userName", "un")
_TIME_KEYS = ("eventTime", "et")

# Two more fields the live record carries.  Neither is read as an operation
# code, but both are reported in the diagnostic attributes because they are the
# cheapest way to tell record classes apart:
#   rt   observed 0 for unlock/relock records, 2 for the cat-eye motion stream
#   type observed 0 on every record so far
_RECORD_TYPE_KEYS = ("rt", "type")
_IDENTIFIER_KEYS = ("eid", "aid", "id")

# The fields echoed into the diagnostic attributes (the latched copy on
# 最近门锁事件 and the raw record dump): operation, alarm, user, timestamp, record
# type and identity tokens -- nothing else, so no credential can reach an attribute.
_DIAGNOSTIC_KEYS = (
    _OPERATION_KEYS
    + _ALARM_KEYS
    + _USER_KEYS
    + _TIME_KEYS
    + _RECORD_TYPE_KEYS
    + ("uic", "eid", "aid")
)

# The cat-eye motion copy is the one record whose identity lives on ``aid``
# (the sibling locks report ``up: 200`` with a MOTION_DETECTION token there),
# so the motion test reads that key specifically rather than whichever
# identifier happens to come first.
_AID_KEY = "aid"
_MOTION_MARKER = "MOTION_DETECTION"

# Event classes fired by the ``event`` entity.  Everything the lock reports
# maps onto exactly one of these, so no operation is silently dropped:
#   unlock / lock  a deliberate bolt operation (with method and direction)
#   alarm          any doorAlarmState >= 1
#   motion         cat-eye motion detection
#   doorbell       a ring or a knock at the door
#   arm / disarm   布防 was switched on or off
#   call           a video call or recording started
#   record         credential/user management bookkeeping
_EVENT_TYPES = (
    "unlock",
    "lock",
    "alarm",
    "motion",
    "doorbell",
    "arm",
    "disarm",
    "call",
    "record",
)
_DOORBELL_OPERATIONS = frozenset({22, 29, 30})  # 门铃响铃 / 敲门 / 连续按门铃

# Fallback wording for 最近门锁事件 when the operation code carries no Profile
# label or describes something other than a credential use.  Without this a
# cat-eye motion push would be labelled with its doorbell code and read 门铃响铃
# while event_kind said motion.
_EVENT_KIND_LABELS = {
    "motion": "移动侦测",
    "doorbell": "门铃",
    "arm": "布防",
    "disarm": "撤防",
    "call": "视频通话",
    "record": "记录",
    "alarm": "告警",
    "lock": "上锁",
    "unlock": "开锁",
}
_ARM_OPERATIONS = frozenset({27})
_DISARM_OPERATIONS = frozenset({28})
_CALL_OPERATIONS = frozenset({31, 32, 33})

# Credential / user management operations declared by the Profile.  These are
# bookkeeping even though the cat-eye token may ride along on the record, so
# they are named explicitly: an *unrecognised* code is the only one where the
# token is allowed to decide (see ``_event_kind``).
_RECORD_OPERATIONS = frozenset(
    {8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 23}
    # 反锁 / 解除反锁: bolt bookkeeping, not a credential use.
    | {25, 26}
)

# Operations observed on the sibling locks that carry no user-visible meaning
# (auto-relock bookkeeping).  They produce no event: firing a generic record
# for every re-lock would bury the events an automation cares about.  A code
# this adapter has never seen is still reported rather than dropped.
_UNKNOWN_BOOKKEEPING = frozenset({43})

# How long a latched one-shot reading keeps describing the present.  The cloud
# raises such values once and never sends the cleared value.
_ALARM_PULSE_WINDOW = timedelta(hours=12)

# How much later a door report must be before it retires an unlock from
# 开门方向 / 最近开门方式.  This lock re-locks by itself seconds after an unlock
# (observed 7 s), and the unlock is the thing the user wants to see, so the
# threshold is minutes -- anything shorter hid every fresh unlock.
_UNLOCK_SUPERSEDE_AFTER = timedelta(minutes=10)

# Absolute age after which a stored unlock stops answering at all.
_UNLOCK_MAX_AGE = timedelta(hours=24)

# lockStatus carries the device's own change time (observed: status + updateTime).
_LOCK_STATUS_TIME_FIELD = "updateTime"

# ``lockAlarm`` values the Profile declares; -1 is not part of this product's
# enum (it belongs to the sibling ``doorAlarmState``), but is tolerated as
# "no alarm" rather than being echoed as a fault.
_NO_ALARM_TEXT = "无告警"

_SECONDS_PER_HOUR = 3600.0

# =============================================================================
# Notifications.  What the owner is told about, never whether the door opens.
# =============================================================================

# Every writable alert switch was dropped by the App comparison, so the writable
# part of this block is just the message-push window -- see the module docstring.

# Read-only on purpose: the master notification switch.  Turning every lock
# alert off from an automation platform is a monitoring regression, so it is
# exposed as a read-only binary sensor instead of a control.
_MESSAGE_PUSH_SWITCH = "messagePushSwitch"

# Only 逗留抓拍 is left: 实时视频 and 猫眼拍照 were dropped by the App comparison
# (see the module docstring).
_CAT_EYE_SWITCHES: tuple[tuple[str, str], ...] = (
    ("staySnapshotSwitch", "逗留抓拍"),
)

# Read-only on purpose: these decide which credentials the lock will accept.
_SECURITY_SWITCHES: tuple[tuple[str, str], ...] = (
    ("deploymentSwitch", "布防模式"),
    ("faceIdentifySwitch", "人脸识别"),
    ("enableSenserOpenSwitch", "感应开锁"),
    ("doubleCheckSwitch", "双重验证"),
    ("passwordVerificationSwitch", "密码验证"),
    ("enableLockoutSwitch", "锁定保护"),
)

# Nothing on ``volumeSetting`` is written except night mode and its window; the
# three volumes and 当前铃声 were dropped by the App comparison.

# Enum selects resolved from the Profile's own enumList, in Profile order.  Only
# the message-push selector survived the App comparison -- see the module
# docstring for which ones were dropped and why.
_ENUM_SELECTS: tuple[tuple[str, str, str, str], ...] = (
    (_ALARM_SETTING_SID, "messagePushTime", "push_time_mode", "消息推送时间"),
)

# Used only when the Profile declares no maxLength -- the alarm fields declare 8,
# the volume fields declare nothing, and inventing a ceiling for those would
# reject values the device may well accept.  text.py clamps to 255 regardless.
_TEXT_MAX_LENGTH = 255

# Time windows (``startTime`` / ``endTime``, plain strings forwarded verbatim --
# no format is imposed here, because the Profile declares none).  Each pair only
# matters while the control it belongs to is active: 消息推送时间 must read
# 自定义时间 (Profile default 全天), and 夜间自动调低音量 must be on.  Both are on
# the Controls board with those controls, not on Configuration.
_TIME_WINDOWS: tuple[tuple[str, str, str, str], ...] = (
    (_ALARM_SETTING_SID, "startTime", "push_start_time", "消息推送开始时间"),
    (_ALARM_SETTING_SID, "endTime", "push_end_time", "消息推送结束时间"),
    # These two MUST keep the same leading characters as the 夜间自动调低音量
    # switch (``night_mode``): HA's device page groups by entity_category and
    # then sorts alphabetically by name, and it offers no way for an
    # integration to pin an order.  Sharing the prefix is what keeps the three
    # controls adjacent on the Controls board -- shortening these names would
    # scatter them (夜 U+591C sorts far from 调 U+8C03).
    (_VOLUME_SETTING_SID, "startTime", "night_start_time", "夜间自动调低音量开始时间"),
    (_VOLUME_SETTING_SID, "endTime", "night_end_time", "夜间自动调低音量结束时间"),
)

# Enrolled-credential rosters.  Only the entry count is reported: the objects
# themselves carry credential values (``cp``), identifiers (``uid``) and, for
# temporary ciphers, the password in clear.
_ROSTERS: tuple[tuple[str, str, str, str], ...] = (
    (_USERS_SID, "userList", "user_count", "用户数"),
    ("faces", "face", "face_count", "人脸数"),
    ("fingers", "finger", "finger_count", "指纹数"),
    ("ciphers", "cipher", "cipher_count", "密码数"),
    ("keyCards", "keyCard", "keycard_count", "门卡数"),
    ("watchs", "watch", "watch_count", "手表手环数"),
    ("walletKeys", "walletKey", "wallet_key_count", "钱包钥匙数"),
    ("temporaryCipher", "periodicCiper", "temporary_cipher_count", "临时密码数"),
)

# Battery sources.  The Profile declares doorBattery/catEyeBattery; the
# sibling locks instead push batteryManager (which KW5L does not declare at
# all), so both are consulted, Profile first.
_BATTERY_SID = "batteryManager"
_LITHIUM_BATTERY_FIELD = "lithiumBatteryLevel"
_DRY_BATTERY_FIELD = "accumulatorBatteryLevel"
_BATTERY_LEVEL_FIELD = "level"
_BATTERY_LPM_FIELD = "lpmStatus"
_LPM_ACTIVE = 1


# =============================================================================
# Small helpers
# =============================================================================


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


def _require_writable(
    profile: Mapping[str, Any] | None,
    sid: str,
    characteristic: str,
) -> None:
    """Refuse a write the Profile does not mark writable.

    Controls are built only when their characteristic exists, but nothing checked
    the *permission* before publishing: a Profile revision that made one of them
    read-only would still be written to, and the cloud would reject it.
    ``prod_ZG0F.py`` validates writes against the Profile schema the same way.
    """

    field = _field(profile or {}, sid, characteristic) or {}
    if "W" not in str(field.get("method", "")):
        raise ValueError(f"{sid}/{characteristic} is not writable in the Profile")


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    else:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
    return int(number) if number.is_integer() else number


def _enum_label(field: Mapping[str, Any] | None, value: Any) -> str | None:
    """Return the Profile label for one enum value."""

    if field is None:
        return None
    number = _number(value)
    for option in field.get("enumList", ()):
        if not isinstance(option, Mapping):
            continue
        if number is not None and _number(option.get("enumVal")) == number:
            label = option.get("descCh") or option.get("descEn")
            if isinstance(label, str) and label:
                return label
    return None


def _enum_options(
    field: Mapping[str, Any] | None,
) -> tuple[tuple[str, int | float | str], ...]:
    """Return ``(label, value)`` pairs in Profile order."""

    options: list[tuple[str, int | float | str]] = []
    if field is None:
        return ()
    for option in field.get("enumList", ()):
        if not isinstance(option, Mapping):
            continue
        raw = option.get("enumVal")
        label = option.get("descCh") or option.get("descEn")
        value = _number(raw)
        if value is None:
            value = raw if isinstance(raw, str) else None
        if value is None:
            continue
        options.append((str(label) if label else str(raw), value))
    return tuple(options)


def _operation_label(field: Mapping[str, Any] | None, value: Any) -> str | None:
    """Label an event operation, falling back to the family codes."""

    label = _enum_label(field, value)
    if label is not None:
        return label
    number = _number(value)
    if number is None:
        return None
    return _FAMILY_OPERATION_LABELS.get(number)


def _unlock_direction(value: Any) -> str | None:
    operation = _number(value)
    if operation is None:
        return None
    if operation in _INDOOR_UNLOCK_OPERATIONS:
        return "室内开门"
    if operation in _OUTDOOR_UNLOCK_OPERATIONS:
        return "室外开门"
    return None


def _battery_percent(value: Any) -> int | None:
    """Project a battery reading, treating the Profile's -1 as unknown."""

    number = _number(value)
    if number is None or number <= _BATTERY_UNKNOWN:
        return None
    return int(number)


def _first(record: Mapping[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in record and record[key] is not None:
            return record[key]
    return None


def _parse_stamp(value: Any) -> datetime | None:
    """Parse a SmartHome stamp such as ``20260915T232350Z``.

    Delegates to the shared :func:`parse_remote_timestamp` (the idiom in
    KW02/KW38/KW4X/KW59), which truncates the nanosecond fractions the old local
    parser rejected outright -- reporting a real timestamp as missing.  The
    dashed ISO shape stays as a fallback because the local parser accepted it.
    """

    if not isinstance(value, str) or not value.strip():
        return None
    # Strip first: parse_remote_timestamp checks the raw string's trailing "Z", so
    # a padded value would otherwise fall through to the ISO shape and fail.
    text = value.strip()
    parsed = parse_remote_timestamp(text)
    if parsed is not None:
        return parsed
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def _format_stamp(value: Any) -> str | None:
    """Compress a stamp into ``MM-DD HH:MM`` for a text sensor."""

    if not isinstance(value, str) or not value.strip():
        return None
    parsed = _parse_stamp(value)
    if parsed is None:
        return value.strip()
    return parsed.strftime("%m-%d %H:%M")


# =============================================================================
# Availability: a sleeping battery lock must not look dead
# =============================================================================


def _newest_report_age_hours(device: DeviceContext) -> float | None:
    """Hours since the freshest reported service state (None if unknown)."""

    now = datetime.now(timezone.utc)
    ages: list[float] = []
    states = getattr(device.descriptor, "service_states", None) or {}
    for service in states.values():
        parsed = _parse_stamp(getattr(service, "reported_timestamp", None))
        if parsed is not None:
            ages.append(max(0.0, (now - parsed).total_seconds()))
    if not ages:
        return None
    return min(ages) / _SECONDS_PER_HOUR


def _lowest_battery(device: DeviceContext) -> int | None:
    levels = [
        value
        for value in (
            _battery_percent(device.value("doorBattery", _BATTERY_LEVEL_FIELD)),
            _battery_percent(device.value("catEyeBattery", _BATTERY_LEVEL_FIELD)),
            _battery_percent(device.value(_BATTERY_SID, _LITHIUM_BATTERY_FIELD)),
            _battery_percent(device.value(_BATTERY_SID, _DRY_BATTERY_FIELD)),
        )
        if value is not None
    ]
    return min(levels) if levels else None


def _available(device: DeviceContext) -> bool:
    """Keep entities usable while the lock sleeps, catch a genuinely dead lock.

    ``networkConnectState.state`` is authoritative whenever the device reports
    it: 2 = online and 1 = sleeping both stay available, only an explicit 0
    (离线) marks the entities unavailable.

    The sibling locks never report that service at all (the KW5J notes record
    zero occurrences on a live install), so a missing reading falls back to
    the battery/silence heuristic: unavailable only when a battery is below
    5% *and* nothing has been reported for more than 24 hours.  Unknown
    battery or unknown age stays available -- hiding a working lock behind an
    unavailable entity is worse than showing a stale value.
    """

    state = _number(device.value(_NET_STATE_SID, _NET_STATE_FIELD))
    if state is not None:
        return state in _NET_AVAILABLE_STATES

    battery = _lowest_battery(device)
    if battery is None or battery >= _LOW_BATTERY_THRESHOLD:
        return True
    age_hours = _newest_report_age_hours(device)
    return age_hours is None or age_hours <= _STALE_HOURS


# =============================================================================
# Per-device adapter state
# =============================================================================


def _device_state(
    context: DeviceContext,
    name: str,
    factory: Callable[[], Any],
) -> Any:
    """Return this device's copy of one adapter-private object, built once.

    ``entity_specs`` is a plain property, not a cache, and setup is forwarded to
    every entry in ``const.PLATFORMS`` (16 of them) -- so ``entities()`` runs
    once per platform.  Specs may be rebuilt freely; these two objects may not:

    * the latched event record, which 门锁事件 writes and 最近门锁事件 -- built by
      a different platform -- reads back;
    * the latched readers below, which would otherwise register a fresh push
      listener on every build.

    Kept on the context (a plain class, no ``__slots__``) so it dies with the
    device; the ``_kw5l_`` prefix keeps the name clear of the framework's.
    """

    key = f"_kw5l_{name}"
    cached = getattr(context, key, None)
    if cached is None:
        cached = factory()
        setattr(context, key, cached)
    return cached


# =============================================================================
# Lock state readers
# =============================================================================


def _status_reader() -> Callable[[DeviceContext], int | float | None]:
    """Return a reader that keeps the last *declared* lockStatus value.

    ``lockStatus/status`` is what every state entity reads, and the firmware can
    report a transitional value the Profile does not declare (the KW02 family
    does).  Holding the last declared value keeps 门锁状态 / 门 / 反锁 /
    门未关异常上锁 describing the same moment instead of blanking them out, and
    ``_device_state`` makes all four share one latch -- they sit on two platforms
    and would otherwise hold a separate copy each.
    """

    cache: dict[str, Any] = {"status": None}

    def read(device: DeviceContext) -> Any:
        status = _number(device.value(_LOCK_STATUS_SID, _LOCK_STATUS_FIELD))
        if status in _DECLARED_STATUSES:
            cache["status"] = status
        return cache["status"]

    return read


def _alarm_is_stale(device: DeviceContext) -> bool:
    """Whether a latched ``lockAlarm`` reading has aged out.

    The cloud raises such a value once and never sends the cleared reading.
    An unparsable timestamp is not evidence of staleness, so it keeps the
    value.  Past the window the reading must stop describing the present --
    otherwise a replaced battery's low-power alarm would stay on forever.
    """

    when = device.service_updated_at(_LOCK_ALARM_SID)
    if when is None:
        return False
    return datetime.now(timezone.utc) - when > _ALARM_PULSE_WINDOW


# =============================================================================
# Event decoding
# =============================================================================


def _parse_payload(value: Any) -> Mapping[str, Any]:
    """Unpack the nested JSON some revisions deliver inside ``eventData``."""

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


def _event_record(device: DeviceContext) -> Mapping[str, Any]:
    """Return the union of both event slots, for classification only.

    ``event`` and ``eventData`` are **independent service slots**, not two
    halves of one record: a live capture showed ``event`` holding a motion
    detection (``et`` 09-28) while ``eventData`` still held an operation from
    eight days later (``et`` 10-06).  Merging them into "one record and
    preferring the richer side" therefore mixed two different occurrences.

    This union is still the right input for :func:`_event_kind` -- the cat-eye
    record needs ``aid`` from one slot and ``up`` from the other -- but the
    unlock readers use :func:`_unlock_candidate`, which keeps the slots apart.
    """

    record: dict[str, Any] = dict(device.service_state(_EVENT_SID))
    nested = dict(
        _parse_payload(device.value(_EVENT_DATA_SID, _EVENT_DATA_PAYLOAD_FIELD))
    )
    nested.update(
        {
            key: value
            for key, value in device.service_state(_EVENT_DATA_SID).items()
            if key != _EVENT_DATA_PAYLOAD_FIELD
        }
    )
    nested.update(record)
    return nested


def _carries_motion_marker(record: Mapping[str, Any]) -> bool:
    aid = record.get(_AID_KEY)
    return isinstance(aid, str) and _MOTION_MARKER in aid.upper()


def _slot_operation(slot: Mapping[str, Any]) -> int | float | None:
    """Read the operation code out of one event slot, if that slot is the source.

    A slot qualifies when it carries its own operation code *and* its own
    occurrence timestamp or identifier: a stale slot without either cannot be
    attributed to anything.
    """

    operation = _number(_first(slot, _OPERATION_KEYS))
    if operation is None:
        return None
    if _first(slot, _TIME_KEYS) is None and _first(slot, _IDENTIFIER_KEYS) is None:
        return None
    return operation


def _slot_timestamp(slot: Mapping[str, Any]) -> str | None:
    value = _first(slot, _TIME_KEYS)
    return value if isinstance(value, str) else None


@dataclass
class _LastEvent:
    """Adapter-lifetime record of the most recent classified event.

    The event entity fires and forgets, so a press can be missed by an
    automation that was added afterwards.  Keeping the last classification here
    (and exposing it on 最近门锁事件) makes "did a doorbell press arrive, and
    what did it classify as" answerable after the fact.
    """

    kind: str | None = None
    occurred_at: str | None = None
    operation: int | float | None = None
    record_type: int | float | None = None
    identifier: str | None = None
    identity: str | None = None
    fields: Mapping[str, Any] | None = None
    at: datetime | None = None


def _note_last_event(
    last: _LastEvent,
    kind: str,
    record: Mapping[str, Any],
    identity: str | None = None,
) -> None:
    last.kind = kind
    last.occurred_at = _first(record, _TIME_KEYS)
    last.operation = _number(_first(record, _OPERATION_KEYS))
    last.record_type = _number(_first(record, _RECORD_TYPE_KEYS))
    identifier = _first(record, _IDENTIFIER_KEYS)
    last.identifier = str(identifier) if identifier is not None else None
    last.identity = identity
    last.at = datetime.now(timezone.utc)
    # Latched separately from the current slots: the slot an event arrived in is
    # overwritten by the next operation (typically the auto-relock seconds
    # later), so reading them back later describes a *different* occurrence.
    last.fields = {key: record[key] for key in _DIAGNOSTIC_KEYS if key in record}


def _slot_identifiers(slot: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(slot.get(key) for key in _IDENTIFIER_KEYS)


def _newest_event_slot(device: DeviceContext) -> tuple[str, Mapping[str, Any]]:
    """Return ``(sid, fields)`` of whichever event slot the lock updated last.

    ``event`` and ``eventData`` are independent slots and either may carry the
    newest occurrence.  A live capture left ``event`` holding a cat-eye motion
    from eight days earlier while ``eventData`` received the unlock, so a fixed
    preference for one slot made 最近门锁事件 keep showing the old record while
    the sensors that read the unlock directly were correct.

    Their own ``et`` decides when both carry one; otherwise the service-level
    report time does.  An unparsable ``et`` counts as "no timestamp" rather than
    as epoch 0, so a good stamp always beats a broken one.
    """

    slots = {
        _EVENT_SID: device.service_state(_EVENT_SID),
        _EVENT_DATA_SID: {
            **dict(device.service_state(_EVENT_DATA_SID)),
            **_parse_payload(
                device.value(_EVENT_DATA_SID, _EVENT_DATA_PAYLOAD_FIELD)
            ),
        },
    }
    # Equal occurrence *and* same identity means one event seen on both
    # transports: the union describes it best and neither slot is "wrong".
    occurrence = {sid: _parse_stamp(_slot_timestamp(slot)) for sid, slot in slots.items()}
    if (
        occurrence[_EVENT_SID] is not None
        and occurrence[_EVENT_SID] == occurrence[_EVENT_DATA_SID]
        and _slot_identifiers(slots[_EVENT_SID])
        == _slot_identifiers(slots[_EVENT_DATA_SID])
    ):
        return _EVENT_SID, _event_record(device)

    def order(sid: str):
        when = occurrence[sid]
        if when is not None:
            return (1, when)
        reported = device.service_updated_at(sid)
        if reported is not None:
            return (1, reported)
        return (0, datetime.min.replace(tzinfo=timezone.utc))

    newest = max(slots, key=order)
    if order(newest)[0] == 0:
        # Neither slot is attributable: the union is what classification wants.
        return _EVENT_SID, _event_record(device)
    return newest, slots[newest]


def _newest_event_record(device: DeviceContext) -> Mapping[str, Any]:
    return _newest_event_slot(device)[1]


def _unlock_in_slot(slot: Mapping[str, Any]) -> tuple[Any, str | None] | None:
    """Return ``(operation, stamp)`` when this slot reports a genuine unlock.

    A slot qualifies only when it carries its own operation code together with
    its own occurrence stamp or identifier -- a stale slot without either cannot
    be attributed to anything.  Codes known to mean something else (doorbell,
    arming, relock bookkeeping, the cat-eye motion marker) never qualify; that
    is what keeps a motion or door-close record from blanking the last unlock.
    """

    operation = _slot_operation(slot)
    # No separate _UNKNOWN_BOOKKEEPING check: _looks_like_unlock already rejects
    # every code in _KNOWN_NON_UNLOCK_OPERATIONS, of which that set is a subset.
    if operation is None or not _looks_like_unlock(operation):
        return None
    return operation, _slot_timestamp(slot)


def _unlock_slots(device: DeviceContext) -> tuple[Mapping[str, Any], ...]:
    """Both event transports, with ``eventData``'s nested JSON flattened in."""

    return (
        device.service_state(_EVENT_SID),
        {
            **dict(device.service_state(_EVENT_DATA_SID)),
            **_parse_payload(
                device.value(_EVENT_DATA_SID, _EVENT_DATA_PAYLOAD_FIELD)
            ),
        },
    )


def _unlock_is_stale(device: DeviceContext, occurred_at: str | None) -> bool:
    """Whether a stored unlock should stop being reported as the latest one.

    Only a *clearly* later door report retires it.  The threshold is minutes,
    not seconds, because this lock re-locks by itself right after an unlock (a
    live capture: unlock at 23:43:30, relock at 23:43:37), and an earlier
    revision with a seconds-scale threshold hid a perfectly current unlock
    7 seconds after it happened.

    An unlock with no stamp is not stale: the snapshot path often has none, and
    dropping a real unlock for lack of a timestamp would be worse than showing
    it.  Also see :func:`_unlock_superseded`, which reports the raw fact
    without acting on it.
    """

    occurred = _parse_stamp(occurred_at)
    if occurred is None:
        return False
    status_at = _lock_status_reported_at(device) or device.service_updated_at(
        _LOCK_STATUS_SID
    )
    if status_at is not None and status_at - occurred > _UNLOCK_SUPERSEDE_AFTER:
        return True
    return datetime.now(timezone.utc) - occurred > _UNLOCK_MAX_AGE


def _unlock_superseded(device: DeviceContext, occurred_at: str | None) -> bool:
    """Whether *any* later door report exists for this unlock (informational)."""

    occurred = _parse_stamp(occurred_at)
    if occurred is None:
        return False
    status_at = _lock_status_reported_at(device) or device.service_updated_at(
        _LOCK_STATUS_SID
    )
    if status_at is None:
        return False
    return status_at > occurred


def _lock_status_reported_at(device: DeviceContext) -> datetime | None:
    """Return the lock's own ``lockStatus.updateTime`` as an aware datetime.

    This is the device's own statement of when the status changed, so it beats
    the transport stamp when the two disagree.
    """

    value = device.value(_LOCK_STATUS_SID, _LOCK_STATUS_TIME_FIELD)
    return _parse_stamp(value)


def _event_kind(
    record: Mapping[str, Any],
    door_event_type: Any = None,
) -> str | None:
    """Classify an event record into one of ``_EVENT_TYPES``.

    Order matters.  The motion copy is recognised by its ``aid`` token and is
    checked first; an alarm is recognised next (an alarm push carries no
    operation); an unknown operation with no user name is bookkeeping that
    must not surface as an unlock.  Any other operation is still reported --
    as ``record`` if it is credential/arming bookkeeping rather than a bolt
    operation -- because silently dropping a lock event is worse than firing
    one with a generic label.

    ``door_event_type`` is the ``doorEvent`` service's own classification
    (0 = opening, 1 = locking) and is used only when the operation slot is
    empty, since its ``event`` code space is undocumented.
    """

    # Order matters, and doorbell codes come first.
    #
    # Every cat-eye record from this lock carries an ``...MOTION_DETECTION...``
    # aid, doorbell presses included: the token identifies the *camera*, not the
    # event.  A doorbell press was confirmed on the vendor App for records whose
    # ``up`` is 22 (the Profile's 门铃响铃) with no motion detection logged, so
    # the operation code decides and the token alone never does.  The token is
    # consulted only as a last resort, after every known code has been tried --
    # putting it earlier would report an unlock carrying the same token as
    # motion.
    operation = _number(_first(record, _OPERATION_KEYS))
    if operation in _DOORBELL_OPERATIONS:
        return "doorbell"
    alarm = _number(_first(record, _ALARM_KEYS))
    if alarm is not None and alarm >= 1:
        return "alarm"
    if operation == _OPERATION_RELOCK:
        return "lock"
    if _unlock_direction(operation) is not None:
        return "unlock"
    if operation is not None:
        if operation in _ARM_OPERATIONS:
            return "arm"
        if operation in _DISARM_OPERATIONS:
            return "disarm"
        if operation in _CALL_OPERATIONS:
            return "call"
        if operation in _UNKNOWN_BOOKKEEPING:
            # Auto-relock bookkeeping: firing an event for every re-lock would
            # bury the events an automation cares about.
            return None
        user = _first(record, _USER_KEYS)
        if isinstance(user, str) and user.strip():
            # A credential unlock whose operation code this firmware left
            # unlabelled: the user name is what identifies it as an unlock.
            return "unlock"
        if operation in _RECORD_OPERATIONS:
            return "record"
        if _carries_motion_marker(record):
            # An operation code this adapter cannot label but which came from the
            # cat-eye: report it as motion rather than as generic bookkeeping.
            # Note this only applies to *unrecognised* codes -- putting the token
            # check earlier would relabel a known unlock as motion, which is what
            # a sweep over every Profile code caught.
            return "motion"
        # Anything else with an operation code and no user name is bookkeeping.
        return "record"
    user = _first(record, _USER_KEYS)
    if isinstance(user, str) and user.strip():
        return "unlock"
    if _carries_motion_marker(record):
        # Nothing in the operation slots but a cat-eye token: the camera is the
        # only remaining explanation.
        return "motion"
    # Nothing in the operation slots: fall back to the doorEvent classification.
    door_type = _number(door_event_type)
    if door_type == _DOOR_EVENT_TYPE_OPEN:
        return "unlock"
    if door_type == _DOOR_EVENT_TYPE_LOCK:
        return "lock"
    return None


def _lock_event_decoder(
    device: DeviceContext,
    sid: str,
    data: Mapping[str, Any],
    timestamp: str | None,
    last_event: _LastEvent | None = None,
) -> list[tuple[str, Mapping[str, Any]]]:
    """Fire one Home Assistant event per accepted lock event push.

    The lock pushes each operation once and never sends a cleared value, so
    the state entities can only describe *what happened last*.  This decoder
    supplies the other half, so an automation runs on every unlock rather than
    only on the first one.
    """

    if sid not in (_EVENT_SID, _EVENT_DATA_SID):
        return []

    current: dict[str, Any] = dict(data)
    if sid == _EVENT_DATA_SID:
        current.pop(_EVENT_DATA_PAYLOAD_FIELD, None)
        current.update(_parse_payload(data.get(_EVENT_DATA_PAYLOAD_FIELD)))
    else:
        # The other service only fills in what this push lacks, and never its
        # identity (eid/aid/id/et).
        for key, value in device.service_state(_EVENT_DATA_SID).items():
            if key == _EVENT_DATA_PAYLOAD_FIELD:
                continue
            current.setdefault(key, value)
        for key, value in _parse_payload(
            device.value(_EVENT_DATA_SID, _EVENT_DATA_PAYLOAD_FIELD)
        ).items():
            if key in _IDENTIFIER_KEYS or key == "et":
                continue
            current.setdefault(key, value)

    kind = _event_kind(
        current,
        device.value(_DOOR_EVENT_SID, _DOOR_EVENT_TYPE_FIELD),
    )
    if kind is None:
        # Auto-relock bookkeeping and pushes with nothing to say produce no
        # event (see _event_kind).
        return []

    # One occurrence arrives on both transports; fire it once.
    identity = None
    if last_event is not None:
        identity = _event_identity(device, sid, data)
        if identity is not None and identity == last_event.identity:
            return []

    profile = device.profile or {}
    operation = _number(_first(current, _OPERATION_KEYS))
    alarm_code = _number(_first(current, _ALARM_KEYS))
    payload: dict[str, Any] = {
        "event_id": _first(current, _IDENTIFIER_KEYS),
        "user": _first(current, _USER_KEYS),
        "clock": _first(current, ("cl",)),
        "occurred_at": _first(current, _TIME_KEYS) or timestamp,
        "method": _operation_label(
            _field(profile, _EVENT_SID, "userOperation"), operation
        ),
        "direction": _unlock_direction(operation),
    }
    if kind not in {"unlock", "lock"}:
        # For every other class the operation code *is* the content, so the
        # event carries the raw code as well as its Profile label.
        payload["operation"] = operation
    if kind == "alarm":
        payload["alarm"] = _enum_label(
            _field(profile, _EVENT_SID, "doorAlarmState"), alarm_code
        )
    if last_event is not None:
        _note_last_event(last_event, kind, current, identity)
    return [(kind, {key: value for key, value in payload.items() if value is not None})]


def _event_identity(
    device: DeviceContext,
    sid: str,
    data: Mapping[str, Any],
) -> str | None:
    """Return the occurrence identity of one push, or None when it has none.

    The lock reports a single occurrence on two services: ``event`` carries the
    user-facing fields while ``eventData`` carries a JSON copy of the same
    record (same ``eid``, same ``et``, same ``up``).  Both are accepted pushes,
    so the decoder would fire twice per occurrence.  The identity therefore
    includes the operation code and record type as well as ``eid``/``et``: a
    different operation is a different occurrence even if the identifier is
    reused, and an identical pair is the same occurrence on two transports.

    Returns None when the push carries no identifier at all, in which case
    nothing is suppressed.
    """

    pool: dict[str, Any] = dict(data)
    if sid == _EVENT_DATA_SID:
        pool.pop(_EVENT_DATA_PAYLOAD_FIELD, None)
        pool.update(_parse_payload(data.get(_EVENT_DATA_PAYLOAD_FIELD)))
    identifier = _first(pool, _IDENTIFIER_KEYS)
    if identifier is None:
        return None
    parts = [
        str(identifier),
        str(_first(pool, _TIME_KEYS)),
        str(_number(_first(pool, _OPERATION_KEYS))),
        str(_number(_first(pool, _RECORD_TYPE_KEYS))),
    ]
    return "|".join(parts)


def _looks_like_unlock(operation: Any) -> bool:
    """Whether an operation code is an unlock this adapter cannot label yet.

    A code outside every known table is still an operation the lock reported as
    a credential use when it carries no alarm and is not one of the codes known
    to mean something else (doorbell, arming, relock bookkeeping).  Treating it
    as an unlock matters: it makes the raw code visible on 最近开门方式 instead
    of a bare "未知", which is the only way to extend the tables from evidence.
    """

    number = _number(operation)
    if number is None:
        return False
    if number in _KNOWN_NON_UNLOCK_OPERATIONS:
        return False
    return True


def _unlock_reader(device: DeviceContext) -> Callable[[DeviceContext], Any]:
    """Return a reader that keeps the latest *unlock* the lock reported.

    The unlock is **latched**, because the slot it arrived in is overwritten by
    the very next operation: a live capture showed the unlock (``up`` 2 at
    23:43:30) replaced 7 seconds later by the automatic relock (``up`` 38), and a
    reader that only inspected the current slot lost the unlock entirely.

    The latch is refreshed both when it is read and when the device pushes
    anything -- the push listener is registered below, and runs once per device
    because callers build the reader through ``_device_state``.  It is retired
    when the door reports a state clearly later than the unlock (minutes, not
    seconds -- this lock re-locks by itself right after unlocking) or when the
    unlock itself is a day old.
    """

    cache: dict[str, Any] = {"operation": None, "at": None}

    def refresh(device: DeviceContext) -> None:
        for slot in _unlock_slots(device):
            found = _unlock_in_slot(slot)
            if found is None:
                continue
            operation, stamp = found
            previous = _parse_stamp(cache["at"])
            candidate = _parse_stamp(stamp)
            if (
                cache["operation"] is None
                or candidate is None
                or previous is None
                or candidate >= previous
            ):
                cache["operation"] = operation
                cache["at"] = stamp

    def read(device: DeviceContext) -> Any:
        refresh(device)
        if cache["operation"] is None:
            return None
        if _unlock_is_stale(device, cache["at"]):
            return None
        return cache["operation"]

    # Latch on every push, so a slot overwritten between reads is not lost.
    # Safe to register here: _device_state builds this once per device.
    device.add_state_listener(lambda: refresh(device))
    return read


# =============================================================================
# Entity builders
# =============================================================================


def _switch_spec(
    sid: str,
    characteristic: str,
    key: str,
    name: str,
    *,
    writable: bool,
) -> EntitySpec:
    def state(device: DeviceContext) -> Mapping[str, Any]:
        value = _number(device.value(sid, characteristic))
        return {"is_on": None if value is None else bool(value)}

    actions: dict[str, Any] = {}
    if writable:

        def make_action(value: int):
            async def action(context: DeviceContext, data: Mapping[str, Any]) -> None:
                del data
                _require_writable(context.profile, sid, characteristic)
                await context.async_send_service(sid, {characteristic: value})

            return action

        actions = {"turn_on": make_action(1), "turn_off": make_action(0)}

    metadata: dict[str, Any] = {}
    if not writable:
        # Read-only settings decide what the lock accepts, so they are
        # reported as binary sensors rather than controls.
        return EntitySpec(
            platform="binary_sensor",
            key=key,
            name=name,
            state=state,
            metadata={"entity_category": "diagnostic"},
            availability=_available,
        )

    # Only the cat-eye branch is reachable: the sole alarmEventSetting caller is
    # the read-only master switch, which returned above.
    if sid == _CAT_EYE_SETTING_SID:
        metadata["icon"] = "mdi:camera"

    return EntitySpec(
        platform="switch",
        key=key,
        name=name,
        state=state,
        metadata=metadata,
        actions=actions,
        availability=_available,
    )


def _enum_select_spec(
    profile: Mapping[str, Any],
    sid: str,
    characteristic: str,
    key: str,
    name: str,
) -> EntitySpec | None:
    options = _enum_options(_field(profile, sid, characteristic))
    if not options:
        # No Profile enum: do not invent a value space for a write.
        return None
    by_label = {label: value for label, value in options}
    by_value = {str(value): label for label, value in options}

    def state(device: DeviceContext) -> Mapping[str, Any]:
        value = _number(device.value(sid, characteristic))
        if value is None:
            return {"current_option": None}
        return {"current_option": by_value.get(str(value))}

    async def select_option(context: DeviceContext, data: Mapping[str, Any]) -> None:
        option = data.get("option")
        if option not in by_label:
            raise ValueError(f"unknown option for {characteristic}: {option!r}")
        await context.async_send_service(sid, {characteristic: by_label[option]})

    return EntitySpec(
        platform="select",
        key=key,
        name=name,
        state=state,
        metadata={"options": [label for label, _ in options]},
        actions={"select_option": select_option},
        availability=_available,
    )


def _text_spec(
    sid: str,
    characteristic: str,
    key: str,
    name: str,
    max_length: int,
) -> EntitySpec:
    def state(device: DeviceContext) -> Mapping[str, Any]:
        value = device.value(sid, characteristic)
        return {"native_value": value if isinstance(value, str) else None}

    async def set_value(context: DeviceContext, data: Mapping[str, Any]) -> None:
        value = data.get("value")
        if not isinstance(value, str) or not value:
            raise ValueError(f"{characteristic} requires a non-empty string")
        if len(value) > max_length:
            raise ValueError(
                f"{characteristic} accepts at most {max_length} characters"
            )
        await context.async_send_service(sid, {characteristic: value})

    return EntitySpec(
        platform="text",
        key=key,
        name=name,
        state=state,
        # No entity_category on purpose: these time fields belong on the same
        # board as the control that activates them (the 消息推送时间 selector,
        # or 夜间自动调低音量).  Every other configurable entity in this adapter is
        # uncategorised for the same reason.
        metadata={"min": 0, "max": max_length},
        actions={"set_value": set_value},
        availability=_available,
    )


def _time_window_specs(
    profile: Mapping[str, Any],
    sid: str,
) -> list[EntitySpec]:
    """Return the time-window text entities that belong to one service."""

    specs: list[EntitySpec] = []
    for window_sid, characteristic, key, name in _TIME_WINDOWS:
        if window_sid != sid:
            continue
        field = _field(profile, window_sid, characteristic)
        if field is None:
            continue
        declared = _number(field.get("maxLength"))
        maximum = int(declared) if declared else _TEXT_MAX_LENGTH
        specs.append(_text_spec(window_sid, characteristic, key, name, maximum))
    return specs


def _battery_spec(
    profile_field: str | None,
    manager_field: str,
    key: str,
    name: str,
) -> EntitySpec:
    def state(device: DeviceContext) -> Mapping[str, Any]:
        value = (
            _battery_percent(device.value(profile_field, _BATTERY_LEVEL_FIELD))
            if profile_field is not None
            else None
        )
        if value is None:
            value = _battery_percent(device.value(_BATTERY_SID, manager_field))
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
        availability=_available,
    )


def _roster_spec(sid: str, name: str, key: str, label: str) -> EntitySpec:
    def state(device: DeviceContext) -> Mapping[str, Any]:
        raw = device.value(sid, name)
        if not isinstance(raw, list):
            return {"native_value": None}
        return {"native_value": len(raw)}

    return EntitySpec(
        platform="sensor",
        key=key,
        name=label,
        state=state,
        metadata={"state_class": "measurement", "entity_category": "diagnostic"},
        availability=_available,
    )


# =============================================================================
# Adapter
# =============================================================================


class ProductKW5LAdapter:
    """HUAWEI SmartLock 2 Pro (KW5L / AGS-X20) entity and command choices."""

    prod_id = "KW5L"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None or not context.has_service(_LOCK_STATUS_SID):
            return ()

        read_status = _device_state(context, "status_reader", _status_reader)
        # No ``lock`` entity: HA always renders 上锁/解锁 buttons on it, and this
        # family refuses remote bolt commands (see the module docstring), so the
        # pair could only ever raise.  门锁状态 / 门 / 反锁 below carry the state.
        entities: list[EntitySpec] = []
        entities.extend(self._lock_status_entities(profile, read_status))
        entities.extend(self._battery_entities(context))
        entities.extend(self._network_entities(context))
        entities.extend(self._alarm_entities(profile))
        entities.extend(self._event_entities(profile, context))
        entities.extend(self._notification_entities(profile, context))
        entities.extend(self._cat_eye_entities(profile, context))
        entities.extend(self._security_entities(profile, context))
        entities.extend(self._volume_entities(profile, context))
        entities.extend(self._roster_entities(context))
        return tuple(entities)

    # -- lock state ---------------------------------------------------------

    def _lock_status_entities(
        self,
        profile: Mapping[str, Any],
        read_status: Callable[[DeviceContext], Any],
    ) -> list[EntitySpec]:
        field = _field(profile, _LOCK_STATUS_SID, _LOCK_STATUS_FIELD) or {}

        def status_state(device: DeviceContext) -> Mapping[str, Any]:
            value = read_status(device)
            if value is None:
                return {"native_value": None}
            return {"native_value": _enum_label(field, value) or str(value)}

        def door_state(device: DeviceContext) -> Mapping[str, Any]:
            status = read_status(device)
            if status in _DOOR_LEAF_OPEN:
                return {"is_on": True}
            if status in _DOOR_LEAF_CLOSED:
                return {"is_on": False}
            return {"is_on": None}

        return [
            EntitySpec(
                platform="sensor",
                key="lock_status",
                name="门锁状态",
                state=status_state,
                availability=_available,
            ),
            EntitySpec(
                platform="binary_sensor",
                key="door",
                name="门",
                state=door_state,
                metadata={"device_class": "door"},
                availability=_available,
            ),
            EntitySpec(
                platform="binary_sensor",
                key="deadlock",
                name="反锁",
                state=lambda device: {
                    "is_on": read_status(device) == _STATUS_DEADLOCK
                },
                availability=_available,
            ),
            EntitySpec(
                platform="binary_sensor",
                key="door_ajar_locked",
                name="门未关异常上锁",
                state=lambda device: {
                    "is_on": read_status(device) == _STATUS_DOOR_AJAR_LOCKED
                },
                metadata={"device_class": "problem"},
                availability=_available,
            ),
        ]

    # -- batteries ----------------------------------------------------------

    def _battery_entities(self, context: DeviceContext) -> list[EntitySpec]:
        entities: list[EntitySpec] = []
        if context.has_service("doorBattery"):
            entities.append(
                _battery_spec(
                    "doorBattery", _LITHIUM_BATTERY_FIELD, "door_battery", "门锁电池"
                )
            )
        elif context.has_service(_BATTERY_SID):
            entities.append(
                _battery_spec(
                    None, _LITHIUM_BATTERY_FIELD, "door_battery", "门锁电池"
                )
            )
        if context.has_service("catEyeBattery"):
            entities.append(
                _battery_spec(
                    "catEyeBattery", _DRY_BATTERY_FIELD, "cat_eye_battery", "猫眼电池"
                )
            )
        elif context.has_service(_BATTERY_SID):
            entities.append(
                _battery_spec(None, _DRY_BATTERY_FIELD, "cat_eye_battery", "猫眼电池")
            )
        if entities:
            entities.append(self._low_battery_spec())
        return entities

    def _low_battery_spec(self) -> EntitySpec:
        """Low battery as one boolean, from either source this family uses.

        ``lockAlarm/alarm == 2`` is the Profile's own low-power alarm;
        ``batteryManager.lpmStatus`` is what the sibling locks report instead;
        and a level at or below 10% is a reading that speaks for itself.  The
        three are OR'd, and an unreported source never claims "fine".
        """

        def state(device: DeviceContext) -> Mapping[str, Any]:
            alarm = _number(device.value(_LOCK_ALARM_SID, _LOCK_ALARM_FIELD))
            if alarm == _ALARM_LOW_BATTERY and not _alarm_is_stale(device):
                return {"is_on": True}
            lpm = _number(device.value(_BATTERY_SID, _BATTERY_LPM_FIELD))
            if lpm == _LPM_ACTIVE:
                return {"is_on": True}
            level = _lowest_battery(device)
            if level is not None and level <= _LOW_BATTERY_PERCENT:
                return {"is_on": True}
            if alarm is None and lpm is None and level is None:
                return {"is_on": None}
            return {"is_on": False}

        return EntitySpec(
            platform="binary_sensor",
            key="low_battery",
            name="低电量告警",
            state=state,
            metadata={"device_class": "battery"},
            availability=_available,
        )

    # -- network ------------------------------------------------------------

    def _network_entities(self, context: DeviceContext) -> list[EntitySpec]:
        entities: list[EntitySpec] = []
        if context.has_service(_NET_STATE_SID):
            field = _field(context.profile or {}, _NET_STATE_SID, _NET_STATE_FIELD)

            def network_state(device: DeviceContext) -> Mapping[str, Any]:
                value = _number(device.value(_NET_STATE_SID, _NET_STATE_FIELD))
                if value is None:
                    return {"native_value": None}
                return {"native_value": _enum_label(field, value) or str(value)}

            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="network_state",
                    name="网络状态",
                    state=network_state,
                    metadata={"entity_category": "diagnostic"},
                    availability=_available,
                )
            )
        if context.has_service(_NET_INFO_SID):
            entities.extend(
                (
                    EntitySpec(
                        platform="sensor",
                        key="wifi_signal",
                        name="网络信号强度",
                        state=lambda device: {
                            "native_value": _number(
                                device.value(_NET_INFO_SID, "intensity")
                            )
                        },
                        metadata={
                            "unit": "%",
                            "state_class": "measurement",
                            "entity_category": "diagnostic",
                        },
                        availability=_available,
                    ),
                    EntitySpec(
                        platform="sensor",
                        key="wifi_rssi",
                        name="WiFi RSSI",
                        state=lambda device: {
                            "native_value": _number(
                                device.value(_NET_INFO_SID, "RSSI")
                            )
                        },
                        metadata={
                            "unit": "dBm",
                            "device_class": "signal_strength",
                            "state_class": "measurement",
                            "entity_category": "diagnostic",
                        },
                        availability=_available,
                    ),
                    EntitySpec(
                        platform="sensor",
                        key="ip_address",
                        name="IP 地址",
                        state=lambda device: {
                            "native_value": _string_value(
                                device.value(_NET_INFO_SID, "IP")
                            )
                        },
                        metadata={
                            "icon": "mdi:ip-network",
                            "entity_category": "diagnostic",
                        },
                        availability=_available,
                    ),
                )
            )
        return entities

    # -- firmware and alarms ------------------------------------------------

    def _alarm_entities(self, profile: Mapping[str, Any]) -> list[EntitySpec]:
        alarm_field = _field(profile, _LOCK_ALARM_SID, _LOCK_ALARM_FIELD) or {}
        door_alarm_field = _field(profile, _EVENT_SID, "doorAlarmState") or {}

        def alarm_state(device: DeviceContext) -> Mapping[str, Any]:
            value = _number(device.value(_LOCK_ALARM_SID, _LOCK_ALARM_FIELD))
            if value is None:
                return {"native_value": None}
            if value < 0:
                return {"native_value": _NO_ALARM_TEXT}
            return {"native_value": _enum_label(alarm_field, value) or str(value)}

        def event_alarm_state(device: DeviceContext) -> Mapping[str, Any]:
            value = _number(_first(_event_record(device), _ALARM_KEYS))
            if value is None:
                return {"native_value": None}
            if value < 1:
                return {"native_value": _NO_ALARM_TEXT}
            return {
                "native_value": _enum_label(door_alarm_field, value) or str(value)
            }

        entities: list[EntitySpec] = [
            EntitySpec(
                platform="sensor",
                key="lock_alarm",
                name="门锁告警",
                state=alarm_state,
                metadata={"icon": "mdi:alert-outline"},
                availability=_available,
            ),
            EntitySpec(
                platform="sensor",
                key="last_door_alarm",
                name="最近门锁告警",
                state=event_alarm_state,
                metadata={"icon": "mdi:alarm-light"},
                availability=_available,
            ),
        ]

        if _field(profile, _UPDATE_SID, "version") is not None:

            def firmware_version(device: DeviceContext) -> Mapping[str, Any]:
                # The Profile names it ``version``; the wire report observed on
                # this family uses ``currentVersion``.  Both are read, and the
                # OTA *action* is deliberately never written (see module
                # docstring).
                value = _string_value(device.value(_UPDATE_SID, "version"))
                if value is None:
                    value = _string_value(device.value(_UPDATE_SID, "currentVersion"))
                return {"native_value": value}

            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="firmware_version",
                    name="固件版本",
                    state=firmware_version,
                    metadata={"entity_category": "diagnostic"},
                    availability=_available,
                )
            )
        return entities

    # -- events -------------------------------------------------------------

    def _event_entities(
        self,
        profile: Mapping[str, Any],
        context: DeviceContext,
    ) -> list[EntitySpec]:
        if not (
            context.has_service(_EVENT_SID) or context.has_service(_EVENT_DATA_SID)
        ):
            return []
        # Shared across every platform's build -- see _device_state.
        read_unlock = _device_state(
            context, "unlock_reader", lambda: _unlock_reader(context)
        )
        last_event = _device_state(context, "last_event", _LastEvent)
        operation_field = _field(profile, _EVENT_SID, "userOperation") or {}

        def decoder(device, sid, data, timestamp):
            return _lock_event_decoder(device, sid, data, timestamp, last_event)

        def fired_attributes(device: DeviceContext) -> Mapping[str, Any]:
            """What the event entity last fired, so a press can be verified later.

            Taken from the latched copy, not from the live slots: the slot an
            event arrived in is overwritten seconds later by the next operation.
            ``doorEvent`` is included because a doorbell may well arrive there.
            """

            del device
            return {
                "last_fired_event_type": last_event.kind,
                "last_fired_operation": last_event.operation,
                "last_fired_record_type": last_event.record_type,
                "last_fired_event_id": last_event.identifier,
                "last_fired_occurred_at": last_event.occurred_at,
                "last_fired_at": (
                    last_event.at.isoformat() if last_event.at is not None else None
                ),
                "last_fired_fields": dict(last_event.fields or {}),
                "last_fired_door_event": dict(
                    context.service_state(_DOOR_EVENT_SID)
                ),
            }

        def direction_state(device: DeviceContext) -> Mapping[str, Any]:
            found = None
            for slot in _unlock_slots(device):
                found = _unlock_in_slot(slot) or found
            stamp = found[1] if found else None
            # Read the latch once: each call re-scans both slots and re-parses
            # their timestamps, and the sensor platform reads state() twice.
            operation = read_unlock(device)
            return {
                "native_value": _unlock_direction(operation),
                # The raw code is what identifies a model-specific operation: if
                # this shows a number while native_value is None, the code is
                # simply not in the tables yet.  ``unlock_slot`` shows what the
                # current slot holds and whether it was judged too old.
                "extra_state_attributes": {
                    "raw_user_operation": operation,
                    "unlock_slot": {
                        "operation": found[0] if found else None,
                        "occurred_at": stamp,
                        "stale": _unlock_is_stale(device, stamp),
                        "superseded": _unlock_superseded(device, stamp),
                    },
                },
            }

        def method_state(device: DeviceContext) -> Mapping[str, Any]:
            value = _number(read_unlock(device))
            if value is None:
                return {
                    "native_value": None,
                    "extra_state_attributes": {"raw_user_operation": None},
                }
            return {
                "native_value": _operation_label(operation_field, value) or str(value),
                "extra_state_attributes": {"raw_user_operation": value},
            }

        def raw_record(device: DeviceContext) -> Mapping[str, Any]:
            """Exactly what the lock sent for the last event.

            Exposed as attributes of ``最近门锁事件`` (no extra entity, so the
            verified entity count is unchanged).  ``开门方向`` /
            ``最近开门方式`` can only label an operation code this adapter knows;
            if the lock publishes it under a field name outside
            ``_OPERATION_KEYS``, both read 未知 while the event still fires --
            and these attributes show which field it actually used, so the
            mapping can be corrected from evidence instead of guesswork.

            Only envelope fields describing the operation, the alarm, the user
            and the identity are echoed; never credential material.
            """

            event = device.service_state(_EVENT_SID)
            event_data = device.service_state(_EVENT_DATA_SID)
            parsed = _parse_payload(event_data.get(_EVENT_DATA_PAYLOAD_FIELD))
            event_data_flat = {**dict(event_data), **parsed}
            chosen_sid, chosen = _newest_event_slot(device)

            def fields_of(slot: Mapping[str, Any]) -> dict[str, Any]:
                return {key: slot[key] for key in _DIAGNOSTIC_KEYS if key in slot}

            # Each slot is reported on its own so the values can be attributed
            # to the transport that carried them -- echoing one merged view
            # mixed a stale `aid` from the other slot into the chosen event and
            # made the diagnostic itself misleading.
            return {
                "event_fields": fields_of(chosen),
                "event_slot_used": chosen_sid,
                "event_fields_slot": fields_of(event),
                "event_fields_eventData": fields_of(event_data_flat),
                "event_at": _slot_timestamp(event),
                "eventData_at": _slot_timestamp(event_data_flat),
                "event_keys": sorted(event),
                "eventData_keys": sorted(
                    key
                    for key in event_data
                    if key != _EVENT_DATA_PAYLOAD_FIELD
                ),
                "eventData_parsed": dict(parsed),
                **fired_attributes(device),
            }

        def last_event_state(device: DeviceContext) -> Mapping[str, Any]:
            # The summary describes the newest occurrence, which may live in
            # either slot; classification still uses the union of both.
            record = _newest_event_record(device)
            door_type = device.value(_DOOR_EVENT_SID, _DOOR_EVENT_TYPE_FIELD)
            kind = _event_kind(record, door_type)
            if kind is None:
                kind = _event_kind(_event_record(device), door_type)
            if kind is None:
                return {
                    "native_value": None,
                    "extra_state_attributes": raw_record(device),
                }
            operation = _number(_first(record, _OPERATION_KEYS))
            # For anything that is not a credential use the operation code means
            # something else (a cat-eye record carries a doorbell code), so the
            # class decides the wording and the label is only a refinement.
            if kind in ("unlock", "lock"):
                headline = _operation_label(operation_field, operation)
            else:
                headline = _EVENT_KIND_LABELS.get(kind)
                labelled = _operation_label(operation_field, operation)
                if kind in ("doorbell", "record") and labelled:
                    headline = labelled
            if headline is None and operation is not None:
                headline = f"事件({int(operation)})"
            parts = [headline]
            user = _first(record, _USER_KEYS)
            if isinstance(user, str) and user.strip():
                parts.append(user.strip())
            stamp = _format_stamp(_first(record, _TIME_KEYS))
            if stamp:
                parts.append(stamp)
            label = " · ".join(part for part in parts if part)
            return {
                "native_value": label or None,
                "extra_state_attributes": {
                    "event_kind": kind,
                    "user_operation": operation,
                    **raw_record(device),
                },
            }

        return [
            EntitySpec(
                platform="sensor",
                key="last_open_direction",
                name="开门方向",
                state=direction_state,
                metadata={"icon": "mdi:door-open"},
                availability=_available,
            ),
            EntitySpec(
                platform="sensor",
                key="last_open_method",
                name="最近开门方式",
                state=method_state,
                metadata={"icon": "mdi:key-variant"},
                availability=_available,
            ),
            EntitySpec(
                platform="sensor",
                key="last_event",
                name="最近门锁事件",
                state=last_event_state,
                metadata={"icon": "mdi:history"},
                availability=_available,
            ),
            EntitySpec(
                platform="event",
                key="lock_event",
                name="门锁事件",
                state=lambda device: {},
                metadata={
                    "event_types": list(_EVENT_TYPES),
                    "icon": "mdi:door-open",
                    # No device_class on purpose: Home Assistant's
                    # EventDeviceClass has no DOOR member, and event.py wraps
                    # the value in that enum, so setting "door" here would
                    # raise during platform setup and the entity would never
                    # be created (observed as event: 0 on a live install).
                },
                event_decoder=decoder,
                availability=_available,
            ),
        ]

    # -- notification settings ---------------------------------------------

    def _notification_entities(
        self,
        profile: Mapping[str, Any],
        context: DeviceContext,
    ) -> list[EntitySpec]:
        if not context.has_service(_ALARM_SETTING_SID):
            return []
        # No writable alert switches remain -- the App comparison removed every
        # one of them (see the module docstring).
        entities: list[EntitySpec] = []
        if _field(profile, _ALARM_SETTING_SID, _MESSAGE_PUSH_SWITCH) is not None:
            entities.append(
                _switch_spec(
                    _ALARM_SETTING_SID,
                    _MESSAGE_PUSH_SWITCH,
                    f"alarm_{_MESSAGE_PUSH_SWITCH}",
                    "消息推送总开关",
                    writable=False,
                )
            )
        # 消息推送时间 -- the selector that decides whether the window below applies.
        for sid, characteristic, key, name in _ENUM_SELECTS:
            if sid != _ALARM_SETTING_SID:
                continue
            spec = _enum_select_spec(profile, sid, characteristic, key, name)
            if spec is not None:
                entities.append(spec)
        # 消息推送开始/结束时间, shown next to the 消息推送时间 selector.
        entities.extend(_time_window_specs(profile, _ALARM_SETTING_SID))
        return entities

    # -- cat-eye settings ---------------------------------------------------

    def _cat_eye_entities(
        self,
        profile: Mapping[str, Any],
        context: DeviceContext,
    ) -> list[EntitySpec]:
        if not context.has_service(_CAT_EYE_SETTING_SID):
            return []
        entities = [
            _switch_spec(
                _CAT_EYE_SETTING_SID,
                characteristic,
                f"cateye_{characteristic}",
                label,
                writable=True,
            )
            for characteristic, label in _CAT_EYE_SWITCHES
            if _field(profile, _CAT_EYE_SETTING_SID, characteristic) is not None
        ]

        # No enum selects remain on this service: 逗留多久开始录像 and
        # 录像最大时长 were both dropped, and with them the temporary probe
        # that existed only to capture ``stayDuration``'s real values.
        return entities

    # -- security settings (read-only) --------------------------------------

    def _security_entities(
        self,
        profile: Mapping[str, Any],
        context: DeviceContext,
    ) -> list[EntitySpec]:
        """Report the admin-gated security switches without being able to set them.

        See decision 4 in the module docstring: writing ``securitySetting``
        requires carrying the admin credential in the command body, and these
        are exactly the settings that decide what the lock will accept.
        """

        if not context.has_service(_SECURITY_SETTING_SID):
            return []
        return [
            _switch_spec(
                _SECURITY_SETTING_SID,
                characteristic,
                f"security_{characteristic}",
                label,
                writable=False,
            )
            for characteristic, label in _SECURITY_SWITCHES
            if _field(profile, _SECURITY_SETTING_SID, characteristic) is not None
        ]

    # -- volume and ring ----------------------------------------------------

    def _volume_entities(
        self,
        profile: Mapping[str, Any],
        context: DeviceContext,
    ) -> list[EntitySpec]:
        if not context.has_service(_VOLUME_SETTING_SID):
            return []

        # 铃声音量 / 按键音量 / 语音音量, and 当前铃声 before them, were all
        # dropped: the App has no matching control for any of them.  Only night
        # mode and its window are written on this service now.
        entities: list[EntitySpec] = []
        if _field(profile, _VOLUME_SETTING_SID, "nightModeSwitch") is not None:
            entities.append(
                _switch_spec(
                    _VOLUME_SETTING_SID,
                    "nightModeSwitch",
                    "night_mode",
                    "夜间自动调低音量",
                    writable=True,
                )
            )

        # 夜间自动调低音量开始/结束时间.  The App presents these as part of the
        # night mode feature; they only apply while that switch is on, and the
        # shared name prefix is what sorts them next to it (see _TIME_WINDOWS).
        entities.extend(_time_window_specs(profile, _VOLUME_SETTING_SID))
        return entities

    # -- rosters (counts only) ----------------------------------------------

    def _roster_entities(self, context: DeviceContext) -> list[EntitySpec]:
        return [
            _roster_spec(sid, name, key, label)
            for sid, name, key, label in _ROSTERS
            if context.has_service(sid)
        ]


def _string_value(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


ADAPTER = ProductKW5LAdapter()
