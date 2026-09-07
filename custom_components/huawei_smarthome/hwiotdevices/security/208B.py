"""Explicit Huawei SmartHome model for the 208B Chlorop doorbell."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from typing import Any
import uuid

from ...const import OBSERVED_MQTT_FILTER
from ...domain.models import (
    RemoteDeviceDescriptor,
    is_older_remote_timestamp,
)
from ...mqtt_client import HuaweiMqttClient
from ..state import HuaweiDeviceStateMixin

PROD_ID = "208B"
MANUFACTURER_NAME = "顺德智勤"
PROFILE_MODEL = "CDB-Q30I"
PROFILE_NAME = "叶绿体自发电无线门铃WiFi版"
COMMAND_ACK_TIMEOUT = 10.0

SERVICE_RING_STATUS = "devStateServ"
SERVICE_MUTE = "muteOpServ"
SERVICE_VOLUME = "volume"
SERVICE_BELL = "bellServ"
SWITCH_SERVICE_IDS = tuple(f"switch{index}" for index in range(1, 9))
STATE_SERVICES = frozenset(
    {
        SERVICE_RING_STATUS,
        SERVICE_MUTE,
        SERVICE_VOLUME,
        SERVICE_BELL,
        *SWITCH_SERVICE_IDS,
    }
)
COMMAND_SERVICES = frozenset(
    {
        SERVICE_MUTE,
        SERVICE_VOLUME,
        SERVICE_BELL,
        *SWITCH_SERVICE_IDS,
    }
)

MUTE_KEY = "mute"
SWITCH_KEYS = (*SWITCH_SERVICE_IDS, MUTE_KEY)
SWITCH_NAMES = {
    **{
        service_id: f"Channel {index}"
        for index, service_id in enumerate(SWITCH_SERVICE_IDS, start=1)
    },
    MUTE_KEY: "Mute",
}

RING_ACTION = "ring"
BUTTON_ACTIONS = (RING_ACTION,)
BUTTON_EVENT_NAMES = {RING_ACTION: "Ring"}
RING_NAMES = {
    5: "Door",
    6: "Bedroom",
    7: "Living room",
    8: "Older adult room",
    9: "Children's room",
    10: "Office",
    11: "Bathroom",
    12: "Other",
    13: "Linked ringing",
}

RINGTONE_NAMES = (
    "暂无",
    "叮咚两声",
    "和弦音",
    "意大利波尔卡",
    "卡门序曲",
    "老式铃声",
    "钢琴音135i",
    "拉德斯基进行曲",
    "哆唻咪",
    "回家",
    "西班牙女郎",
    "茶花女",
    "土耳其进行曲",
    "啊朋友",
    "金婚氏",
    "圣诞快乐",
    "孤独的牧羊人",
    "胡桃夹子",
    "爱丽丝",
    "回忆",
    "威尔逊进行曲",
    "生日快乐",
    "铃儿响叮当",
    "苏三娜",
    "小步舞曲",
    "欢快铃声",
    "倒计时1",
    "倒计时2",
    "你好欢迎光临",
    "愉快韵律",
    "时钟滴答",
    "滴滴滴",
    "报警声",
)
RINGTONE_BY_VALUE = dict(enumerate(RINGTONE_NAMES))
RINGTONE_VALUE_BY_NAME = {
    name: value for value, name in RINGTONE_BY_VALUE.items()
}

SELECT_KEYS = ("ringtone",)
SELECT_NAMES = {"ringtone": "Ringtone"}
SELECT_OPTIONS = {"ringtone": RINGTONE_NAMES}
NUMBER_KEYS = ("volume",)
NUMBER_METADATA = {"volume": ("Volume", 0.0, 100.0, 25.0, "%")}

StateListener = Callable[[], None]


@dataclass(frozen=True, slots=True)
class DoorbellEvent:
    """One ringing state reported by the 208B device."""

    action: str
    key_code: int
    button_id: int | None
    name: str | None
    timestamp: str | None


EventListener = Callable[[DoorbellEvent], None]


class HuaweiDevice(HuaweiDeviceStateMixin):
    """Runtime context and protocol mapping for one 208B device."""

    prod_id = PROD_ID
    profile_model = PROFILE_MODEL
    ha_platform = "switch"
    expose_aggregate_switch = False
    state_services = STATE_SERVICES
    command_services = COMMAND_SERVICES
    switch_keys = SWITCH_KEYS
    switch_names = SWITCH_NAMES
    button_event_actions = BUTTON_ACTIONS
    button_event_names = BUTTON_EVENT_NAMES
    select_keys = SELECT_KEYS
    select_names = SELECT_NAMES
    select_options = SELECT_OPTIONS
    number_keys = NUMBER_KEYS
    number_metadata = NUMBER_METADATA

    def __init__(
        self,
        descriptor: RemoteDeviceDescriptor,
        mqtt: HuaweiMqttClient,
    ) -> None:
        if (descriptor.prod_id or "").strip().upper() != PROD_ID:
            raise ValueError("208B device requires prodId=208B")
        self._descriptor = descriptor
        self._mqtt = mqtt
        self._state: dict[str, dict[str, Any]] = {
            sid: dict(service.data)
            for sid, service in descriptor.service_states.items()
            if sid in STATE_SERVICES
        }
        self._state_timestamps: dict[str, str] = {
            sid: service.reported_timestamp
            for sid, service in descriptor.service_states.items()
            if sid in STATE_SERVICES and service.reported_timestamp
        }
        self._listeners: set[StateListener] = set()
        self._event_listeners: set[EventListener] = set()
        self._pending_acks: dict[str, asyncio.Future[int]] = {}
        self._command_lock = asyncio.Lock()

    @property
    def descriptor(self) -> RemoteDeviceDescriptor:
        """Return the current discovered device descriptor."""

        return self._descriptor

    @property
    def key(self) -> tuple[str, str]:
        return self._descriptor.key

    @property
    def home_id(self) -> str:
        return self._descriptor.home_id

    @property
    def dev_id(self) -> str:
        return self._descriptor.dev_id

    @property
    def name(self) -> str:
        return self._descriptor.name or PROFILE_NAME

    @property
    def model(self) -> str:
        return self._descriptor.model or PROFILE_MODEL

    @property
    def manufacturer(self) -> str:
        return self._descriptor.manufacturer or MANUFACTURER_NAME

    @property
    def firmware_version(self) -> str | None:
        return self._descriptor.firmware_version

    @property
    def available(self) -> bool:
        return self._descriptor.online is not False

    def value(self, sid: str, name: str) -> Any:
        return self._state.get(sid, {}).get(name)

    def feature_is_on(self, key: str) -> bool | None:
        try:
            sid = self._switch_service(key)
        except KeyError as error:
            raise ValueError(f"unsupported 208B switch: {key}") from error
        field = "value" if key == MUTE_KEY else "on"
        return self._bool_value(sid, field)

    def select_value(self, key: str) -> str | None:
        if key not in SELECT_KEYS:
            raise ValueError(f"unsupported 208B select: {key}")
        value = self._int_value(SERVICE_BELL, "value")
        return RINGTONE_BY_VALUE.get(value)

    def number_value(self, key: str) -> float | None:
        if key not in NUMBER_KEYS:
            raise ValueError(f"unsupported 208B number: {key}")
        value = self._int_value(SERVICE_VOLUME, "value")
        if value is None:
            return None
        return float(min(max(value, 0), 100))

    def add_state_listener(self, listener: StateListener) -> None:
        self._listeners.add(listener)

    def remove_state_listener(self, listener: StateListener) -> None:
        self._listeners.discard(listener)

    def add_event_listener(self, listener: EventListener) -> None:
        self._event_listeners.add(listener)

    def remove_event_listener(self, listener: EventListener) -> None:
        self._event_listeners.discard(listener)

    def update_descriptor(self, descriptor: RemoteDeviceDescriptor) -> None:
        was_available = self.available
        self._descriptor = descriptor
        for sid, service in descriptor.service_states.items():
            if sid not in STATE_SERVICES:
                continue
            if sid not in self._state:
                self._state[sid] = dict(service.data)
            if sid not in self._state_timestamps and service.reported_timestamp:
                self._state_timestamps[sid] = service.reported_timestamp
        if was_available != self.available:
            self._notify_state_changed()

    def close(self) -> None:
        for future in self._pending_acks.values():
            if not future.done():
                future.cancel()
        self._pending_acks.clear()
        self._listeners.clear()
        self._event_listeners.clear()

    def handle_mqtt_message(self, topic: str, payload: bytes) -> bool:
        """Consume one official SmartHome state or command response."""

        del topic
        try:
            message = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
        if not isinstance(message, Mapping):
            return False
        body = message.get("body")
        header = message.get("header")
        if not isinstance(body, Mapping) or not isinstance(header, Mapping):
            return False

        notify_type = header.get("notifyType")
        if notify_type == "commandRsp":
            return self._handle_command_ack(body, header)
        if notify_type != "deviceDataChanged" or body.get("devId") != self.dev_id:
            return False

        services = body.get("services")
        if not isinstance(services, list):
            return False
        changed = False
        events: list[DoorbellEvent] = []
        for service in services:
            if not isinstance(service, Mapping):
                continue
            sid = service.get("sid")
            data = service.get("data")
            if not isinstance(sid, str) or not isinstance(data, Mapping):
                continue
            timestamp = service.get("ts")
            timestamp = timestamp if isinstance(timestamp, str) else None
            if sid == SERVICE_RING_STATUS and not is_older_remote_timestamp(
                timestamp,
                self._state_timestamps.get(sid),
            ):
                events.extend(self._parse_ring_events(data, timestamp))
            changed = self._merge_service_state(sid, data, timestamp) or changed

        if changed:
            self._notify_state_changed()
        for event in events:
            self._notify_event(event)
        return changed

    async def async_set_feature(self, key: str, enabled: bool) -> None:
        try:
            sid = self._switch_service(key)
        except KeyError as error:
            raise ValueError(f"unsupported 208B switch: {key}") from error
        field = "value" if key == MUTE_KEY else "on"
        await self.async_set_service(sid, {field: 1 if enabled else 0})

    async def async_select_option(self, key: str, option: str) -> None:
        if key not in SELECT_KEYS:
            raise ValueError(f"unsupported 208B select: {key}")
        try:
            value = RINGTONE_VALUE_BY_NAME[option]
        except KeyError as error:
            raise ValueError(f"unsupported 208B ringtone: {option}") from error
        await self.async_set_service(SERVICE_BELL, {"value": value})

    async def async_set_number(self, key: str, value: float) -> None:
        if key not in NUMBER_KEYS:
            raise ValueError(f"unsupported 208B number: {key}")
        volume = self._validated_volume(value)
        await self.async_set_service(SERVICE_VOLUME, {"value": volume})

    async def async_set_service(self, sid: str, data: dict[str, Any]) -> None:
        if sid not in COMMAND_SERVICES:
            raise ValueError(f"unsupported 208B service: {sid}")
        target = f"/devices/{self.dev_id}/services/{sid}"
        async with self._command_lock:
            request_id = str(uuid.uuid4()).upper()
            future = asyncio.get_running_loop().create_future()
            self._pending_acks[target] = future
            try:
                await self._mqtt.async_publish_command(
                    topic=OBSERVED_MQTT_FILTER,
                    target=target,
                    body=data,
                    request_id=request_id,
                )
                remote_code = await asyncio.wait_for(
                    future,
                    timeout=COMMAND_ACK_TIMEOUT,
                )
            finally:
                self._pending_acks.pop(target, None)
            if remote_code != 0:
                raise RuntimeError(
                    f"208B command rejected: sid={sid} errcode={remote_code}"
                )

    def _parse_ring_events(
        self,
        data: Mapping[str, Any],
        timestamp: str | None,
    ) -> list[DoorbellEvent]:
        value = self._int_value_from(data.get("value"))
        if value not in RING_NAMES:
            return []
        return [
            DoorbellEvent(
                action=RING_ACTION,
                key_code=value,
                button_id=None,
                name=RING_NAMES[value],
                timestamp=timestamp,
            )
        ]

    def _handle_command_ack(
        self,
        body: Mapping[str, Any],
        header: Mapping[str, Any],
    ) -> bool:
        target = header.get("from")
        if not isinstance(target, str):
            return False
        future = self._pending_acks.get(target)
        if future is None or future.done():
            return False
        try:
            remote_code = int(body.get("errcode"))
        except (TypeError, ValueError):
            remote_code = -1
        future.set_result(remote_code)
        return True

    def _notify_event(self, event: DoorbellEvent) -> None:
        for listener in tuple(self._event_listeners):
            listener(event)

    @staticmethod
    def _switch_service(key: str) -> str:
        if key in SWITCH_SERVICE_IDS:
            return key
        if key == MUTE_KEY:
            return SERVICE_MUTE
        raise KeyError(key)

    def _int_value(self, sid: str, name: str) -> int | None:
        return self._int_value_from(self.value(sid, name))

    @staticmethod
    def _int_value_from(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return None
        return None

    def _bool_value(self, sid: str, name: str) -> bool | None:
        value = self.value(sid, name)
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "on"}:
                return True
            if normalized in {"0", "false", "off"}:
                return False
        if isinstance(value, (bool, int, float)):
            return bool(value)
        return None

    @staticmethod
    def _validated_volume(value: float) -> int:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("208B volume must be a number")
        if not 0 <= value <= 100:
            raise ValueError("208B volume must be between 0 and 100")
        volume = round(value)
        if volume % 25:
            raise ValueError("208B volume must use 25-point steps")
        return volume

    def _notify_state_changed(self) -> None:
        for listener in tuple(self._listeners):
            listener()
