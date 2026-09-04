"""Non-secret account discovery state persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Protocol

from ..const import STATE_STORAGE_PREFIX
from ..domain.models import (
    AccountState,
    ConnectionState,
    Operation,
    RemoteDeviceDescriptor,
    RemoteHome,
    RemoteRoom,
    RemoteServiceState,
)
from .locking import storage_lock


STATE_STORAGE_VERSION = 2


class AccountStateStore(Protocol):
    """Persistence port for one ConfigEntry's non-secret state."""

    async def async_load(self) -> AccountState | None:
        """Load the last account state."""

    async def async_save(self, state: AccountState) -> None:
        """Save account state."""

    async def async_remove(self) -> None:
        """Remove account state."""


class HomeAssistantAccountStateStore:
    """Store one account's discovery state through Home Assistant Store."""

    def __init__(self, hass: Any, entry_id: str) -> None:
        from homeassistant.helpers.storage import Store

        self._store = Store(
            hass,
            STATE_STORAGE_VERSION,
            f"{STATE_STORAGE_PREFIX}.{entry_id}.state",
        )
        self._storage_key = f"{STATE_STORAGE_PREFIX}.{entry_id}.state"

    async def async_load(self) -> AccountState | None:
        """Load validated state from Home Assistant storage."""

        async with storage_lock(self._storage_key):
            value = await self._store.async_load()
            if not isinstance(value, Mapping):
                return None
            try:
                return state_from_storage(value)
            except (TypeError, ValueError, KeyError):
                return None

    async def async_save(self, state: AccountState) -> None:
        """Save only non-secret state."""

        async with storage_lock(self._storage_key):
            await self._store.async_save(state_to_storage(state))

    async def async_remove(self) -> None:
        """Remove this ConfigEntry's state."""

        async with storage_lock(self._storage_key):
            await self._store.async_remove()


def state_to_storage(state: AccountState) -> dict[str, Any]:
    """Serialize account state to JSON-compatible values."""

    return {
        "storage_schema_version": STATE_STORAGE_VERSION,
        "homes": [_home_to_storage(home) for home in state.homes.values()],
        "devices": [_device_to_storage(device) for device in state.devices.values()],
        "device_home_index": {
            dev_id: sorted(home_ids)
            for dev_id, home_ids in state.device_home_index.items()
        },
        "selected_home_ids": sorted(state.selected_home_ids),
        "connection": state.connection.value,
        "last_snapshot_at": _datetime_to_storage(state.last_snapshot_at),
        "last_event_at": _datetime_to_storage(state.last_event_at),
        "last_success_at": _datetime_to_storage(state.last_success_at),
        "stale_since": _datetime_to_storage(state.stale_since),
        "last_error": state.last_error,
        "revision": state.revision,
    }


def state_from_storage(value: Mapping[str, Any]) -> AccountState:
    """Deserialize the current state schema without legacy migration."""

    if value.get("storage_schema_version") != STATE_STORAGE_VERSION:
        raise ValueError("unsupported SmartHome state storage version")
    homes_raw = value.get("homes", [])
    devices_raw = value.get("devices", [])
    if not isinstance(homes_raw, list) or not isinstance(devices_raw, list):
        raise ValueError("account state collections are invalid")
    homes = {
        home.home_id: home
        for item in homes_raw
        if isinstance(item, Mapping)
        for home in [_home_from_storage(item)]
    }
    devices = {
        device.key: device
        for item in devices_raw
        if isinstance(item, Mapping)
        for device in [_device_from_storage(item)]
    }
    selected = value.get("selected_home_ids", [])
    if not isinstance(selected, list) or not all(isinstance(item, str) for item in selected):
        raise ValueError("selected home ids are invalid")
    index_raw = value.get("device_home_index", {})
    if not isinstance(index_raw, Mapping):
        raise ValueError("device home index is invalid")
    device_home_index: dict[str, frozenset[str]] = {}
    for dev_id, home_ids_raw in index_raw.items():
        if isinstance(home_ids_raw, str):
            home_ids = frozenset({home_ids_raw})
        elif isinstance(home_ids_raw, list) and all(
            isinstance(item, str) and item for item in home_ids_raw
        ):
            home_ids = frozenset(home_ids_raw)
        else:
            raise ValueError("device home index entry is invalid")
        if home_ids:
            device_home_index[str(dev_id)] = home_ids
    connection = value.get("connection", ConnectionState.STOPPED.value)
    if connection not in ConnectionState._value2member_map_:
        raise ValueError("account connection state is invalid")
    revision = value.get("revision", 0)
    if not isinstance(revision, int) or revision < 0:
        raise ValueError("account state revision is invalid")
    return AccountState(
        homes=homes,
        devices=devices,
        device_home_index=device_home_index,
        selected_home_ids=frozenset(selected),
        connection=ConnectionState(connection),
        last_snapshot_at=_datetime_from_storage(value.get("last_snapshot_at")),
        last_event_at=_datetime_from_storage(value.get("last_event_at")),
        last_success_at=_datetime_from_storage(value.get("last_success_at")),
        stale_since=_datetime_from_storage(value.get("stale_since")),
        last_error=value.get("last_error") if isinstance(value.get("last_error"), str) else None,
        revision=revision,
    )


def _home_to_storage(home: RemoteHome) -> dict[str, Any]:
    return {
        "home_id": home.home_id,
        "name": home.name,
        "role": home.role,
        "rooms": [_room_to_storage(room) for room in home.rooms.values()],
    }


def _home_from_storage(value: Mapping[str, Any]) -> RemoteHome:
    home_id = _required_text(value.get("home_id"))
    name = _required_text(value.get("name"))
    rooms_raw = value.get("rooms", [])
    if not isinstance(rooms_raw, list):
        raise ValueError("home rooms are invalid")
    rooms = {
        room.room_id: room
        for item in rooms_raw
        if isinstance(item, Mapping)
        for room in [_room_from_storage(item, home_id)]
    }
    role = value.get("role") if isinstance(value.get("role"), str) else None
    return RemoteHome(home_id=home_id, name=name, role=role, rooms=rooms)


def _room_to_storage(room: RemoteRoom) -> dict[str, str]:
    return {"home_id": room.home_id, "room_id": room.room_id, "name": room.name}


def _room_from_storage(value: Mapping[str, Any], home_id: str) -> RemoteRoom:
    return RemoteRoom(
        home_id=home_id,
        room_id=_required_text(value.get("room_id")),
        name=_required_text(value.get("name")),
    )


def _device_to_storage(device: RemoteDeviceDescriptor) -> dict[str, Any]:
    return {
        "home_id": device.home_id,
        "dev_id": device.dev_id,
        "name": device.name,
        "room_id": device.room_id,
        "room_name": device.room_name,
        "gateway_id": device.gateway_id,
        "node_type": device.node_type,
        "prod_id": device.prod_id,
        "device_type_id": device.device_type_id,
        "model": device.model,
        "manufacturer": device.manufacturer,
        "manufacturer_code": device.manufacturer_code,
        "firmware_version": device.firmware_version,
        "protocol_type": device.protocol_type,
        "operations": sorted(operation.value for operation in device.operations),
        "service_states": [
            _service_state_to_storage(service)
            for service in device.service_states.values()
        ],
        "online": device.online,
        "tags": dict(device.tags),
        "third_party_id": device.third_party_id,
        "registry_time": device.registry_time,
        "discovery_metadata": dict(device.discovery_metadata),
    }


def _device_from_storage(value: Mapping[str, Any]) -> RemoteDeviceDescriptor:
    operations_raw = value.get("operations", [])
    if not isinstance(operations_raw, list):
        raise ValueError("device operations are invalid")
    operations = frozenset(
        Operation(item)
        for item in operations_raw
        if isinstance(item, str) and item in Operation._value2member_map_
    )
    services_raw = value.get("service_states", [])
    if not isinstance(services_raw, list):
        raise ValueError("device service states are invalid")
    services = {
        service.sid: service
        for item in services_raw
        if isinstance(item, Mapping)
        for service in [_service_state_from_storage(item)]
    }
    tags = value.get("tags", {})
    metadata = value.get("discovery_metadata", {})
    if not isinstance(tags, Mapping) or not isinstance(metadata, Mapping):
        raise ValueError("device metadata is invalid")
    online = value.get("online")
    return RemoteDeviceDescriptor(
        home_id=_required_text(value.get("home_id")),
        dev_id=_required_text(value.get("dev_id")),
        name=_required_text(value.get("name")),
        room_id=_optional_text(value.get("room_id")),
        room_name=_optional_text(value.get("room_name")),
        gateway_id=_optional_text(value.get("gateway_id")),
        node_type=_optional_text(value.get("node_type")),
        prod_id=_optional_text(value.get("prod_id")),
        device_type_id=_optional_text(value.get("device_type_id")),
        model=_optional_text(value.get("model")),
        manufacturer=_optional_text(value.get("manufacturer")),
        manufacturer_code=_optional_text(value.get("manufacturer_code")),
        firmware_version=_optional_text(value.get("firmware_version")),
        protocol_type=(
            value.get("protocol_type")
            if isinstance(value.get("protocol_type"), (str, int))
            else None
        ),
        operations=operations,
        service_states=services,
        online=online if isinstance(online, bool) else None,
        tags=dict(tags),
        third_party_id=_optional_text(value.get("third_party_id")),
        registry_time=_optional_text(value.get("registry_time")),
        discovery_metadata=dict(metadata),
    )


def _service_state_to_storage(service: RemoteServiceState) -> dict[str, Any]:
    return {
        "sid": service.sid,
        "service_type": service.service_type,
        "data": dict(service.data),
        "reported_timestamp": service.reported_timestamp,
        "occurred_at": _datetime_to_storage(service.occurred_at),
        "received_at": _datetime_to_storage(service.received_at),
    }


def _service_state_from_storage(value: Mapping[str, Any]) -> RemoteServiceState:
    data = value.get("data", {})
    if not isinstance(data, Mapping):
        raise ValueError("service state data is invalid")
    return RemoteServiceState(
        sid=_required_text(value.get("sid")),
        service_type=_optional_text(value.get("service_type")),
        data=dict(data),
        reported_timestamp=_optional_text(value.get("reported_timestamp")),
        occurred_at=_datetime_from_storage(value.get("occurred_at")),
        received_at=_datetime_from_storage(value.get("received_at")),
    )


def _datetime_to_storage(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _datetime_from_storage(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _required_text(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("required state text is missing")
    return value


def _optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
