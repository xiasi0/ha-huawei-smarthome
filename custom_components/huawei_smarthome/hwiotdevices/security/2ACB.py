"""Explicit Huawei SmartHome model for the 2ACB Linptech doorbell."""

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

PROD_ID = "2ACB"
MANUFACTURER_NAME = "领普科技"
PROFILE_MODEL = "G4L-HW"
PROFILE_NAME = "领普自发电无线门铃"
COMMAND_ACK_TIMEOUT = 10.0

SERVICE_VOLUME = "volume"
SERVICE_SELECT_MUSIC = "selectmusic"
SERVICE_BELL_STATUS = "bellstatus"
STATE_SERVICES = frozenset(
    {SERVICE_VOLUME, SERVICE_SELECT_MUSIC, SERVICE_BELL_STATUS}
)
COMMAND_SERVICES = frozenset({SERVICE_VOLUME, SERVICE_SELECT_MUSIC})

BUTTON_PRESSED_ACTION = "button_pressed"
BUTTON_ACTIONS = (BUTTON_PRESSED_ACTION,)
BUTTON_EVENT_NAMES = {BUTTON_PRESSED_ACTION: "Button pressed"}

RINGTONE_NAMES = (
    "静音",
    "叮咚2声（缓）",
    "叮咚2声（快）",
    "叮咚1声",
    "西敏寺钟声",
    "致爱丽丝",
    "雨中旋律",
    "回忆",
    "喀秋莎",
    "土耳其进行曲",
    "小天鹅",
    "爱的罗曼史",
    "午夜睡眠",
    "匈牙利舞曲",
    "抒情曲",
    "幻想舞曲",
    "铃儿叮当响",
    "桂河大桥",
    "命运舞曲",
    "恭喜恭喜",
    "莫斯科郊外的晚上",
    "干簧管波尔卡",
    "老黑奴",
    "绿柚子",
    "勃拉姆斯摇篮曲",
    "警报6秒",
    "苏珊娜",
    "威廉泰尔序曲",
    "摇篮曲",
    "红河谷",
    "泰坦尼克号",
    "华尔兹舞曲",
    "圆舞曲",
    "警犬叔叔",
    "小美人鱼",
    "小企鹅",
    "罗密欧与朱丽叶",
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
    """One button press reported by the 2ACB device."""

    action: str
    key_code: int
    button_id: int | None
    name: str | None
    timestamp: str | None


EventListener = Callable[[DoorbellEvent], None]


class HuaweiDevice(HuaweiDeviceStateMixin):
    """Runtime context and protocol mapping for one 2ACB device."""

    prod_id = PROD_ID
    profile_model = PROFILE_MODEL
    state_services = STATE_SERVICES
    command_services = COMMAND_SERVICES
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
            raise ValueError("2ACB device requires prodId=2ACB")
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

    def select_value(self, key: str) -> str | None:
        if key not in SELECT_KEYS:
            raise ValueError(f"unsupported 2ACB select: {key}")
        value = self._int_value(SERVICE_SELECT_MUSIC, "selectmusic")
        return RINGTONE_BY_VALUE.get(value)

    def number_value(self, key: str) -> float | None:
        if key not in NUMBER_KEYS:
            raise ValueError(f"unsupported 2ACB number: {key}")
        value = self._int_value(SERVICE_VOLUME, "volume")
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
            if sid == SERVICE_BELL_STATUS and not is_older_remote_timestamp(
                timestamp,
                self._state_timestamps.get(sid),
            ):
                events.extend(self._parse_bell_events(data, timestamp))
            changed = self._merge_service_state(sid, data, timestamp) or changed

        if changed:
            self._notify_state_changed()
        for event in events:
            self._notify_event(event)
        return changed

    async def async_select_option(self, key: str, option: str) -> None:
        if key not in SELECT_KEYS:
            raise ValueError(f"unsupported 2ACB select: {key}")
        try:
            value = RINGTONE_VALUE_BY_NAME[option]
        except KeyError as error:
            raise ValueError(f"unsupported 2ACB ringtone: {option}") from error
        await self.async_set_service(
            SERVICE_SELECT_MUSIC,
            {"selectmusic": value},
        )

    async def async_set_number(self, key: str, value: float) -> None:
        if key not in NUMBER_KEYS:
            raise ValueError(f"unsupported 2ACB number: {key}")
        volume = self._validated_volume(value)
        await self.async_set_service(SERVICE_VOLUME, {"volume": volume})

    async def async_set_service(self, sid: str, data: dict[str, Any]) -> None:
        if sid not in COMMAND_SERVICES:
            raise ValueError(f"unsupported 2ACB service: {sid}")
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
                    f"2ACB command rejected: sid={sid} errcode={remote_code}"
                )

    def _parse_bell_events(
        self,
        data: Mapping[str, Any],
        timestamp: str | None,
    ) -> list[DoorbellEvent]:
        button_id = self._int_value_from(data.get("status"))
        if button_id is None or not 1 <= button_id <= 15:
            return []
        return [
            DoorbellEvent(
                action=BUTTON_PRESSED_ACTION,
                key_code=button_id,
                button_id=button_id,
                name=f"Button {button_id}",
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

    @staticmethod
    def _validated_volume(value: float) -> int:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("2ACB volume must be a number")
        if not 0 <= value <= 100:
            raise ValueError("2ACB volume must be between 0 and 100")
        volume = round(value)
        if volume % 25:
            raise ValueError("2ACB volume must use 25-point steps")
        return volume

    def _notify_state_changed(self) -> None:
        for listener in tuple(self._listeners):
            listener()
