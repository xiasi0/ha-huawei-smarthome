"""Explicit Huawei SmartHome model for the 2BE7 water detector."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from typing import Any

from ...domain.models import RemoteDeviceDescriptor
from ...mqtt_client import HuaweiMqttClient
from ..state import HuaweiDeviceStateMixin

PROD_ID = "2BE7"
MANUFACTURER_NAME = "麦乐克"
PROFILE_MODEL = "MIR-WA100"

SERVICE_ALARM = "alarm"
SERVICE_BATTERY = "battery"
STATE_SERVICES = frozenset({SERVICE_ALARM, SERVICE_BATTERY})

WATER_LEAK_KEY = "water_leak"
BINARY_SENSOR_KEYS = (WATER_LEAK_KEY,)
BINARY_SENSOR_NAMES = {WATER_LEAK_KEY: "Water leak"}
BINARY_SENSOR_DEVICE_CLASSES = {WATER_LEAK_KEY: "moisture"}
SENSOR_KEYS = frozenset({"battery_level"})

StateListener = Callable[[], None]


class HuaweiDevice(HuaweiDeviceStateMixin):
    """Runtime context and protocol mapping for one 2BE7 device."""

    prod_id = PROD_ID
    binary_sensor_keys = BINARY_SENSOR_KEYS
    binary_sensor_names = BINARY_SENSOR_NAMES
    binary_sensor_device_classes = BINARY_SENSOR_DEVICE_CLASSES
    sensor_keys = SENSOR_KEYS
    state_services = STATE_SERVICES

    def __init__(
        self,
        descriptor: RemoteDeviceDescriptor,
        mqtt: HuaweiMqttClient,
    ) -> None:
        if (descriptor.prod_id or "").strip().upper() != PROD_ID:
            raise ValueError("2BE7 device requires prodId=2BE7")
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

    @property
    def descriptor(self) -> RemoteDeviceDescriptor:
        """Return the current discovered device descriptor."""

        return self._descriptor

    @property
    def key(self) -> tuple[str, str]:
        """Return the stable account/device key."""

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

    def binary_sensor_is_on(self, key: str) -> bool | None:
        """Return whether the detector currently reports water intrusion."""

        if key != WATER_LEAK_KEY:
            raise ValueError(f"unsupported 2BE7 binary sensor: {key}")
        return self._bool_value(SERVICE_ALARM, "alarm")

    @property
    def battery_level(self) -> int | None:
        """Return the remaining battery level as a percentage."""

        value = self._int_value(SERVICE_BATTERY, "level")
        if value is None:
            return None
        return min(max(value, 0), 100)

    def value(self, sid: str, name: str) -> Any:
        """Return one cached product characteristic."""

        return self._state.get(sid, {}).get(name)

    def add_state_listener(self, listener: StateListener) -> None:
        self._listeners.add(listener)

    def remove_state_listener(self, listener: StateListener) -> None:
        self._listeners.discard(listener)

    def update_descriptor(self, descriptor: RemoteDeviceDescriptor) -> None:
        """Update discovery metadata without replacing newer MQTT state."""

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
        """Release listeners."""

        self._listeners.clear()

    def handle_mqtt_message(self, topic: str, payload: bytes) -> bool:
        """Consume one official SmartHome MQTT state envelope."""

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
        for service in services:
            if not isinstance(service, Mapping):
                continue
            sid = service.get("sid")
            data = service.get("data")
            if not isinstance(sid, str) or not isinstance(data, Mapping):
                continue
            changed = (
                self._merge_service_state(sid, data, service.get("ts"))
                or changed
            )
        if changed:
            self._notify_state_changed()
        return changed

    def _int_value(self, sid: str, name: str) -> int | None:
        value = self.value(sid, name)
        if isinstance(value, bool):
            return int(value)
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
