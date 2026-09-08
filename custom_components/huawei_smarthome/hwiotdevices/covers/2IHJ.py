"""Explicit Huawei SmartHome model for product 2IHJ curtain motors."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
import json
from typing import Any
import uuid

from ...const import OBSERVED_MQTT_FILTER
from ...domain.models import RemoteDeviceDescriptor
from ...mqtt_client import HuaweiMqttClient
from ..state import HuaweiDeviceStateMixin

PROD_ID = "2IHJ"
HA_PLATFORM = "cover"
COVER_ENTITY_NAME = "Curtain"
MANUFACTURER_NAME = "广东朗森机电有限公司"
PROFILE_MODEL = "LS82"
COMMAND_ACK_TIMEOUT = 10.0

SERVICE_OPENER = "opener"
SERVICE_ACTION = "action"

ACTION_CLOSE = 0
ACTION_OPEN = 1
ACTION_PAUSE = 2

STATE_SERVICES = frozenset({SERVICE_OPENER, SERVICE_ACTION})
COMMAND_SERVICES = frozenset({SERVICE_OPENER, SERVICE_ACTION})

StateListener = Callable[[], None]


class HuaweiDevice(HuaweiDeviceStateMixin):
    """Runtime context and protocol mapping for one 2IHJ device."""

    prod_id = PROD_ID
    ha_platform = HA_PLATFORM
    cover_entity_name = COVER_ENTITY_NAME
    state_services = STATE_SERVICES

    def __init__(
        self,
        descriptor: RemoteDeviceDescriptor,
        mqtt: HuaweiMqttClient,
    ) -> None:
        if (descriptor.prod_id or "").strip().upper() != PROD_ID:
            raise ValueError("2IHJ device requires prodId=2IHJ")
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
    def current_position(self) -> int | None:
        value = self._int_value(SERVICE_OPENER, "current")
        if value is None:
            return None
        return min(max(value, 0), 100)

    @property
    def action(self) -> int | None:
        return self._int_value(SERVICE_ACTION, "action")

    @property
    def is_closed(self) -> bool | None:
        position = self.current_position
        if position is not None:
            return position == 0
        if self.action == ACTION_CLOSE:
            return True
        if self.action == ACTION_OPEN:
            return False
        return None

    def value(self, sid: str, name: str) -> Any:
        """Return one cached 2IHJ characteristic."""

        return self._state.get(sid, {}).get(name)

    def add_state_listener(self, listener: StateListener) -> None:
        self._listeners.add(listener)

    def remove_state_listener(self, listener: StateListener) -> None:
        self._listeners.discard(listener)

    def update_descriptor(self, descriptor: RemoteDeviceDescriptor) -> None:
        """Update metadata without replacing newer 2IHJ state."""

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
            changed = (
                self._merge_service_state(sid, data, service.get("ts"))
                or changed
            )
        if changed:
            self._notify_state_changed()
        return changed

    async def async_open_cover(self) -> None:
        """Open the 2IHJ curtain."""

        await self.async_set_service(SERVICE_ACTION, {"action": ACTION_OPEN})

    async def async_close_cover(self) -> None:
        """Close the 2IHJ curtain."""

        await self.async_set_service(SERVICE_ACTION, {"action": ACTION_CLOSE})

    async def async_stop_cover(self) -> None:
        """Pause the 2IHJ curtain motor."""

        await self.async_set_service(SERVICE_ACTION, {"action": ACTION_PAUSE})

    async def async_set_cover_position(self, position: int) -> None:
        """Set the 2IHJ target opening percentage directly."""

        self._check_range(position, 0, 100, "position")
        await self.async_set_service(
            SERVICE_OPENER,
            {"target": position},
        )

    async def async_set_service(
        self,
        sid: str,
        data: dict[str, Any],
    ) -> None:
        """Publish one hard-coded 2IHJ service command and await its ACK."""

        if sid not in COMMAND_SERVICES:
            raise ValueError(f"unsupported 2IHJ service: {sid}")
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
                    f"2IHJ command rejected: sid={sid} errcode={remote_code}"
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
        try:
            remote_code = int(body.get("errcode"))
        except (TypeError, ValueError):
            remote_code = -1
        future.set_result(remote_code)
        return True

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

    def _notify_state_changed(self) -> None:
        for listener in tuple(self._listeners):
            listener()

    @staticmethod
    def _check_range(value: int, minimum: int, maximum: int, name: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} must be an integer")
        if not minimum <= value <= maximum:
            raise ValueError(f"{name} must be between {minimum} and {maximum}")
