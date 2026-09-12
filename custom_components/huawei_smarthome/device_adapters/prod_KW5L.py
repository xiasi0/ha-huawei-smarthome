"""Product adapter for Huawei SmartLock 2 Pro (KW5L).

华为智能门锁 2 Pro - 全功能接入 Home Assistant
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

# lockStatus/status 枚举值
_LOCK_STATUS_NOT_CLOSED = 1  # 门未关异常上锁
_LOCK_STATUS_UNLOCKED = 2    # 已开锁
_LOCK_STATUS_LOCKED = 3      # 已上锁
_LOCK_STATUS_DOOR_CLOSED = 4 # 已关门
_LOCK_STATUS_DEADLOCK = 6    # 已反锁

# networkConnectState/state 枚举值
_NET_STATE_OFFLINE = 0
_NET_STATE_SLEEPING = 1
_NET_STATE_ONLINE = 2

# lockAlarm/alarm 枚举值
_ALARM_FAULT = 1
_ALARM_LOW_BATTERY = 2
_ALARM_OFFLINE_LONG = 3

# event/userOperation 枚举值
_USER_OPS = {
    0: "指纹开锁",
    1: "密码开锁",
    2: "人脸开锁",
    3: "门卡开锁",
    4: "手表手环开锁",
    5: "华为钱包开锁",
    6: "临时密码开门",
    7: "物理钥匙开门",
    8: "添加密码",
    9: "删除密码",
    10: "添加指纹",
    11: "删除指纹",
    12: "添加人脸",
    13: "删除人脸",
    14: "添加门卡",
    15: "删除门卡",
    16: "添加手表手环",
    17: "删除手表手环",
    18: "添加钱包钥匙",
    19: "删除钱包钥匙",
    20: "添加用户",
    21: "删除用户",
    22: "门铃响铃",
    23: "编辑用户",
    24: "门内开锁",
    25: "反锁",
    26: "解除反锁",
    27: "开启布防",
    28: "解除布防",
    29: "敲门事件",
    30: "连续按门铃",
    31: "门内sensor检测靠近",
    32: "开始视频通话",
    33: "开始视频录制",
}

# event/doorAlarmState 枚举值
_DOOR_ALARM = {
    1: "门未关告警",
    2: "门虚掩告警",
    3: "门未锁故障告警",
    4: "低电告警",
    5: "网络质量差告警",
    6: "指纹连续错误告警",
    7: "密码连续错误告警",
    8: "人脸连续错误告警",
    9: "挟持告警",
    10: "布防告警",
    11: "可疑逗留",
    12: "被撬告警",
    13: "遮挡告警",
    14: "过爆告警",
    15: "长时间未开门",
}


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


def _enum_label(field: Mapping[str, Any] | None, value: Any) -> str | None:
    """Get the Chinese label for an enum value from the profile."""
    if field is None:
        return None
    for option in field.get("enumList", ()):
        if not isinstance(option, Mapping):
            continue
        if str(option.get("enumVal")) == str(value):
            return str(option.get("descCh") or option.get("enumVal"))
    return None


# =============================================================================
# Lock control actions
# =============================================================================

async def _lock_lock(context: DeviceContext, data: Mapping[str, Any]) -> None:
    """Lock the door (上锁)."""
    await context.async_send_service("lockStatus", {"status": _LOCK_STATUS_LOCKED})


async def _lock_unlock(context: DeviceContext, data: Mapping[str, Any]) -> None:
    """Unlock the door (开锁)."""
    await context.async_send_service("lockStatus", {"status": _LOCK_STATUS_UNLOCKED})


# =============================================================================
# Switch actions for alarm event settings
# =============================================================================

def _make_switch_action(sid: str, field_name: str):
    """Create a switch toggle action for alarmEventSetting."""
    async def _action(context: DeviceContext, data: Mapping[str, Any]) -> None:
        value = 1 if data.get("state") else 0
        await context.async_send_service(sid, {field_name: value})
    return _action


def _make_enum_action(sid: str, field_name: str, options: tuple[tuple[str, Any], ...]):
    """Create a select action for enum settings."""
    async def _action(context: DeviceContext, data: Mapping[str, Any]) -> None:
        option = data.get("option")
        for label, value in options:
            if label == option:
                await context.async_send_service(sid, {field_name: value})
                return
        raise ValueError(f"unknown option: {option}")
    return _action


def _make_number_action(sid: str, field_name: str):
    """Create a number set action."""
    async def _action(context: DeviceContext, data: Mapping[str, Any]) -> None:
        value = data.get("value")
        if value is None:
            raise ValueError("value is required")
        await context.async_send_service(sid, {field_name: int(value)})
    return _action


# =============================================================================
# Button actions
# =============================================================================

async def _check_firmware(context: DeviceContext, data: Mapping[str, Any]) -> None:
    """Check for firmware update."""
    await context.async_send_service("update", {"action": "0"})


async def _start_upgrade(context: DeviceContext, data: Mapping[str, Any]) -> None:
    """Start firmware upgrade."""
    await context.async_send_service("update", {"action": "1"})


# =============================================================================
# Adapter class
# =============================================================================

class ProductKW5LAdapter:
    """Huawei SmartLock 2 Pro (KW5L) adapter for Home Assistant."""

    prod_id = "KW5L"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        entities: list[EntitySpec] = []

        # =========================================================================
        # Lock entity (lock platform)
        # =========================================================================
        if context.has_service("lockStatus"):
            lock_status_field = _field(profile, "lockStatus", "status") or {}

            def lock_state(device: DeviceContext) -> Mapping[str, Any]:
                status = _number(device.value("lockStatus", "status"))
                # 2=已开锁, 4=已关门 → unlocked; 3=已上锁, 6=已反锁 → locked
                is_locked = status in (_LOCK_STATUS_LOCKED, _LOCK_STATUS_DEADLOCK)
                is_jammed = status == _LOCK_STATUS_NOT_CLOSED
                return {
                    "is_locked": is_locked,
                    "is_jammed": is_jammed,
                }

            entities.append(
                EntitySpec(
                    platform="lock",
                    key="lock",
                    name="门锁",
                    state=lock_state,
                    metadata={},
                    actions={
                        "lock": _lock_lock,
                        "unlock": _lock_unlock,
                    },
                )
            )

        # =========================================================================
        # Binary sensors
        # =========================================================================
        if context.has_service("lockStatus"):
            # Door closed sensor
            def door_state(device: DeviceContext) -> Mapping[str, Any]:
                status = _number(device.value("lockStatus", "status"))
                # 4=已关门, 3=已上锁, 6=已反锁 → on (door closed)
                # 2=已开锁, 1=门未关异常上锁 → off (door open)
                return {"is_on": status in (_LOCK_STATUS_DOOR_CLOSED, _LOCK_STATUS_LOCKED, _LOCK_STATUS_DEADLOCK)}

            entities.append(
                EntitySpec(
                    platform="binary_sensor",
                    key="door_closed",
                    name="门状态",
                    state=door_state,
                    metadata={"device_class": "door"},
                )
            )

            # Deadlock sensor
            def deadlock_state(device: DeviceContext) -> Mapping[str, Any]:
                status = _number(device.value("lockStatus", "status"))
                return {"is_on": status == _LOCK_STATUS_DEADLOCK}

            entities.append(
                EntitySpec(
                    platform="binary_sensor",
                    key="deadlock",
                    name="反锁状态",
                    state=deadlock_state,
                    metadata={"device_class": "lock"},
                )
            )

            # Door not closed alarm
            def door_not_closed_state(device: DeviceContext) -> Mapping[str, Any]:
                status = _number(device.value("lockStatus", "status"))
                return {"is_on": status == _LOCK_STATUS_NOT_CLOSED}

            entities.append(
                EntitySpec(
                    platform="binary_sensor",
                    key="door_not_closed_alarm",
                    name="门未关告警",
                    state=door_not_closed_state,
                    metadata={"device_class": "problem"},
                )
            )

        # Online status
        if context.has_service("networkConnectState"):
            def online_state(device: DeviceContext) -> Mapping[str, Any]:
                state = _number(device.value("networkConnectState", "state"))
                return {"is_on": state == _NET_STATE_ONLINE}

            entities.append(
                EntitySpec(
                    platform="binary_sensor",
                    key="online",
                    name="在线状态",
                    state=online_state,
                    metadata={"device_class": "connectivity"},
                )
            )

        # =========================================================================
        # Sensors
        # =========================================================================
        # Door battery
        if context.has_service("doorBattery"):
            def door_battery_state(device: DeviceContext) -> Mapping[str, Any]:
                level = _number(device.value("doorBattery", "level"))
                return {"native_value": level if level is not None and level >= 0 else None}

            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="door_battery",
                    name="门锁电池",
                    state=door_battery_state,
                    metadata={
                        "device_class": "battery",
                        "native_unit_of_measurement": "%",
                        "state_class": "measurement",
                    },
                )
            )

        # Cat eye battery
        if context.has_service("catEyeBattery"):
            def cateye_battery_state(device: DeviceContext) -> Mapping[str, Any]:
                level = _number(device.value("catEyeBattery", "level"))
                return {"native_value": level if level is not None and level >= 0 else None}

            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="cateye_battery",
                    name="猫眼电池",
                    state=cateye_battery_state,
                    metadata={
                        "device_class": "battery",
                        "native_unit_of_measurement": "%",
                        "state_class": "measurement",
                    },
                )
            )

        # Lock alarm status
        if context.has_service("lockAlarm"):
            alarm_field = _field(profile, "lockAlarm", "alarm") or {}

            def alarm_state(device: DeviceContext) -> Mapping[str, Any]:
                alarm = _number(device.value("lockAlarm", "alarm"))
                if alarm is None:
                    return {"native_value": None}
                label = _enum_label(alarm_field, alarm)
                return {"native_value": label or str(alarm)}

            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="lock_alarm",
                    name="告警状态",
                    state=alarm_state,
                    metadata={"device_class": "enum"},
                )
            )

        # WiFi signal intensity
        if context.has_service("netInfo"):
            def wifi_intensity_state(device: DeviceContext) -> Mapping[str, Any]:
                intensity = _number(device.value("netInfo", "intensity"))
                return {"native_value": intensity}

            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="wifi_intensity",
                    name="WiFi信号强度",
                    state=wifi_intensity_state,
                    metadata={
                        "native_unit_of_measurement": "%",
                        "state_class": "measurement",
                        "icon": "mdi:wifi",
                    },
                )
            )

            # WiFi RSSI
            def wifi_rssi_state(device: DeviceContext) -> Mapping[str, Any]:
                rssi = _number(device.value("netInfo", "RSSI"))
                return {"native_value": rssi}

            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="wifi_rssi",
                    name="WiFi RSSI",
                    state=wifi_rssi_state,
                    metadata={
                        "native_unit_of_measurement": "dBm",
                        "state_class": "measurement",
                        "device_class": "signal_strength",
                    },
                )
            )

            # WiFi SSID
            def wifi_ssid_state(device: DeviceContext) -> Mapping[str, Any]:
                ssid = device.value("netInfo", "SSID")
                return {"native_value": ssid}

            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="wifi_ssid",
                    name="WiFi SSID",
                    state=wifi_ssid_state,
                    metadata={"icon": "mdi:wifi"},
                )
            )

        # Firmware version
        if context.has_service("update"):
            def firmware_version_state(device: DeviceContext) -> Mapping[str, Any]:
                version = device.value("update", "version")
                return {"native_value": version}

            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="firmware_version",
                    name="固件版本",
                    state=firmware_version_state,
                    metadata={"icon": "mdi:information"},
                )
            )

            # Firmware upgrade progress
            def upgrade_progress_state(device: DeviceContext) -> Mapping[str, Any]:
                progress = _number(device.value("update", "progress"))
                return {"native_value": progress}

            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="upgrade_progress",
                    name="升级进度",
                    state=upgrade_progress_state,
                    metadata={
                        "native_unit_of_measurement": "%",
                        "icon": "mdi:progress-download",
                    },
                )
            )

        # =========================================================================
        # Event entity (door events, alarms, user operations)
        # =========================================================================
        if context.has_service("event"):
            def event_state(device: DeviceContext) -> Mapping[str, Any]:
                event_type = _number(device.value("event", "eventType"))
                user_op = _number(device.value("event", "userOperation"))
                door_alarm = _number(device.value("event", "doorAlarmState"))
                user_name = device.value("event", "userName")
                event_time = device.value("event", "eventTime")

                # Build event type label
                if event_type == 1:
                    event_label = "记录"
                elif event_type == 2:
                    event_label = "告警"
                else:
                    event_label = str(event_type) if event_type is not None else None

                # Build user operation label
                op_label = _USER_OPS.get(user_op) if user_op is not None else None

                # Build door alarm label
                alarm_label = _DOOR_ALARM.get(door_alarm) if door_alarm is not None else None

                # Determine the event type for HA
                ha_event_type = None
                if event_type == 2 or door_alarm is not None:
                    ha_event_type = "alarm"
                elif event_type == 1:
                    ha_event_type = "record"

                return {
                    "event_type": ha_event_type or "unknown",
                    "event_label": event_label,
                    "user_operation": op_label,
                    "door_alarm": alarm_label,
                    "user_name": user_name,
                    "event_time": event_time,
                }

            entities.append(
                EntitySpec(
                    platform="event",
                    key="door_event",
                    name="门锁事件",
                    state=event_state,
                    metadata={
                        "event_types": ["record", "alarm", "unknown"],
                        "icon": "mdi:bell-ring",
                    },
                )
            )

        # =========================================================================
        # Buttons (firmware update)
        # =========================================================================
        if context.has_service("update"):
            entities.append(
                EntitySpec(
                    platform="button",
                    key="check_firmware",
                    name="检查固件更新",
                    state=lambda d: {},
                    metadata={"icon": "mdi:update"},
                    actions={"press": _check_firmware},
                )
            )

            entities.append(
                EntitySpec(
                    platform="button",
                    key="start_upgrade",
                    name="启动固件升级",
                    state=lambda d: {},
                    metadata={"icon": "mdi:arrow-up-bold-circle"},
                    actions={"press": _start_upgrade},
                )
            )

        # =========================================================================
        # Switches (alarm event settings)
        # =========================================================================
        if context.has_service("alarmEventSetting"):
            alarm_switches = [
                ("door_not_close_switch", "doorNotCLoseSwitch", "门未关告警"),
                ("unlock_switch", "unlockSwitch", "开锁告警"),
                ("lock_broken_switch", "lockBrokenSwitch", "门锁故障告警"),
                ("force_unlocked_switch", "forceUnlockedSwitch", "暴力开锁告警"),
                ("alert_mode_unlocked_switch", "alertModeUnlockedSwitch", "异常开锁告警"),
                ("low_battery_switch", "lowBatterySwitch", "低电量告警"),
                ("take_snapshot_switch", "takeSnapshotSwitch", "告警拍照"),
                ("door_open_switch", "doorOpenSwitch", "开门告警"),
                ("message_push_switch", "messagePushSwitch", "消息推送"),
            ]

            for key, field_name, name in alarm_switches:
                def make_switch_state(fn: str):
                    def switch_state(device: DeviceContext) -> Mapping[str, Any]:
                        value = _number(device.value("alarmEventSetting", fn))
                        return {"is_on": value == 1}
                    return switch_state

                entities.append(
                    EntitySpec(
                        platform="switch",
                        key=f"alarm_{key}",
                        name=name,
                        state=make_switch_state(field_name),
                        metadata={"icon": "mdi:bell-alert"},
                        actions={"turn_on": _make_switch_action("alarmEventSetting", field_name),
                                 "turn_off": _make_switch_action("alarmEventSetting", field_name)},
                    )
                )

            # outAlarmTime select (5秒/10秒/15秒)
            out_alarm_field = _field(profile, "alarmEventSetting", "outAlarmTime") or {}
            out_alarm_options = tuple(
                (str(opt.get("descCh") or opt.get("enumVal")), opt.get("enumVal"))
                for opt in out_alarm_field.get("enumList", ())
                if isinstance(opt, Mapping)
            )
            if out_alarm_options:
                def out_alarm_state(device: DeviceContext) -> Mapping[str, Any]:
                    value = _number(device.value("alarmEventSetting", "outAlarmTime"))
                    if value is None:
                        return {"current_option": None}
                    label = next((l for l, v in out_alarm_options if v == value), str(value))
                    return {"current_option": label}

                entities.append(
                    EntitySpec(
                        platform="select",
                        key="out_alarm_time",
                        name="门外告警延时",
                        state=out_alarm_state,
                        metadata={"options": tuple(l for l, _ in out_alarm_options)},
                        actions={"select_option": _make_enum_action("alarmEventSetting", "outAlarmTime", out_alarm_options)},
                    )
                )

            # inAlarmTime select (5秒/15秒/30秒)
            in_alarm_field = _field(profile, "alarmEventSetting", "inAlarmTime") or {}
            in_alarm_options = tuple(
                (str(opt.get("descCh") or opt.get("enumVal")), opt.get("enumVal"))
                for opt in in_alarm_field.get("enumList", ())
                if isinstance(opt, Mapping)
            )
            if in_alarm_options:
                def in_alarm_state(device: DeviceContext) -> Mapping[str, Any]:
                    value = _number(device.value("alarmEventSetting", "inAlarmTime"))
                    if value is None:
                        return {"current_option": None}
                    label = next((l for l, v in in_alarm_options if v == value), str(value))
                    return {"current_option": label}

                entities.append(
                    EntitySpec(
                        platform="select",
                        key="in_alarm_time",
                        name="门内告警延时",
                        state=in_alarm_state,
                        metadata={"options": tuple(l for l, _ in in_alarm_options)},
                        actions={"select_option": _make_enum_action("alarmEventSetting", "inAlarmTime", in_alarm_options)},
                    )
                )

            # messagePushTime select
            push_time_field = _field(profile, "alarmEventSetting", "messagePushTime") or {}
            push_time_options = tuple(
                (str(opt.get("descCh") or opt.get("enumVal")), opt.get("enumVal"))
                for opt in push_time_field.get("enumList", ())
                if isinstance(opt, Mapping)
            )
            if push_time_options:
                def push_time_state(device: DeviceContext) -> Mapping[str, Any]:
                    value = _number(device.value("alarmEventSetting", "messagePushTime"))
                    if value is None:
                        return {"current_option": None}
                    label = next((l for l, v in push_time_options if v == value), str(value))
                    return {"current_option": label}

                entities.append(
                    EntitySpec(
                        platform="select",
                        key="message_push_time",
                        name="消息推送时间",
                        state=push_time_state,
                        metadata={"options": tuple(l for l, _ in push_time_options)},
                        actions={"select_option": _make_enum_action("alarmEventSetting", "messagePushTime", push_time_options)},
                    )
                )

        # =========================================================================
        # Switches (cat eye settings)
        # =========================================================================
        if context.has_service("catEyeSetting"):
            cateye_switches = [
                ("stay_snapshot", "staySnapshotSwitch", "逗留抓拍"),
                ("live_video", "liveVideoSwitch", "实时视频"),
                ("distortion_correction", "distortionCorrectionSwitch", "畸变校正"),
                ("cateye_snapshot", "takeSnapshotSwitch", "猫眼拍照"),
                ("shimmer_full_color", "shimmerFullColorSwitch", "微光全彩"),
            ]

            for key, field_name, name in cateye_switches:
                def make_cateye_switch_state(fn: str):
                    def switch_state(device: DeviceContext) -> Mapping[str, Any]:
                        value = _number(device.value("catEyeSetting", fn))
                        return {"is_on": value == 1}
                    return switch_state

                entities.append(
                    EntitySpec(
                        platform="switch",
                        key=f"cateye_{key}",
                        name=name,
                        state=make_cateye_switch_state(field_name),
                        metadata={"icon": "mdi:camera"},
                        actions={"turn_on": _make_switch_action("catEyeSetting", field_name),
                                 "turn_off": _make_switch_action("catEyeSetting", field_name)},
                    )
                )

            # stayDuration select (3-15秒)
            stay_duration_field = _field(profile, "catEyeSetting", "stayDuration") or {}
            stay_duration_options = tuple(
                (str(opt.get("descCh") or opt.get("enumVal")), opt.get("enumVal"))
                for opt in stay_duration_field.get("enumList", ())
                if isinstance(opt, Mapping)
            )
            if stay_duration_options:
                def stay_duration_state(device: DeviceContext) -> Mapping[str, Any]:
                    value = _number(device.value("catEyeSetting", "stayDuration"))
                    if value is None:
                        return {"current_option": None}
                    label = next((l for l, v in stay_duration_options if v == value), str(value))
                    return {"current_option": label}

                entities.append(
                    EntitySpec(
                        platform="select",
                        key="stay_duration",
                        name="逗留检测时长",
                        state=stay_duration_state,
                        metadata={"options": tuple(l for l, _ in stay_duration_options)},
                        actions={"select_option": _make_enum_action("catEyeSetting", "stayDuration", stay_duration_options)},
                    )
                )

            # shootingInterval select
            shooting_interval_field = _field(profile, "catEyeSetting", "shootingInterval") or {}
            shooting_interval_options = tuple(
                (str(opt.get("descCh") or opt.get("enumVal")), opt.get("enumVal"))
                for opt in shooting_interval_field.get("enumList", ())
                if isinstance(opt, Mapping)
            )
            if shooting_interval_options:
                def shooting_interval_state(device: DeviceContext) -> Mapping[str, Any]:
                    value = _number(device.value("catEyeSetting", "shootingInterval"))
                    if value is None:
                        return {"current_option": None}
                    label = next((l for l, v in shooting_interval_options if v == value), str(value))
                    return {"current_option": label}

                entities.append(
                    EntitySpec(
                        platform="select",
                        key="shooting_interval",
                        name="拍摄间隔",
                        state=shooting_interval_state,
                        metadata={"options": tuple(l for l, _ in shooting_interval_options)},
                        actions={"select_option": _make_enum_action("catEyeSetting", "shootingInterval", shooting_interval_options)},
                    )
                )

            # shootingDuration select
            shooting_duration_field = _field(profile, "catEyeSetting", "shootingDuration") or {}
            shooting_duration_options = tuple(
                (str(opt.get("descCh") or opt.get("enumVal")), opt.get("enumVal"))
                for opt in shooting_duration_field.get("enumList", ())
                if isinstance(opt, Mapping)
            )
            if shooting_duration_options:
                def shooting_duration_state(device: DeviceContext) -> Mapping[str, Any]:
                    value = _number(device.value("catEyeSetting", "shootingDuration"))
                    if value is None:
                        return {"current_option": None}
                    label = next((l for l, v in shooting_duration_options if v == value), str(value))
                    return {"current_option": label}

                entities.append(
                    EntitySpec(
                        platform="select",
                        key="shooting_duration",
                        name="拍摄时长",
                        state=shooting_duration_state,
                        metadata={"options": tuple(l for l, _ in shooting_duration_options)},
                        actions={"select_option": _make_enum_action("catEyeSetting", "shootingDuration", shooting_duration_options)},
                    )
                )

            # callValidPeriod select
            call_valid_field = _field(profile, "catEyeSetting", "callValidPeriod") or {}
            call_valid_options = tuple(
                (str(opt.get("descCh") or opt.get("enumVal")), opt.get("enumVal"))
                for opt in call_valid_field.get("enumList", ())
                if isinstance(opt, Mapping)
            )
            if call_valid_options:
                def call_valid_state(device: DeviceContext) -> Mapping[str, Any]:
                    value = _number(device.value("catEyeSetting", "callValidPeriod"))
                    if value is None:
                        return {"current_option": None}
                    label = next((l for l, v in call_valid_options if v == value), str(value))
                    return {"current_option": label}

                entities.append(
                    EntitySpec(
                        platform="select",
                        key="call_valid_period",
                        name="通话有效期",
                        state=call_valid_state,
                        metadata={"options": tuple(l for l, _ in call_valid_options)},
                        actions={"select_option": _make_enum_action("catEyeSetting", "callValidPeriod", call_valid_options)},
                    )
                )

            # detectDistance select
            detect_distance_field = _field(profile, "catEyeSetting", "detectDistance") or {}
            detect_distance_options = tuple(
                (str(opt.get("descCh") or opt.get("enumVal")), opt.get("enumVal"))
                for opt in detect_distance_field.get("enumList", ())
                if isinstance(opt, Mapping)
            )
            if detect_distance_options:
                def detect_distance_state(device: DeviceContext) -> Mapping[str, Any]:
                    value = _number(device.value("catEyeSetting", "detectDistance"))
                    if value is None:
                        return {"current_option": None}
                    label = next((l for l, v in detect_distance_options if v == value), str(value))
                    return {"current_option": label}

                entities.append(
                    EntitySpec(
                        platform="select",
                        key="detect_distance",
                        name="检测距离",
                        state=detect_distance_state,
                        metadata={"options": tuple(l for l, _ in detect_distance_options)},
                        actions={"select_option": _make_enum_action("catEyeSetting", "detectDistance", detect_distance_options)},
                    )
                )

        # =========================================================================
        # Switches (security settings)
        # =========================================================================
        if context.has_service("securitySetting"):
            security_switches = [
                ("deployment", "deploymentSwitch", "布防模式"),
                ("double_check", "doubleCheckSwitch", "双重验证"),
                ("password_verification", "passwordVerificationSwitch", "密码验证"),
                ("enable_lockout", "enableLockoutSwitch", "锁定保护"),
                ("face_identify", "faceIdentifySwitch", "人脸识别"),
                ("enable_senser_open", "enableSenserOpenSwitch", "感应开锁"),
            ]

            for key, field_name, name in security_switches:
                def make_security_switch_state(fn: str):
                    def switch_state(device: DeviceContext) -> Mapping[str, Any]:
                        value = _number(device.value("securitySetting", fn))
                        return {"is_on": value == 1}
                    return switch_state

                entities.append(
                    EntitySpec(
                        platform="switch",
                        key=f"security_{key}",
                        name=name,
                        state=make_security_switch_state(field_name),
                        metadata={"icon": "mdi:shield-lock"},
                        actions={"turn_on": _make_switch_action("securitySetting", field_name),
                                 "turn_off": _make_switch_action("securitySetting", field_name)},
                    )
                )

        # =========================================================================
        # Numbers (volume settings)
        # =========================================================================
        if context.has_service("volumeSetting"):
            volume_numbers = [
                ("ring_volume", "ringVolume", "铃声音量"),
                ("key_volume", "keyVolume", "按键音量"),
                ("voice_volume", "voiceVolume", "语音音量"),
            ]

            for key, field_name, name in volume_numbers:
                def make_volume_state(fn: str):
                    def volume_state(device: DeviceContext) -> Mapping[str, Any]:
                        value = _number(device.value("volumeSetting", fn))
                        return {"native_value": value}
                    return volume_state

                entities.append(
                    EntitySpec(
                        platform="number",
                        key=key,
                        name=name,
                        state=make_volume_state(field_name),
                        metadata={
                            "native_min_value": 0,
                            "native_max_value": 100,
                            "native_step": 1,
                            "native_unit_of_measurement": "%",
                            "icon": "mdi:volume-high",
                        },
                        actions={"set_value": _make_number_action("volumeSetting", field_name)},
                    )
                )

            # Night mode switch
            def night_mode_state(device: DeviceContext) -> Mapping[str, Any]:
                value = _number(device.value("volumeSetting", "nightModeSwitch"))
                return {"is_on": value == 1}

            entities.append(
                EntitySpec(
                    platform="switch",
                    key="night_mode",
                    name="夜间模式",
                    state=night_mode_state,
                    metadata={"icon": "mdi:weather-night"},
                    actions={"turn_on": _make_switch_action("volumeSetting", "nightModeSwitch"),
                             "turn_off": _make_switch_action("volumeSetting", "nightModeSwitch")},
                )
            )

            # Current ring select
            supported_ring = _number(context.value("volumeSetting", "supportedRing"))
            if supported_ring is not None and supported_ring > 0:
                ring_options = tuple(
                    (f"铃声{i}", i) for i in range(supported_ring)
                )

                def current_ring_state(device: DeviceContext) -> Mapping[str, Any]:
                    value = _number(device.value("volumeSetting", "currentRing"))
                    if value is None:
                        return {"current_option": None}
                    label = next((l for l, v in ring_options if v == value), str(value))
                    return {"current_option": label}

                entities.append(
                    EntitySpec(
                        platform="select",
                        key="current_ring",
                        name="当前铃声",
                        state=current_ring_state,
                        metadata={"options": tuple(l for l, _ in ring_options)},
                        actions={"select_option": _make_enum_action("volumeSetting", "currentRing", ring_options)},
                    )
                )

        return tuple(entities)


ADAPTER = ProductKW5LAdapter()
