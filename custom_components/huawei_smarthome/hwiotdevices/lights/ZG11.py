"""Explicit Huawei SmartHome model for the ZG11 PLC switch."""

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

PROD_ID = "ZG11"
PROFILE_MODEL = "OSLO-SS3"
MANUFACTURER_NAME = "华为"
COMMAND_ACK_TIMEOUT = 10.0

SERVICE_SCENE = "scene"
SCENE_ACTION_FIELDS = {
    "num": "single",
    "DoubleClick": "double",
    "LongClick": "long",
}
BUTTON_ACTIONS = tuple(SCENE_ACTION_FIELDS.values())
CHANNEL_SERVICE_IDS = ("switch1", "switch2", "switch3")
BUTTON_SERVICE_IDS = ("button1", "button2", "button3")
MODE_SERVICE_IDS = ("mode1", "mode2", "mode3")
STATE_SERVICES = frozenset(
    {
        SERVICE_SCENE,
        *CHANNEL_SERVICE_IDS,
        *BUTTON_SERVICE_IDS,
        *MODE_SERVICE_IDS,
    }
)
COMMAND_SERVICES = frozenset({*CHANNEL_SERVICE_IDS, *MODE_SERVICE_IDS})
SWITCH_NAMES = {
    "switch1": "Switch 1",
    "switch2": "Switch 2",
    "switch3": "Switch 3",
}
MODE_BY_OPTION = {"Switch mode": 1, "Scene mode": 2}
OPTION_BY_MODE = {value: key for key, value in MODE_BY_OPTION.items()}
SELECT_NAMES = {
    service_id: f"Button {index} mode"
    for index, service_id in enumerate(MODE_SERVICE_IDS, start=1)
}
SELECT_OPTIONS = {
    service_id: ("Switch mode", "Scene mode")
    for service_id in MODE_SERVICE_IDS
}

StateListener = Callable[[], None]


@dataclass(frozen=True, slots=True)
class WirelessSwitchEvent:
    """One physical key action reported by the ZG11 device."""

    action: str
    key_code: int
    button_id: int | None
    name: str | None
    timestamp: str | None


EventListener = Callable[[WirelessSwitchEvent], None]


class HuaweiDevice(HuaweiDeviceStateMixin):
    """Runtime context and protocol mapping for one ZG11 device."""

    prod_id = PROD_ID
    profile_model = PROFILE_MODEL
    ha_platform = "switch"
    expose_aggregate_switch = False
    state_services = STATE_SERVICES
    command_services = COMMAND_SERVICES
    switch_keys = CHANNEL_SERVICE_IDS
    switch_names = SWITCH_NAMES
    button_service_ids = BUTTON_SERVICE_IDS
    button_event_actions = BUTTON_ACTIONS
    select_keys = MODE_SERVICE_IDS
    select_names = SELECT_NAMES
    select_options = SELECT_OPTIONS

    def __init__(self, descriptor: RemoteDeviceDescriptor, mqtt: HuaweiMqttClient) -> None:
        if (descriptor.prod_id or "").strip().upper() != PROD_ID:
            raise ValueError("ZG11 device requires prodId=ZG11")
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
        return self._descriptor.name

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

    @property
    def button_count(self) -> int:
        return len(BUTTON_SERVICE_IDS)

    def feature_is_on(self, characteristic: str) -> bool | None:
        if characteristic not in self.switch_keys:
            raise ValueError(f"unsupported ZG11 switch: {characteristic}")
        return self._bool_value(characteristic, "on")

    def select_value(self, key: str) -> str | None:
        if key not in self.select_keys:
            raise ValueError(f"unsupported ZG11 select: {key}")
        return OPTION_BY_MODE.get(self._int_value(key, "mode"))

    async def async_select_option(self, key: str, option: str) -> None:
        if key not in self.select_keys:
            raise ValueError(f"unsupported ZG11 select: {key}")
        try:
            mode = MODE_BY_OPTION[option]
        except KeyError as error:
            raise ValueError(f"unsupported ZG11 mode option: {option}") from error
        await self.async_set_service(key, {"mode": mode})

    def value(self, sid: str, name: str) -> Any:
        return self._state.get(sid, {}).get(name)

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
        events: list[WirelessSwitchEvent] = []
        for service in services:
            if not isinstance(service, Mapping):
                continue
            sid = service.get("sid")
            data = service.get("data")
            if not isinstance(sid, str) or not isinstance(data, Mapping):
                continue
            timestamp = service.get("ts")
            timestamp = timestamp if isinstance(timestamp, str) else None
            if sid == SERVICE_SCENE and not is_older_remote_timestamp(
                timestamp,
                self._state_timestamps.get(sid),
            ):
                events.extend(self._parse_scene_events(data, timestamp))
            changed = self._merge_service_state(sid, data, timestamp) or changed
        if changed:
            self._notify_state_changed()
        for event in events:
            self._notify_event(event)
        return changed

    async def async_set_feature(self, characteristic: str, enabled: bool) -> None:
        if characteristic not in self.switch_keys:
            raise ValueError(f"unsupported ZG11 switch: {characteristic}")
        await self.async_set_service(characteristic, {"on": 1 if enabled else 0})

    async def async_set_service(self, sid: str, data: dict[str, Any]) -> None:
        if sid not in COMMAND_SERVICES:
            raise ValueError(f"unsupported ZG11 service: {sid}")
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
                remote_code = await asyncio.wait_for(future, timeout=COMMAND_ACK_TIMEOUT)
            finally:
                self._pending_acks.pop(target, None)
            if remote_code != 0:
                raise RuntimeError(
                    f"ZG11 command rejected: sid={sid} errcode={remote_code}"
                )

    def _handle_command_ack(self, body: Mapping[str, Any], header: Mapping[str, Any]) -> bool:
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

    def _parse_scene_events(
        self,
        data: Mapping[str, Any],
        timestamp: str | None,
    ) -> list[WirelessSwitchEvent]:
        events = []
        for field, action in SCENE_ACTION_FIELDS.items():
            key_code = self._int_from_value(data.get(field))
            if key_code is None or key_code <= 0:
                continue
            button_id, name = self._button_for_code(key_code)
            events.append(WirelessSwitchEvent(action, key_code, button_id, name, timestamp))
        return events

    def _button_for_code(self, key_code: int) -> tuple[int | None, str | None]:
        configured = False
        for index, sid in enumerate(BUTTON_SERVICE_IDS, start=1):
            value = self._int_value(sid, "num")
            if value is not None and value > 0:
                configured = True
            if value == key_code:
                return index, self._button_name(sid)
        if not configured and 1 <= key_code <= self.button_count:
            sid = BUTTON_SERVICE_IDS[key_code - 1]
            return key_code, self._button_name(sid)
        return None, None

    def _button_name(self, sid: str) -> str | None:
        value = self.value(sid, "name")
        return value.strip() if isinstance(value, str) and value.strip() else None

    def _notify_event(self, event: WirelessSwitchEvent) -> None:
        for listener in tuple(self._event_listeners):
            listener(event)

    def _int_value(self, sid: str, name: str) -> int | None:
        return self._int_from_value(self.value(sid, name))

    @staticmethod
    def _int_from_value(value: Any) -> int | None:
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

    def _notify_state_changed(self) -> None:
        for listener in tuple(self._listeners):
            listener()
