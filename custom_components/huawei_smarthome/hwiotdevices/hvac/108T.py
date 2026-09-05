"""Explicit Huawei SmartHome model for the 720 air purifier."""

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

PROD_ID = "108T"
HA_PLATFORM = "fan"
MANUFACTURER_NAME = "720"
PROFILE_MODEL = "KJ500F-EP500H"
COMMAND_ACK_TIMEOUT = 10.0

SERVICE_SWITCH = "switch"
SERVICE_AIR_PURIFYING = "airPurifying"
SERVICE_PM2P5 = "pm2p5"
SERVICE_WIND = "wind"
SERVICE_FAULT_DETECTION = "faultDetection"
SERVICE_FILTER_ELEMENT = "filterElement"
SERVICE_UPDATE = "update"

STATE_SERVICES = frozenset(
    {
        SERVICE_SWITCH,
        SERVICE_AIR_PURIFYING,
        SERVICE_PM2P5,
        SERVICE_WIND,
        SERVICE_FAULT_DETECTION,
        SERVICE_FILTER_ELEMENT,
        SERVICE_UPDATE,
    }
)
COMMAND_SERVICES = frozenset(
    {
        SERVICE_SWITCH,
        SERVICE_AIR_PURIFYING,
        SERVICE_WIND,
    }
)

MODE_BY_PRESET = {
    "manual": 0,
    "auto": 1,
    "sleep": 2,
}
PRESET_BY_MODE = {value: key for key, value in MODE_BY_PRESET.items()}

FEATURE_FIELDS = {
    "childLock": "Child lock",
    "UV": "UV",
    "anion": "Anion",
    "screenSwitch": "Screen",
    "keytoneSwitch": "Key tone",
}

StateListener = Callable[[], None]


class HuaweiDevice(HuaweiDeviceStateMixin):
    """Runtime context and protocol mapping for one 108T device."""

    prod_id = PROD_ID
    ha_platform = HA_PLATFORM
    state_services = STATE_SERVICES
    switch_keys = tuple(FEATURE_FIELDS)
    switch_names = FEATURE_FIELDS
    sensor_keys = frozenset({"pm2p5", "filter_remaining"})
    preset_modes = tuple(MODE_BY_PRESET)
    percentage_step = 25

    def __init__(
        self,
        descriptor: RemoteDeviceDescriptor,
        mqtt: HuaweiMqttClient,
    ) -> None:
        if (descriptor.prod_id or "").strip().upper() != PROD_ID:
            raise ValueError("108T device requires prodId=108T")
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
    def model(self) -> str | None:
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
    def preset_mode(self) -> str | None:
        mode = self._int_value(SERVICE_AIR_PURIFYING, "mode")
        return PRESET_BY_MODE.get(mode)

    @property
    def percentage(self) -> int | None:
        speed = self._int_value(SERVICE_WIND, "windSpeed")
        if speed is None or not 1 <= speed <= 4:
            return None
        return speed * self.percentage_step

    @property
    def pm2p5(self) -> int | None:
        return self._int_value(SERVICE_PM2P5, "pm2p5Value")

    @property
    def filter_remaining(self) -> int | None:
        value = self._int_value(SERVICE_FILTER_ELEMENT, "leftPer")
        if value is None:
            return None
        return min(max(value, 0), 100)

    def feature_is_on(self, characteristic: str) -> bool | None:
        """Return the state of one air-purifier feature switch."""

        if characteristic not in FEATURE_FIELDS:
            raise ValueError(f"unsupported 108T feature: {characteristic}")
        return self._bool_value(SERVICE_AIR_PURIFYING, characteristic)

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
                or not isinstance(data, Mapping)
            ):
                continue
            changed = (
                self._merge_service_state(
                    sid,
                    data,
                    service.get("ts"),
                )
                or changed
            )
        if changed:
            self._notify_state_changed()
        return changed

    async def async_turn_on(self) -> None:
        """Turn the air purifier on."""

        await self.async_set_service(SERVICE_SWITCH, {"on": 1})

    async def async_turn_off(self) -> None:
        """Turn the air purifier off."""

        await self.async_set_service(SERVICE_SWITCH, {"on": 0})

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the purifier's operating mode."""

        try:
            mode = MODE_BY_PRESET[preset_mode]
        except KeyError as error:
            raise ValueError(f"unsupported 108T preset mode: {preset_mode}") from error
        await self.async_set_service(SERVICE_AIR_PURIFYING, {"mode": mode})

    async def async_set_percentage(self, percentage: int) -> None:
        """Set one of the four manual fan speeds."""

        if isinstance(percentage, bool) or not isinstance(percentage, int):
            raise ValueError("percentage must be an integer")
        if percentage == 0:
            await self.async_turn_off()
            return
        if not 1 <= percentage <= 100:
            raise ValueError("percentage must be between 0 and 100")
        speed = min(max(round(percentage / self.percentage_step), 1), 4)
        await self.async_set_service(SERVICE_AIR_PURIFYING, {"mode": 0})
        await self.async_set_service(SERVICE_WIND, {"windSpeed": speed})

    async def async_set_feature(self, characteristic: str, enabled: bool) -> None:
        """Set one writable air-purifier feature."""

        if characteristic not in FEATURE_FIELDS:
            raise ValueError(f"unsupported 108T feature: {characteristic}")
        await self.async_set_service(
            SERVICE_AIR_PURIFYING,
            {characteristic: 1 if enabled else 0},
        )

    async def async_set_service(
        self,
        sid: str,
        data: dict[str, Any],
    ) -> None:
        """Publish one product command and wait for its service ACK."""

        if sid not in COMMAND_SERVICES:
            raise ValueError(f"unsupported 108T service: {sid}")
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
                    f"108T command rejected: sid={sid} errcode={remote_code}"
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
