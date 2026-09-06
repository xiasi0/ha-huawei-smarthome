"""Explicit Huawei SmartHome model for the 2QBO air quality detector."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from typing import Any

from ...domain.models import RemoteDeviceDescriptor
from ...mqtt_client import HuaweiMqttClient
from ..state import HuaweiDeviceStateMixin

PROD_ID = "2QBO"
MANUFACTURER_NAME = "豪恩"
PROFILE_MODEL = "LH-335WF"

SERVICE_CO2 = "co2"
SERVICE_HCHO = "hcho"
SERVICE_BATTERY = "battery"
SERVICE_HEAT = "heat"
SERVICE_HUMIDITY = "humidity"
SERVICE_MOISTURE = "moisture"
SERVICE_TEMPERATURE = "temperature"

STATE_SERVICES = frozenset(
    {
        SERVICE_CO2,
        SERVICE_HCHO,
        SERVICE_BATTERY,
        SERVICE_HEAT,
        SERVICE_HUMIDITY,
        SERVICE_MOISTURE,
        SERVICE_TEMPERATURE,
    }
)
SENSOR_KEYS = frozenset(
    {
        "co2",
        "formaldehyde",
        "temperature",
        "humidity",
        "battery_level",
    }
)

StateListener = Callable[[], None]


class HuaweiDevice(HuaweiDeviceStateMixin):
    """Runtime context and protocol mapping for one 2QBO device."""

    prod_id = PROD_ID
    state_services = STATE_SERVICES
    sensor_keys = SENSOR_KEYS

    def __init__(
        self,
        descriptor: RemoteDeviceDescriptor,
        mqtt: HuaweiMqttClient,
    ) -> None:
        if (descriptor.prod_id or "").strip().upper() != PROD_ID:
            raise ValueError("2QBO device requires prodId=2QBO")
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

    @property
    def co2(self) -> int | float | None:
        """Return the current CO2 concentration."""

        return self._number_value(SERVICE_CO2, "current")

    @property
    def formaldehyde(self) -> float | None:
        """Return formaldehyde in mg/m³ using the precise field when present."""

        precise = self._number_value(SERVICE_HCHO, "currentFloat")
        if precise is not None:
            return float(precise)
        raw = self._number_value(SERVICE_HCHO, "current")
        if raw is None:
            return None
        return float(raw) / 1000

    @property
    def temperature(self) -> float | None:
        """Return the canonical temperature reading in degrees Celsius."""

        value = self._number_value(SERVICE_TEMPERATURE, "currentFloat")
        if value is None:
            value = self._number_value(SERVICE_HEAT, "currentFloat")
        return None if value is None else float(value)

    @property
    def humidity(self) -> float | None:
        """Return the canonical humidity reading as a percentage."""

        value = self._number_value(SERVICE_HUMIDITY, "currentFloat")
        if value is None:
            value = self._number_value(SERVICE_MOISTURE, "current")
        if value is None:
            value = self._number_value(SERVICE_HUMIDITY, "current")
        return None if value is None else float(value)

    @property
    def battery_level(self) -> int | None:
        """Return the remaining battery level as a percentage."""

        value = self._number_value(SERVICE_BATTERY, "level")
        if value is None:
            return None
        return min(max(int(value), 0), 100)

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

    def _number_value(self, sid: str, name: str) -> int | float | None:
        value = self.value(sid, name)
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            try:
                return float(value) if "." in value else int(value)
            except ValueError:
                return None
        return None

    def _notify_state_changed(self) -> None:
        for listener in tuple(self._listeners):
            listener()
