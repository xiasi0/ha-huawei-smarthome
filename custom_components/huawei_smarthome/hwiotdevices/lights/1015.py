"""Explicit Huawei SmartHome model for the 1015 four-key controller."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from typing import Any

from ...domain.models import (
    RemoteDeviceDescriptor,
    is_older_remote_timestamp,
)
from ...mqtt_client import HuaweiMqttClient
from ..state import HuaweiDeviceStateMixin

PROD_ID = "1015"
MANUFACTURER_NAME = "中安消物联传感"
PROFILE_MODEL = "B910ZB"
PROFILE_NAME = "四键遥控器"

SERVICE_KEY_EVENT = "keyEvent"
STATE_SERVICES = frozenset({SERVICE_KEY_EVENT})

KEY_EVENT_ACTION = "key_event"
BUTTON_ACTIONS = (KEY_EVENT_ACTION,)
BUTTON_EVENT_NAMES = {KEY_EVENT_ACTION: "Key event"}
KEY_NAMES = {
    1: "Away arm",
    2: "Home arm",
    3: "Disarm",
    4: "Emergency help",
}

StateListener = Callable[[], None]


@dataclass(frozen=True, slots=True)
class WirelessSwitchEvent:
    """One physical key action reported by the 1015 device."""

    action: str
    key_code: int
    button_id: int | None
    name: str | None
    timestamp: str | None


EventListener = Callable[[WirelessSwitchEvent], None]


class HuaweiDevice(HuaweiDeviceStateMixin):
    """Runtime context and protocol mapping for one 1015 device."""

    prod_id = PROD_ID
    profile_model = PROFILE_MODEL
    state_services = STATE_SERVICES
    button_event_actions = BUTTON_ACTIONS
    button_event_names = BUTTON_EVENT_NAMES

    def __init__(
        self,
        descriptor: RemoteDeviceDescriptor,
        mqtt: HuaweiMqttClient,
    ) -> None:
        if (descriptor.prod_id or "").strip().upper() != PROD_ID:
            raise ValueError("1015 device requires prodId=1015")
        self._descriptor = descriptor
        del mqtt
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
        self._listeners.clear()
        self._event_listeners.clear()

    def handle_mqtt_message(self, topic: str, payload: bytes) -> bool:
        """Consume one official SmartHome device state message."""

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
        if (
            header.get("notifyType") != "deviceDataChanged"
            or body.get("devId") != self.dev_id
        ):
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
            if sid == SERVICE_KEY_EVENT and not is_older_remote_timestamp(
                timestamp,
                self._state_timestamps.get(sid),
            ):
                events.extend(self._parse_key_events(data, timestamp))
            changed = self._merge_service_state(sid, data, timestamp) or changed

        if changed:
            self._notify_state_changed()
        for event in events:
            self._notify_event(event)
        return changed

    def _parse_key_events(
        self,
        data: Mapping[str, Any],
        timestamp: str | None,
    ) -> list[WirelessSwitchEvent]:
        key_code = self._int_from_value(data.get("key"))
        if key_code not in KEY_NAMES:
            return []
        return [
            WirelessSwitchEvent(
                action=KEY_EVENT_ACTION,
                key_code=key_code,
                button_id=key_code,
                name=KEY_NAMES[key_code],
                timestamp=timestamp,
            )
        ]

    def _notify_event(self, event: WirelessSwitchEvent) -> None:
        for listener in tuple(self._event_listeners):
            listener(event)

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

    def _notify_state_changed(self) -> None:
        for listener in tuple(self._listeners):
            listener()
