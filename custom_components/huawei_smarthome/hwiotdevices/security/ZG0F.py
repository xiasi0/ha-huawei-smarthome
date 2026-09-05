"""Explicit Huawei SmartHome model for the ZG0F AI human sensor."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from typing import Any

from ...domain.models import RemoteDeviceDescriptor
from ...mqtt_client import HuaweiMqttClient
from ..state import HuaweiDeviceStateMixin

PROD_ID = "ZG0F"
HA_PLATFORM = "binary_sensor"
MANUFACTURER_NAME = "华为"
PROFILE_MODEL = "BER-SE00"

SERVICE_LUMINANCE = "luminance"
SERVICE_BASIC_FENCE_EVENT = "basicFenceEvent"
USER_FENCE_EVENT_SERVICES = tuple(
    f"userFenceEvent{index}"
    for index in range(1, 7)
)
STATE_SERVICES = frozenset(
    {
        SERVICE_LUMINANCE,
        SERVICE_BASIC_FENCE_EVENT,
        *USER_FENCE_EVENT_SERVICES,
    }
)

MAIN_STANDING_KEY = "standing"
ZONE_PRESENCE_KEYS = tuple(
    f"zone_{index}_presence"
    for index in range(1, 7)
)
ZONE_STANDING_KEYS = tuple(
    f"zone_{index}_standing"
    for index in range(1, 7)
)
ZONE_PRESENCE_SERVICE_BY_KEY = dict(
    zip(ZONE_PRESENCE_KEYS, USER_FENCE_EVENT_SERVICES, strict=True)
)
ZONE_STANDING_SERVICE_BY_KEY = dict(
    zip(ZONE_STANDING_KEYS, USER_FENCE_EVENT_SERVICES, strict=True)
)
BINARY_SENSOR_KEYS = (
    MAIN_STANDING_KEY,
    *ZONE_PRESENCE_KEYS,
    *ZONE_STANDING_KEYS,
)
BINARY_SENSOR_NAMES = {
    MAIN_STANDING_KEY: "Standing",
    **{
        key: f"Zone {index} presence"
        for index, key in enumerate(ZONE_PRESENCE_KEYS, start=1)
    },
    **{
        key: f"Zone {index} standing"
        for index, key in enumerate(ZONE_STANDING_KEYS, start=1)
    },
}
SENSOR_KEYS = ("illuminance", "light_level")

StateListener = Callable[[], None]


class HuaweiDevice(HuaweiDeviceStateMixin):
    """Runtime context and protocol mapping for one ZG0F device."""

    prod_id = PROD_ID
    ha_platform = HA_PLATFORM
    state_services = STATE_SERVICES
    binary_sensor_keys = BINARY_SENSOR_KEYS
    binary_sensor_names = BINARY_SENSOR_NAMES
    sensor_keys = SENSOR_KEYS

    def __init__(
        self,
        descriptor: RemoteDeviceDescriptor,
        mqtt: HuaweiMqttClient,
    ) -> None:
        if (descriptor.prod_id or "").strip().upper() != PROD_ID:
            raise ValueError("ZG0F device requires prodId=ZG0F")
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
    def is_present(self) -> bool | None:
        """Return whether the basic sensing area currently has a person."""

        return self._bool_value(SERVICE_BASIC_FENCE_EVENT, "existent")

    def binary_sensor_is_on(self, key: str) -> bool | None:
        """Return one standing or user-area presence state."""

        if key == MAIN_STANDING_KEY:
            return self._bool_value(
                SERVICE_BASIC_FENCE_EVENT,
                "standingExistent",
            )
        if key in ZONE_PRESENCE_SERVICE_BY_KEY:
            return self._bool_value(
                ZONE_PRESENCE_SERVICE_BY_KEY[key],
                "existent",
            )
        if key in ZONE_STANDING_SERVICE_BY_KEY:
            return self._bool_value(
                ZONE_STANDING_SERVICE_BY_KEY[key],
                "standingExistent",
            )
        raise ValueError(f"unsupported ZG0F binary sensor: {key}")

    @property
    def illuminance(self) -> int | None:
        """Return the current illuminance in lux."""

        return self._int_value(SERVICE_LUMINANCE, "current")

    @property
    def light_level(self) -> int | None:
        """Return the discrete light level reported by the device."""

        value = self._int_value(SERVICE_LUMINANCE, "level")
        return value if value is not None and 1 <= value <= 6 else None

    def value(self, sid: str, name: str) -> Any:
        """Return one cached product characteristic."""

        return self._state.get(sid, {}).get(name)

    def add_state_listener(self, listener: StateListener) -> None:
        self._listeners.add(listener)

    def remove_state_listener(self, listener: StateListener) -> None:
        self._listeners.discard(listener)

    def update_descriptor(self, descriptor: RemoteDeviceDescriptor) -> None:
        """Update discovery metadata without replacing newer live state."""

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
        """Consume one official SmartHome state envelope."""

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
