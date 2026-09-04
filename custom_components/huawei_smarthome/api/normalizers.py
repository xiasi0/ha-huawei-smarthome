"""Normalize SmartHome discovery responses into phase-2 domain models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from ..errors import InvalidProtocolDataError
from ..domain.models import (
    DeviceKey,
    Operation,
    RemoteDeviceDescriptor,
    RemoteDiscoverySnapshot,
    RemoteHome,
    RemoteRoom,
    RemoteServiceState,
    canonical_home_id,
    parse_remote_timestamp,
)


def normalize_snapshot(
    devices_payload: Any,
    homes_payload: Any,
    *,
    received_at: datetime | None = None,
) -> RemoteDiscoverySnapshot:
    """Normalize the two confirmed discovery responses."""

    received_at = received_at or datetime.now(timezone.utc)
    if not isinstance(devices_payload, list):
        raise InvalidProtocolDataError("device response is not a JSON list")
    if not isinstance(homes_payload, Mapping):
        raise InvalidProtocolDataError("home response is not a JSON object")

    homes_by_id = {
        home.home_id: home
        for home in _normalize_homes(homes_payload)
    }
    devices: list[RemoteDeviceDescriptor] = []
    seen_keys: set[DeviceKey] = set()
    for item in devices_payload:
        if not isinstance(item, Mapping):
            continue
        device = _normalize_device(item, received_at)
        if device.key in seen_keys:
            raise InvalidProtocolDataError(
                f"device response contains duplicate device {device.key!r}"
            )
        seen_keys.add(device.key)
        devices.append(device)
        if device.home_id in homes_by_id and device.room_id:
            home = homes_by_id[device.home_id]
            rooms = dict(home.rooms)
            rooms.setdefault(
                device.room_id,
                RemoteRoom(
                    home_id=device.home_id,
                    room_id=device.room_id,
                    name=device.room_name or device.room_id,
                ),
            )
            homes_by_id[device.home_id] = RemoteHome(
                home_id=home.home_id,
                name=home.name,
                role=home.role,
                rooms=rooms,
            )
    device_home_index: dict[str, set[str]] = {}
    for device in devices:
        device_home_index.setdefault(device.dev_id, set()).add(device.home_id)
    return RemoteDiscoverySnapshot(
        homes=tuple(homes_by_id.values()),
        devices=tuple(devices),
        received_at=received_at,
        complete=True,
        device_home_index={
            dev_id: frozenset(home_ids)
            for dev_id, home_ids in device_home_index.items()
        },
    )


def normalize_device_detail(payload: Any) -> RemoteDeviceDescriptor:
    """Normalize a single device detail response."""

    candidate = _find_device_object(payload)
    if candidate is None:
        raise InvalidProtocolDataError("device detail has no device object")
    return _normalize_device(candidate, datetime.now(timezone.utc))


def _normalize_homes(payload: Mapping[str, Any]) -> tuple[RemoteHome, ...]:
    house_infos = payload.get("houseInfos")
    if not isinstance(house_infos, list):
        raise InvalidProtocolDataError("home response has no houseInfos list")
    homes: list[RemoteHome] = []
    for item in house_infos:
        if not isinstance(item, Mapping):
            continue
        home_id = _text(item.get("homeId"))
        if not home_id:
            continue
        homes.append(
            RemoteHome(
                home_id=canonical_home_id(home_id),
                name=_text(item.get("name")) or "Huawei SmartHome",
                role=_text(item.get("role")),
            )
        )
    return tuple(homes)


def _normalize_device(
    item: Mapping[str, Any],
    received_at: datetime,
) -> RemoteDeviceDescriptor:
    dev_id = _text(item.get("devId"))
    if not dev_id:
        raise InvalidProtocolDataError("device item has no devId")
    info = item.get("devInfo")
    info = info if isinstance(info, Mapping) else {}
    name = (
        _text(item.get("devName"))
        or _text(info.get("deviceName"))
        or _text(info.get("model"))
        or "Huawei device"
    )
    services: dict[str, RemoteServiceState] = {}
    services_raw = item.get("services")
    if isinstance(services_raw, list):
        for service in services_raw:
            normalized = _normalize_service(service, received_at)
            if normalized is not None:
                services[normalized.sid] = normalized
    operations_raw = item.get("operations")
    operations = frozenset(
        Operation(value)
        for value in operations_raw if isinstance(value, str)
        and value in Operation._value2member_map_
    ) if isinstance(operations_raw, list) else frozenset()
    tags = item.get("devTags")
    tags = dict(tags) if isinstance(tags, Mapping) else {}
    discovery_metadata = {
        str(key): child
        for key, child in item.items()
        if str(key) not in {
            "devId", "devName", "homeId", "roomId", "roomName",
            "gatewayId", "nodeType", "devInfo", "services", "operations",
            "devTags", "online", "status", "thirdPartyId", "registryTime",
        }
        and _is_json_value(child)
    }
    online = item.get("online")
    if not isinstance(online, bool):
        status = _text(item.get("status"))
        online = True if status == "online" else False if status == "offline" else None
    return RemoteDeviceDescriptor(
        home_id=canonical_home_id(item.get("homeId")),
        dev_id=dev_id,
        name=name,
        room_id=_text(item.get("roomId")),
        room_name=_text(item.get("roomName")),
        gateway_id=_text(item.get("gatewayId")),
        node_type=_text(item.get("nodeType")),
        prod_id=_text(info.get("prodId")),
        device_type_id=_text(info.get("devType")),
        model=_text(info.get("model")),
        manufacturer=_text(info.get("manufacturerName")),
        manufacturer_code=_text(info.get("manu")) or _text(info.get("manufacturerId")),
        firmware_version=_text(info.get("fwv")),
        protocol_type=info.get("protType")
        if isinstance(info.get("protType"), (str, int)) else None,
        operations=operations,
        service_states=services,
        online=online if isinstance(online, bool) else None,
        tags={str(key): child for key, child in tags.items() if _is_json_value(child)},
        third_party_id=_text(item.get("thirdPartyId")),
        registry_time=_text(item.get("registryTime")),
        discovery_metadata=discovery_metadata,
    )


def _normalize_service(
    value: Any,
    received_at: datetime,
) -> RemoteServiceState | None:
    if not isinstance(value, Mapping):
        return None
    sid = _text(value.get("sid"))
    if not sid:
        return None
    data = value.get("data")
    data = {
        str(key): child
        for key, child in data.items()
        if isinstance(key, (str, int)) and _is_json_value(child)
    } if isinstance(data, Mapping) else {}
    timestamp = _text(value.get("ts"))
    return RemoteServiceState(
        sid=sid,
        service_type=_text(value.get("st")),
        data=data,
        reported_timestamp=timestamp,
        occurred_at=parse_remote_timestamp(timestamp),
        received_at=received_at,
    )


def _find_device_object(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        if value.get("devId"):
            return value
        for key in ("device", "deviceInfo", "data", "result"):
            found = _find_device_object(value.get(key))
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_device_object(child)
            if found is not None:
                return found
    return None


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, (Mapping, list, tuple, set)):
        return None
    text = str(value).strip()
    return text or None


def _is_json_value(value: Any) -> bool:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, list):
        return all(_is_json_value(child) for child in value)
    if isinstance(value, Mapping):
        return all(
            isinstance(key, (str, int)) and _is_json_value(child)
            for key, child in value.items()
        )
    return False
