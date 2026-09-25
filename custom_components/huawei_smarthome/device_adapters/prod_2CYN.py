"""User-contributed protocol for Huawei product 2CYN.

Product: VOC SmartLock  (deviceModel ``SHEP-SL0-VC1S``, prodId ``2CYN``).
Profile: https://smarthome-drcn.dbankcdn.com/device/guide/2CYN/2CYN.json

Note: This device is a smart lock, not a light. Direct lock/unlock state is not explicitly 
reported in the available services. Lock state is inferred from unlock events with an 
automatic re-lock timeout.

Services used:
   lockState.state         int  R  (0=休眠中, 1=已连接) - Device communication state
   lockMode.mode           int  R  (0=正常模式, 1=离家模式)
   battery.level           int  R  (0-100 电量)
   lockAlarm.alarm         int  R  (1=防撬告警, 2=低电量告警, 3=禁试告警, 4=挟持告警)
   event.event             int  R  (1=指纹开锁, 2=密码开锁, 3=门禁卡开锁, 4=华为智卡开锁, 5=临时密码开锁)
   event.eventTime         string R  时间戳
   update.action           int  RW (0=检查新版本, 1=启动升级)
   update.version          string R  版本信息
   update.progress         int  R  (0-100 升级进度)
   netInfo.intensity       int  R  (0-100 信号强度)
   netInfo.RSSI            int  R  RSSI值
   netInfo.SSID            string R  路由器SSID
   netInfo.BSSID           string R  路由器BSSID
   netInfo.IP              string R  设备IP

Note: Lock/unlock state inference:
- Device reports unlock events (event.event = 1-5) but not explicit lock events
- Lock state is tracked as: unlocked after unlock event, then automatically locks after 30s
- This is an approximation; actual behavior may vary
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from typing import Any
from time import time

from .api import EntitySpec
from .context import DeviceContext

_LOGGER = logging.getLogger(__name__)

# Service IDs
_LOCK_STATE_SID = "lockState"
_LOCK_STATE_FIELD = "state"
_LOCK_MODE_SID = "lockMode"
_LOCK_MODE_FIELD = "mode"
_BATTERY_SID = "battery"
_BATTERY_FIELD = "level"
_LOCK_ALARM_SID = "lockAlarm"
_LOCK_ALARM_ALARM_FIELD = "alarm"
_LOCK_ALARM_ID_FIELD = "id"
_LOCK_ALARM_TYPE_FIELD = "type"
_LOCK_ALARM_TIME_FIELD = "alarmTime"
_EVENT_SID = "event"
_EVENT_EVENT_FIELD = "event"
_EVENT_ID_FIELD = "id"
_EVENT_TIME_FIELD = "eventTime"
_KEYOPERATE_SID = "keyOperate"
_UPDATE_SID = "update"
_UPDATE_ACTION_FIELD = "action"
_UPDATE_VERSION_FIELD = "version"
_UPDATE_PROGRESS_FIELD = "progress"
_UPDATE_BOOTTIME_FIELD = "bootTime"
_NET_INFO_SID = "netInfo"
_NET_INFO_INTENSITY_FIELD = "intensity"
_NET_INFO_RSSI_FIELD = "RSSI"
_NET_INFO_SSID_FIELD = "SSID"
_NET_INFO_BSSID_FIELD = "BSSID"
_NET_INFO_IP_FIELD = "IP"

# Profile characteristic names for enum labels
_LOCK_STATE_PROFILE_FIELD = "state"
_LOCK_MODE_PROFILE_FIELD = "mode"
_BATTERY_PROFILE_FIELD = "level"
_LOCK_ALARM_PROFILE_FIELD = "alarm"
_EVENT_PROFILE_FIELD = "event"
_UPDATE_ACTION_PROFILE_FIELD = "action"

# lockState/status values declared by the Profile.
_STATE_SLEEPING = 0  # 休眠中
_STATE_CONNECTED = 1  # 已连接

# lockMode.mode values declared by the Profile.
_MODE_NORMAL = 0  # 正常模式
_MODE_AWAY = 1  # 离家模式

# lockAlarm/alarm values declared by the Profile.
_ALARM_TAMPER = 1  # 防撬告警
_ALARM_LOW_BATTERY = 2  # 低电量告警
_ALARM_TAMPER_CODE = 3  # 禁试告警
_ALARM_DURESS = 4  # 挟持告警

# event/event values declared by the Profile (unlock events).
_EVENT_FINGERPRINT = 1  # 指纹开锁
_EVENT_PASSWORD = 2  # 密码开锁
_EVENT_CARD = 3  # 门禁卡开锁
_EVENT_HUAWEI_CARD = 4  # 华为智卡开锁
_EVENT_TEMP_PASSWORD = 5  # 临时密码开锁

# update/action values declared by the Profile.
_UPDATE_ACTION_CHECK = 0  # 检查新版本
_UPDATE_ACTION_START = 1  # 启动升级

# How long to consider lock unlocked after an unlock event (seconds)
_UNLOCK_TIMEOUT = 30


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


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.strip().casefold() in {"1", "true", "on"}:
            return True
        if value.strip().casefold() in {"0", "false", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _status_reader() -> Callable[[DeviceContext], Any]:
    """Return a reader that keeps the last declared lockState value."""

    cache: dict[str, Any] = {"status": None}

    def read(device: DeviceContext) -> Any:
        status = _number(device.value(_LOCK_STATE_SID, _LOCK_STATE_FIELD))
        if status in (_STATE_SLEEPING, _STATE_CONNECTED):
            cache["status"] = status
        return cache["status"]

    return read


def _lock_state_inferrer() -> Callable[[DeviceContext], Any]:
    """Return a reader that infers lock state from unlock events with timeout."""

    cache: dict[str, Any] = {
        "is_unlocked": False,  # Start locked (conservative assumption)
        "unlock_time": 0,      # Timestamp of last unlock event
    }

    def read(device: DeviceContext) -> Any:
        # Check for recent unlock events
        event_id = _number(_event_record(device).get(_EVENT_ID_FIELD))
        event_time_str = _event_record(device).get(_EVENT_TIME_FIELD)
        
        # If we have a new unlock event, update state
        if event_id is not None and event_time_str is not None:
            try:
                # Parse event time (format may vary, try common formats)
                # For simplicity, we'll use current time if parsing fails
                # In a real implementation, you'd want to parse the timestamp properly
                event_time = time()  # Fallback to current time
                # TODO: Properly parse event_time_str if it's a timestamp string
                
                # Check if this is a newer unlock event
                if event_time > cache["unlock_time"]:
                    cache["is_unlocked"] = True
                    cache["unlock_time"] = event_time
                    _LOGGER.debug(
                        "2CYN: Unlock event detected (id=%s), setting unlocked state",
                        event_id
                    )
            except (ValueError, TypeError):
                _LOGGER.warning("2CYN: Could not parse event time: %s", event_time_str)
        
        # Check if unlock timeout has passed
        if cache["is_unlocked"]:
            current_time = time()
            if current_time - cache["unlock_time"] > _UNLOCK_TIMEOUT:
                cache["is_unlocked"] = False
                _LOGGER.debug(
                    "2CYN: Unlock timeout expired (%ss), setting locked state",
                    _UNLOCK_TIMEOUT
                )
        
        return {"is_locked": not cache["is_unlocked"]}

    return read


def _event_record(device: DeviceContext) -> Mapping[str, Any]:
    """Return the flat event record."""

    record: dict[str, Any] = dict(device.service_state(_EVENT_SID))
    return record


def _lock_spec(profile: Mapping[str, Any]) -> EntitySpec:
    """Lock entity with inferred state."""

    def lock_state(device: DeviceContext) -> Mapping[str, Any]:
        state_reader = _lock_state_inferrer()
        return state_reader(device)

    return EntitySpec(
        platform="lock",
        key="lock",
        name="华为智选 VOC智能门锁S",
        state=lock_state,
    )


def _lock_mode_spec(profile: Mapping[str, Any]) -> EntitySpec:
    """Sensor for lock mode."""

    field = _field(profile, _LOCK_MODE_SID, _LOCK_MODE_FIELD) or {}

    def state(device: DeviceContext) -> Mapping[str, Any]:
        value = _number(device.value(_LOCK_MODE_SID, _LOCK_MODE_FIELD))
        if value is None:
            return {"native_value": None}
        return {"native_value": _enum_label(field, value) or str(value)}

    return EntitySpec(
        platform="sensor",
        key="lock_mode",
        name="锁模式",
        state=state,
    )


def _battery_spec() -> EntitySpec:
    """Sensor for battery level."""

    def state(device: DeviceContext) -> Mapping[str, Any]:
        value = _number(device.value(_BATTERY_SID, _BATTERY_FIELD))
        if value is None:
            return {"native_value": None}
        return {"native_value": value}

    return EntitySpec(
        platform="sensor",
        key="battery",
        name="电量",
        state=state,
        metadata={
            "device_class": "battery",
            "unit": "%",
            "state_class": "measurement",
        },
    )


def _last_action_time_spec() -> EntitySpec:
    """Sensor for last action time."""

    def state(device: DeviceContext) -> Mapping[str, Any]:
        value = device.value("lastActionTime", "time")
        if value is None:
            return {"native_value": None}
        return {"native_value": value}

    return EntitySpec(
        platform="sensor",
        key="last_action_time",
        name="最后操作时间",
        state=state,
    )


def _tamper_alarm_spec(profile: Mapping[str, Any]) -> EntitySpec:
    """Binary sensor for tamper alarm."""

    field = _field(profile, _LOCK_ALARM_SID, _LOCK_ALARM_ALARM_FIELD) or {}

    def state(device: DeviceContext) -> Mapping[str, Any]:
        value = _number(device.value(_LOCK_ALARM_SID, _LOCK_ALARM_ALARM_FIELD))
        if value is None:
            return {"is_on": None}
        return {"is_on": value == _ALARM_TAMPER}

    return EntitySpec(
        platform="binary_sensor",
        key="tamper_alarm",
        name="防撬告警",
        state=state,
        metadata={"device_class": "safety"},
    )


def _low_battery_alarm_spec(profile: Mapping[str, Any]) -> EntitySpec:
    """Binary sensor for low battery alarm."""

    field = _field(profile, _LOCK_ALARM_SID, _LOCK_ALARM_ALARM_FIELD) or {}

    def state(device: DeviceContext) -> Mapping[str, Any]:
        value = _number(device.value(_LOCK_ALARM_SID, _LOCK_ALARM_ALARM_FIELD))
        if value is None:
            return {"is_on": None}
        return {"is_on": value == _ALARM_LOW_BATTERY}

    return EntitySpec(
        platform="binary_sensor",
        key="low_battery_alarm",
        name="低电量告警",
        state=state,
        metadata={"device_class": "battery"},
    )


def _duress_alarm_spec(profile: Mapping[str, Any]) -> EntitySpec:
    """Binary sensor for duress alarm."""

    field = _field(profile, _LOCK_ALARM_SID, _LOCK_ALARM_ALARM_FIELD) or {}

    def state(device: DeviceContext) -> Mapping[str, Any]:
        value = _number(device.value(_LOCK_ALARM_SID, _LOCK_ALARM_ALARM_FIELD))
        if value is None:
            return {"is_on": None}
        return {"is_on": value == _ALARM_DURESS}

    return EntitySpec(
        platform="binary_sensor",
        key="duress_alarm",
        name="挟持告警",
        state=state,
        metadata={"device_class": "safety"},
    )


def _last_unlock_method_spec(profile: Mapping[str, Any]) -> EntitySpec:
    """Sensor for last unlock method."""

    field = _field(profile, _EVENT_SID, _EVENT_EVENT_FIELD) or {}

    def state(device: DeviceContext) -> Mapping[str, Any]:
        value = _number(_event_record(device).get(_EVENT_EVENT_FIELD))
        if value is None:
            return {"native_value": None}
        return {"native_value": _enum_label(field, value) or str(value)}

    return EntitySpec(
        platform="sensor",
        key="last_unlock_method",
        name="最后开锁方式",
        state=state,
    )


def _last_unlock_time_spec() -> EntitySpec:
    """Sensor for last unlock time."""

    def state(device: DeviceContext) -> Mapping[str, Any]:
        value = _event_record(device).get(_EVENT_TIME_FIELD)
        if value is None:
            return {"native_value": None}
        return {"native_value": value}

    return EntitySpec(
        platform="sensor",
        key="last_unlock_time",
        name="最后开锁时间",
        state=state,
    )


def _update_spec(profile: Mapping[str, Any]) -> EntitySpec:
    """Sensor for update status."""

    action_field = _field(profile, _UPDATE_SID, _UPDATE_ACTION_FIELD) or {}
    version_field = _field(profile, _UPDATE_SID, _UPDATE_VERSION_FIELD) or {}
    progress_field = _field(profile, _UPDATE_SID, _UPDATE_PROGRESS_FIELD) or {}

    def state(device: DeviceContext) -> Mapping[str, Any]:
        state_dict: dict[str, Any] = {}
        
        action = _number(device.value(_UPDATE_SID, _UPDATE_ACTION_FIELD))
        if action is not None:
            state_dict["update_action"] = _enum_label(action_field, action) or str(action)
        
        version = device.value(_UPDATE_SID, _UPDATE_VERSION_FIELD)
        if version is not None:
            state_dict["update_version"] = version
            
        progress = _number(device.value(_UPDATE_SID, _UPDATE_PROGRESS_FIELD))
        if progress is not None:
            state_dict["update_progress"] = progress
            
        return state_dict

    return EntitySpec(
        platform="sensor",
        key="update",
        name="固件更新",
        state=state,
    )


def _update_action_spec(profile: Mapping[str, Any]) -> EntitySpec:
    """Button to trigger update check/start."""

    field = _field(profile, _UPDATE_SID, _UPDATE_ACTION_FIELD) or {}

    async def press_update(context: DeviceContext, data: Mapping[str, Any]) -> None:
        action = data.get("action")
        if action == "check":
            await context.async_send_service(_UPDATE_SID, {_UPDATE_ACTION_FIELD: _UPDATE_ACTION_CHECK})
        elif action == "start":
            await context.async_send_service(_UPDATE_SID, {_UPDATE_ACTION_FIELD: _UPDATE_ACTION_START})

    return EntitySpec(
        platform="button",
        key="update_action",
        name="固件更新",
        state=lambda device: {},  # Buttons don't need state
        actions={
            "press": press_update,
        },
    )


def _net_info_spec() -> EntitySpec:
    """Sensor for network information."""

    def state(device: DeviceContext) -> Mapping[str, Any]:
        state_dict: dict[str, Any] = {}
        
        intensity = _number(device.value(_NET_INFO_SID, _NET_INFO_INTENSITY_FIELD))
        if intensity is not None:
            state_dict["signal_strength"] = intensity
            
        rssi = _number(device.value(_NET_INFO_SID, _NET_INFO_RSSI_FIELD))
        if rssi is not None:
            state_dict["rssi"] = rssi
            
        ssid = device.value(_NET_INFO_SID, _NET_INFO_SSID_FIELD)
        if ssid is not None:
            state_dict["ssid"] = ssid
            
        bssid = device.value(_NET_INFO_SID, _NET_INFO_BSSID_FIELD)
        if bssid is not None:
            state_dict["bssid"] = bssid
            
        ip = device.value(_NET_INFO_SID, _NET_INFO_IP_FIELD)
        if ip is not None:
            state_dict["ip_address"] = ip
            
        return state_dict

    return EntitySpec(
        platform="sensor",
        key="net_info",
        name="网络信息",
        state=state,
    )


class Product2CYNAdapter:
    """VOC SmartLock  (SHEP-SL0-VC1S) entity and command choices."""

    prod_id = "2CYN"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        entities = [
            _lock_spec(profile),
            _lock_mode_spec(profile),
            _battery_spec(),
            _last_action_time_spec(),
            _tamper_alarm_spec(profile),
            _low_battery_alarm_spec(profile),
            _duress_alarm_spec(profile),
            _last_unlock_method_spec(profile),
            _last_unlock_time_spec(),
            _update_spec(profile),
            _update_action_spec(profile),
            _net_info_spec(),
        ]
        
        return tuple(entities)


ADAPTER = Product2CYNAdapter()
