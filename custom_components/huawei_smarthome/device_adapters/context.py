"""Raw device context shared by MQTT and product adapters."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from ..domain.models import (
    RemoteDeviceDescriptor,
    RemoteServiceState,
    is_older_remote_timestamp,
)
from ..mqtt.commands import HuaweiCommandGateway
from ..mqtt.protocol import decode_message
from ..mqtt_client import HuaweiMqttClient
from .api import EntitySpec, HuaweiProductAdapter


class DeviceContext:
    """One device's raw state, Profile and product adapter."""

    def __init__(
        self,
        descriptor: RemoteDeviceDescriptor,
        profile: Mapping[str, Any] | None,
        mqtt: HuaweiMqttClient,
        adapter: HuaweiProductAdapter | None,
    ) -> None:
        self.descriptor = descriptor
        self.profile = profile
        self.adapter = adapter
        self.command_gateway = HuaweiCommandGateway(mqtt)
        self._state: dict[str, dict[str, Any]] = {
            sid: dict(service.data)
            for sid, service in descriptor.service_states.items()
        }
        self._timestamps: dict[str, str] = {
            sid: service.reported_timestamp
            for sid, service in descriptor.service_states.items()
            if service.reported_timestamp
        }
        self._listeners: set[Callable[[], None]] = set()

    @property
    def key(self) -> tuple[str, str]:
        return self.descriptor.key

    @property
    def dev_id(self) -> str:
        return self.descriptor.dev_id

    @property
    def home_id(self) -> str:
        return self.descriptor.home_id

    @property
    def name(self) -> str:
        return self.descriptor.name

    @property
    def available(self) -> bool:
        return self.descriptor.online is not False

    @property
    def prod_id(self) -> str | None:
        return self.descriptor.prod_id

    @property
    def entity_specs(self) -> tuple[EntitySpec, ...]:
        if self.adapter is None or self.profile is None:
            return ()
        return self.adapter.entities(self)

    def has_service(self, sid: str) -> bool:
        if sid in self._state:
            return True
        services = self.profile.get("services") if self.profile else ()
        if not isinstance(services, list):
            return False
        return any(
            isinstance(service, Mapping) and service.get("serviceId") == sid
            for service in services
        )

    def value(self, sid: str, field: str) -> Any:
        return self._state.get(sid, {}).get(field)

    def service_state(self, sid: str) -> Mapping[str, Any]:
        return dict(self._state.get(sid, {}))

    async def async_send_service(
        self,
        sid: str,
        data: Mapping[str, Any],
    ) -> None:
        if not self.has_service(sid):
            raise ValueError(f"service is not present on device: {sid}")
        await self.command_gateway.async_send(
            device_id=self.dev_id,
            sid=sid,
            body=data,
        )

    def add_state_listener(self, listener: Callable[[], None]) -> None:
        self._listeners.add(listener)

    def remove_state_listener(self, listener: Callable[[], None]) -> None:
        self._listeners.discard(listener)

    def handle_mqtt_message(self, payload: bytes) -> bool:
        """Handle ACKs and raw device state without interpreting product semantics."""

        if self.command_gateway.handle_message(payload):
            return True
        message = decode_message(payload)
        if message is None or message.notify_type != "deviceDataChanged":
            return False
        if message.body.get("devId") != self.dev_id:
            return False
        services = message.body.get("services")
        if not isinstance(services, list):
            return False
        changed = self.descriptor.online is not True
        if changed:
            self.descriptor = replace(self.descriptor, online=True)
        for item in services:
            if not isinstance(item, Mapping):
                continue
            sid = item.get("sid")
            data = item.get("data")
            if not isinstance(sid, str) or not isinstance(data, Mapping):
                continue
            changed = self._merge_state(
                sid,
                data,
                item.get("ts"),
            ) or changed
        if changed:
            self._notify_state_changed()
        return changed

    def apply_state_snapshot(
        self,
        services: Mapping[str, RemoteServiceState],
        *,
        online: bool | None = None,
    ) -> bool:
        changed = False
        for sid, service in services.items():
            changed = self._merge_state(
                sid,
                service.data,
                service.reported_timestamp,
            ) or changed
        if online is not None and online != self.descriptor.online:
            self.descriptor = replace(self.descriptor, online=online)
            changed = True
        if changed:
            self._notify_state_changed()
        return changed

    def update(
        self,
        descriptor: RemoteDeviceDescriptor,
        profile: Mapping[str, Any] | None,
        adapter: HuaweiProductAdapter | None,
    ) -> None:
        self.descriptor = descriptor
        self.profile = profile
        self.adapter = adapter
        for sid, service in descriptor.service_states.items():
            if sid not in self._state:
                self._state[sid] = dict(service.data)
            if sid not in self._timestamps and service.reported_timestamp:
                self._timestamps[sid] = service.reported_timestamp

    def close(self) -> None:
        self.command_gateway.close()
        self._listeners.clear()

    def _merge_state(
        self,
        sid: str,
        data: Mapping[str, Any],
        timestamp: Any,
    ) -> bool:
        incoming_timestamp = timestamp if isinstance(timestamp, str) else None
        previous_timestamp = self._timestamps.get(sid)
        if is_older_remote_timestamp(incoming_timestamp, previous_timestamp):
            return False
        before = self._state.get(sid, {})
        after = {**before, **dict(data)}
        changed = after != before
        self._state[sid] = after
        if incoming_timestamp:
            self._timestamps[sid] = incoming_timestamp
        return changed

    def _notify_state_changed(self) -> None:
        for listener in tuple(self._listeners):
            listener()
