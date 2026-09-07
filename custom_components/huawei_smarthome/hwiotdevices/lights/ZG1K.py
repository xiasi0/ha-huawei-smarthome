"""Explicit Huawei SmartHome model for the ZG1K MINI Pro button."""

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

PROD_ID = "ZG1K"
PROFILE_MODEL = "MINI-MLG320"
PROFILE_NAME = "华为鸿蒙智家 智能MINI Pro"
MANUFACTURER_NAME = "华为"

SERVICE_SCENE = "scene"
SERVICE_BATTERY = "battery"
SERVICE_ROTATION_MODE = "rotationMode"
STATE_SERVICES = frozenset(
    {SERVICE_SCENE, SERVICE_BATTERY, SERVICE_ROTATION_MODE}
)

SCENE_ACTION_FIELDS = {
    "num": "single",
    "doubleClick": "double",
    "longClick": "long",
}
BUTTON_ACTIONS = tuple(SCENE_ACTION_FIELDS.values())
BUTTON_COUNT = 20
SENSOR_KEYS = ("battery_level", "rotation_mode")
BINARY_SENSOR_KEYS: tuple[str, ...] = ()
ROTATION_MODE_NAMES = {
    0: "No config",
    1: "Light",
    2: "Music",
    3: "Sunshade",
}

StateListener = Callable[[], None]


@dataclass(frozen=True, slots=True)
class WirelessSwitchEvent:
    """One physical key action reported by the ZG1K device."""

    action: str
    key_code: int
    button_id: int | None
    name: str | None
    timestamp: str | None


EventListener = Callable[[WirelessSwitchEvent], None]


class HuaweiDevice(HuaweiDeviceStateMixin):
    """Runtime context and protocol mapping for one ZG1K device."""

    prod_id = PROD_ID
    profile_model = PROFILE_MODEL
    state_services = STATE_SERVICES
    button_event_actions = BUTTON_ACTIONS
    sensor_keys = SENSOR_KEYS
    binary_sensor_keys = BINARY_SENSOR_KEYS

    def __init__(
        self,
        descriptor: RemoteDeviceDescriptor,
        mqtt: HuaweiMqttClient,
    ) -> None:
        if (descriptor.prod_id or "").strip().upper() != PROD_ID:
            raise ValueError("ZG1K device requires prodId=ZG1K")
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

    @property
    def button_count(self) -> int:
        return BUTTON_COUNT

    @property
    def battery_level(self) -> int | None:
        value = self._int_value(SERVICE_BATTERY, "level")
        if value is None:
            return None
        return min(max(value, 0), 100)

    @property
    def rotation_mode(self) -> str | None:
        return ROTATION_MODE_NAMES.get(
            self._int_value(SERVICE_ROTATION_MODE, "mode")
        )

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

    def _parse_scene_events(
        self,
        data: Mapping[str, Any],
        timestamp: str | None,
    ) -> list[WirelessSwitchEvent]:
        events: list[WirelessSwitchEvent] = []
        for field, action in SCENE_ACTION_FIELDS.items():
            key_code = self._int_from_value(data.get(field))
            if key_code is None or not 1 <= key_code <= BUTTON_COUNT:
                continue
            events.append(
                WirelessSwitchEvent(
                    action=action,
                    key_code=key_code,
                    button_id=None,
                    name=None,
                    timestamp=timestamp,
                )
            )
        return events

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

    def _notify_state_changed(self) -> None:
        for listener in tuple(self._listeners):
            listener()
