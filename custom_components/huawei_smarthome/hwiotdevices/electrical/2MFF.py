"""Explicit Huawei SmartHome model for the 2MFF smart socket."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
import json
from typing import Any
import uuid

from ...const import OBSERVED_MQTT_FILTER
from ...domain.models import RemoteDeviceDescriptor
from ...mqtt_client import HuaweiMqttClient

PROD_ID = "2MFF"
HA_PLATFORM = "switch"
MANUFACTURER_NAME = "佛山照明"
PROFILE_MODEL = "Z1-Z3B-101/ZK"
COMMAND_ACK_TIMEOUT = 10.0

SERVICE_SWITCH = "switch"
SERVICE_ELECTRIC = "electric"
SERVICE_POWER = "power"
STATE_SERVICES = frozenset(
    {SERVICE_SWITCH, SERVICE_ELECTRIC, SERVICE_POWER}
)
SENSOR_KEYS = frozenset(
    {"power", "electric_current", "voltage", "total_electricity"}
)

StateListener = Callable[[], None]


class HuaweiDevice:
    """Runtime context and protocol mapping for one 2MFF device."""

    prod_id = PROD_ID
    ha_platform = HA_PLATFORM
    sensor_keys = SENSOR_KEYS

    def __init__(
        self,
        descriptor: RemoteDeviceDescriptor,
        mqtt: HuaweiMqttClient,
    ) -> None:
        if (descriptor.prod_id or "").strip().upper() != PROD_ID:
            raise ValueError("2MFF device requires prodId=2MFF")
        self._descriptor = descriptor
        self._mqtt = mqtt
        self._state: dict[str, dict[str, Any]] = {
            sid: dict(service.data)
            for sid, service in descriptor.service_states.items()
        }
        self._state_timestamps: dict[str, str] = {
            sid: service.reported_timestamp
            for sid, service in descriptor.service_states.items()
            if service.reported_timestamp
        }
        self._listeners: set[StateListener] = set()
        self._pending_acks: dict[str, asyncio.Future[int]] = {}
        self._command_lock = asyncio.Lock()

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
    def is_on(self) -> bool | None:
        return self._bool_value(SERVICE_SWITCH, "on")

    @property
    def power(self) -> int | None:
        """Return current power in watts."""

        return self._int_value(SERVICE_POWER, "current")

    @property
    def electric_current(self) -> float | None:
        """Return current in amperes; the profile reports milliamperes."""

        value = self._number_value(SERVICE_ELECTRIC, "current")
        return value / 1000 if value is not None else None

    @property
    def voltage(self) -> int | None:
        return self._int_value(SERVICE_ELECTRIC, "voltage")

    @property
    def total_electricity(self) -> int | float | None:
        """Return total electricity in kWh."""

        return self._number_value(SERVICE_ELECTRIC, "totalElectricity")

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
            if sid not in self._state:
                self._state[sid] = dict(service.data)
            if sid not in self._state_timestamps and service.reported_timestamp:
                self._state_timestamps[sid] = service.reported_timestamp
        if was_available != self.available:
            self._notify_state_changed()

    def close(self) -> None:
        """Release listeners and wake commands waiting for an ACK."""

        for future in self._pending_acks.values():
            if not future.done():
                future.cancel()
        self._pending_acks.clear()
        self._listeners.clear()

    def handle_mqtt_message(self, topic: str, payload: bytes) -> bool:
        """Consume one official SmartHome MQTT envelope."""

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
        for service in services:
            if not isinstance(service, Mapping):
                continue
            sid = service.get("sid")
            data = service.get("data")
            if (
                not isinstance(sid, str)
                or sid not in STATE_SERVICES
                or not isinstance(data, Mapping)
            ):
                continue
            timestamp = service.get("ts")
            if (
                isinstance(timestamp, str)
                and timestamp
                and self._state_timestamps.get(sid)
                and timestamp < self._state_timestamps[sid]
            ):
                continue
            before = self._state.get(sid, {})
            after = {**before, **dict(data)}
            if after != before:
                self._state[sid] = after
                changed = True
            if isinstance(timestamp, str) and timestamp:
                self._state_timestamps[sid] = timestamp
        if changed:
            self._notify_state_changed()
        return changed

    async def async_turn_on(self) -> None:
        """Turn the socket on."""

        await self.async_set_service({"on": 1})

    async def async_turn_off(self) -> None:
        """Turn the socket off."""

        await self.async_set_service({"on": 0})

    async def async_set_service(self, data: dict[str, Any]) -> None:
        """Publish a switch command and wait for its ACK."""

        target = f"/devices/{self.dev_id}/services/{SERVICE_SWITCH}"
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
                    f"2MFF command rejected: errcode={remote_code}"
                )

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
        code = body.get("errcode")
        try:
            remote_code = int(code)
        except (TypeError, ValueError):
            remote_code = -1
        future.set_result(remote_code)
        return True

    def _int_value(self, sid: str, name: str) -> int | None:
        value = self._number_value(sid, name)
        if value is None:
            return None
        return int(value) if float(value).is_integer() else None

    def _number_value(self, sid: str, name: str) -> int | float | None:
        value = self.value(sid, name)
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            try:
                return float(value) if "." in value else int(value)
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
