"""Protocol-independent Huawei SmartHome domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Mapping, TypeAlias

from ..const import UNASSIGNED_HOME_ID

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
DeviceKey: TypeAlias = tuple[str, str]


class Operation(StrEnum):
    """Remote operation advertised by a device."""

    READ = "READ"
    WRITE = "WRITE"
    EXECUTE = "EXECUTE"


class ConnectionState(StrEnum):
    """Account lifecycle state shared by discovery and later transports."""

    STOPPED = "stopped"
    AUTHENTICATING = "authenticating"
    DISCOVERING = "discovering"
    READY = "ready"
    REFRESHING_TOKEN = "refreshing_token"
    MQTT_CONNECTING = "mqtt_connecting"
    MQTT_SUBSCRIBING = "mqtt_subscribing"
    RUNNING = "running"
    DEGRADED = "degraded"
    RECONNECT_BACKOFF = "reconnect_backoff"
    REAUTH_REQUIRED = "reauth_required"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class AuthSession:
    """Authenticated account session with separated token domains."""

    account: str = field(repr=False)
    user_id: str
    service_token: str = field(repr=False)
    hms_access_token: str | None = field(default=None, repr=False)
    hms_refresh_token: str | None = field(default=None, repr=False)
    hms_expires_at: datetime | None = None
    oauth_access_token: str | None = field(default=None, repr=False)
    oauth_expires_at: datetime | None = None
    device_id: str = ""
    device_name: str = "huawei-smarthome"
    pushtmid: str | None = field(default=None, repr=False)
    identity_fingerprint: str | None = field(default=None, repr=False)
    app_id: str = "com.huawei.smarthome-ios"
    base_url: str = "https://smarthome.hicloud.com"
    home_zone: str | None = None
    oauth_domain: str | None = None
    site_domain: str | None = None
    generation: int = 0

    def is_hms_valid(self, margin_seconds: int = 30) -> bool:
        """Return whether the HMS-lite token is usable for HTTP."""

        if not self.hms_access_token:
            return False
        if self.hms_expires_at is None:
            return True
        return datetime_after_now(self.hms_expires_at, margin_seconds)

    def is_oauth_valid(self, margin_seconds: int = 30) -> bool:
        """Return whether the OAuth session token is usable."""

        if not self.oauth_access_token:
            return False
        if self.oauth_expires_at is None:
            return True
        return datetime_after_now(self.oauth_expires_at, margin_seconds)


@dataclass(frozen=True, slots=True)
class MessageChannelSession:
    """Ephemeral message-center context used to initialize MQTT."""

    mqtt_client_id: str = field(repr=False)
    mqtt_topic: str = field(repr=False)
    first_login: bool | None = None
    log_collection: str | None = None


@dataclass(frozen=True, slots=True)
class SmartHomeCloudRoute:
    """Dynamic cloud route returned for one authenticated account."""

    smart_home_host: str
    mqtt_port: int
    https_port: int
    expires_seconds: int | None = None
    role: int | None = None


@dataclass(frozen=True, slots=True)
class MqttConnectionSettings:
    """Complete MQTT transport settings for one connection generation."""

    broker_host: str
    broker_port: int
    client_id: str = field(repr=False)
    subscription_filters: tuple[str, ...] = field(default=(), repr=False)
    subscription_qos: int = 2  # Official command-channel SUBSCRIBE QoS.
    username: str | None = field(default=None, repr=False)
    password: str | None = field(default=None, repr=False)
    control_source: str = "huawei-smarthome"
    use_tls: bool = True
    keepalive: int = 60
    clean_session: bool | None = None


@dataclass(frozen=True, slots=True)
class RemoteRoom:
    """Remote Huawei room retained for discovery scope only."""

    home_id: str
    room_id: str
    name: str


@dataclass(frozen=True, slots=True)
class RemoteHome:
    """Remote Huawei home retained for discovery scope only."""

    home_id: str
    name: str
    role: str | None = None
    rooms: Mapping[str, RemoteRoom] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RemoteServiceState:
    """A service definition and its latest state from discovery."""

    sid: str
    service_type: str | None = None
    data: Mapping[str, JsonValue] = field(default_factory=dict)
    reported_timestamp: str | None = None
    occurred_at: datetime | None = None
    received_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RemoteDeviceDescriptor:
    """Device instance data from the SmartHome discovery API."""

    home_id: str
    dev_id: str
    name: str
    room_id: str | None = None
    room_name: str | None = None
    gateway_id: str | None = None
    node_type: str | None = None
    prod_id: str | None = None
    device_type_id: str | None = None
    model: str | None = None
    manufacturer: str | None = None
    manufacturer_code: str | None = None
    firmware_version: str | None = None
    protocol_type: str | int | None = None
    operations: frozenset[Operation] = frozenset()
    service_states: Mapping[str, RemoteServiceState] = field(default_factory=dict)
    online: bool | None = None
    tags: Mapping[str, JsonValue] = field(default_factory=dict)
    third_party_id: str | None = None
    registry_time: str | None = None
    discovery_metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    @property
    def key(self) -> DeviceKey:
        """Return the stable device key."""

        return self.home_id, self.dev_id


@dataclass(frozen=True, slots=True)
class RemoteDiscoverySnapshot:
    """Complete normalized homes and devices response."""

    homes: tuple[RemoteHome, ...]
    devices: tuple[RemoteDeviceDescriptor, ...]
    received_at: datetime
    complete: bool = True
    device_home_index: Mapping[str, frozenset[str]] = field(default_factory=dict)


@dataclass(slots=True)
class AccountState:
    """Non-secret account discovery state."""

    homes: dict[str, RemoteHome] = field(default_factory=dict)
    devices: dict[DeviceKey, RemoteDeviceDescriptor] = field(default_factory=dict)
    device_home_index: dict[str, frozenset[str]] = field(default_factory=dict)
    selected_home_ids: frozenset[str] = frozenset()
    connection: ConnectionState = ConnectionState.STOPPED
    last_snapshot_at: datetime | None = None
    last_event_at: datetime | None = None
    last_success_at: datetime | None = None
    stale_since: datetime | None = None
    last_error: str | None = None
    revision: int = 0


def canonical_home_id(value: Any) -> str:
    """Normalize a remote home identifier."""

    text = str(value).strip() if value is not None else ""
    return text or UNASSIGNED_HOME_ID


def parse_remote_timestamp(value: Any) -> datetime | None:
    """Parse the compact UTC timestamps used by SmartHome messages."""

    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    body = value[:-1]
    if "." in body:
        whole, fraction = body.split(".", 1)
        if not fraction.isdigit() or not whole:
            return None
        # Some devices report nanoseconds. datetime stores microseconds, so
        # retain the leading six digits to preserve remote ordering.
        fraction = (fraction + "000000")[:6]
        body = f"{whole}.{fraction}"
        pattern = "%Y%m%dT%H%M%S.%f"
    else:
        pattern = "%Y%m%dT%H%M%S"
    try:
        return datetime.strptime(body, pattern).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def datetime_after_now(value: datetime, margin_seconds: int) -> bool:
    """Compare a timezone-aware timestamp with the current UTC time."""

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value > datetime.now(timezone.utc) + timedelta(seconds=margin_seconds)
