"""Explicit Huawei SmartHome model for product 2QQQ presence lights."""

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

PROD_ID = "2QQQ"
HA_PLATFORM = "light"
MANUFACTURER_NAME = "鸿钧电器"
PROFILE_MODEL = "HF-HM-PBD-D1"
COMMAND_ACK_TIMEOUT = 10.0
SUPPORTED_COLOR_MODES = frozenset({"color_temp"})
MIN_BRIGHTNESS = 1
MAX_BRIGHTNESS = 100
MIN_COLOR_TEMP_KELVIN = 3000
MAX_COLOR_TEMP_KELVIN = 5000

SERVICE_SWITCH = "switch"
SERVICE_BRIGHTNESS = "brightness"
SERVICE_CCT = "cct"
SERVICE_LIGHT_MODE = "lightMode"
SERVICE_HUMAN_SENSING_STATUS = "humanSensingStatus"
SERVICE_INDUCTION_SWITCH = "inductionSwitch"

PRESENCE_KEY = "presence"
INDUCTION_KEY = "induction"
STATE_SERVICES = frozenset(
    {
        SERVICE_SWITCH,
        SERVICE_BRIGHTNESS,
        SERVICE_CCT,
        SERVICE_LIGHT_MODE,
        SERVICE_HUMAN_SENSING_STATUS,
        SERVICE_INDUCTION_SWITCH,
    }
)
COMMAND_SERVICES = frozenset(
    {
        SERVICE_SWITCH,
        SERVICE_BRIGHTNESS,
        SERVICE_CCT,
        SERVICE_INDUCTION_SWITCH,
    }
)
FEATURE_SERVICES = {INDUCTION_KEY: SERVICE_INDUCTION_SWITCH}

StateListener = Callable[[], None]


class HuaweiDevice(HuaweiDeviceStateMixin):
    """Runtime context and protocol mapping for one 2QQQ device."""

    prod_id = PROD_ID
    ha_platform = HA_PLATFORM
    state_services = STATE_SERVICES
    supported_color_modes = SUPPORTED_COLOR_MODES
    min_color_temp_kelvin = MIN_COLOR_TEMP_KELVIN
    max_color_temp_kelvin = MAX_COLOR_TEMP_KELVIN
    binary_sensor_keys = (PRESENCE_KEY,)
    binary_sensor_names = {PRESENCE_KEY: "Presence"}
    binary_sensor_device_classes = {PRESENCE_KEY: "occupancy"}
    switch_keys = (INDUCTION_KEY,)
    switch_names = {INDUCTION_KEY: "Automatic sensing"}

    def __init__(
        self,
        descriptor: RemoteDeviceDescriptor,
        mqtt: HuaweiMqttClient,
    ) -> None:
        if (descriptor.prod_id or "").strip().upper() != PROD_ID:
            raise ValueError("2QQQ device requires prodId=2QQQ")
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
    def model(self) -> str | None:
        return self._descriptor.model or PROFILE_MODEL

    @property
    def manufacturer(self) -> str:
        return self._descriptor.manufacturer or MANUFACTURER_NAME

    @property
    def firmware_version(self) -> str | None:
        return self._descriptor.firmware_version

    @property
    def online(self) -> bool | None:
        return self._descriptor.online

    @property
    def available(self) -> bool:
        return self._descriptor.online is not False

    @property
    def is_on(self) -> bool | None:
        return self._bool_value(SERVICE_SWITCH, "on")

    @property
    def brightness(self) -> int | None:
        value = self._int_value(SERVICE_BRIGHTNESS, "brightness")
        if value is None:
            return None
        value = min(max(value, MIN_BRIGHTNESS), MAX_BRIGHTNESS)
        return round(
            (value - MIN_BRIGHTNESS) * 255 / (MAX_BRIGHTNESS - MIN_BRIGHTNESS)
        )

    @property
    def rgb_color(self) -> None:
        return None

    @property
    def color_temperature(self) -> int | None:
        return self._int_value(SERVICE_CCT, "colorTemperature")

    @property
    def colour_mode(self) -> None:
        return None

    def value(self, sid: str, name: str) -> Any:
        """Return one cached product characteristic."""

        return self._state.get(sid, {}).get(name)

    def binary_sensor_is_on(self, key: str) -> bool | None:
        """Return the presence state for the binary sensor projection."""

        if key != PRESENCE_KEY:
            raise ValueError(f"unsupported 2QQQ binary sensor: {key}")
        return self._bool_value(SERVICE_HUMAN_SENSING_STATUS, "status")

    def feature_is_on(self, key: str) -> bool | None:
        """Return one product feature switch state."""

        try:
            sid = FEATURE_SERVICES[key]
        except KeyError as error:
            raise ValueError(f"unsupported 2QQQ switch: {key}") from error
        return self._bool_value(sid, "on")

    async def async_set_feature(self, key: str, enabled: bool) -> None:
        """Set one product feature switch."""

        try:
            sid = FEATURE_SERVICES[key]
        except KeyError as error:
            raise ValueError(f"unsupported 2QQQ switch: {key}") from error
        await self.async_set_service(sid, {"on": 1 if enabled else 0})

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
            if not isinstance(sid, str) or not isinstance(data, Mapping):
                continue
            changed = (
                self._merge_service_state(sid, data, service.get("ts"))
                or changed
            )
        if changed:
            self._notify_state_changed()
        return changed

    async def async_turn_on(
        self,
        *,
        brightness: int | None = None,
        rgb_color: tuple[int, int, int] | None = None,
        color_temperature: int | None = None,
    ) -> None:
        """Turn on and apply the requested brightness or color temperature."""

        if rgb_color is not None:
            raise ValueError("2QQQ does not support RGB")
        await self.async_set_service(SERVICE_SWITCH, {"on": 1})
        if brightness is not None:
            await self.async_set_brightness(brightness)
        if color_temperature is not None:
            await self.async_set_color_temperature(color_temperature)

    async def async_turn_off(self) -> None:
        await self.async_set_service(SERVICE_SWITCH, {"on": 0})

    async def async_set_brightness(self, value: int) -> None:
        self._check_range(value, 0, 255, "brightness")
        device_value = round(
            MIN_BRIGHTNESS
            + value * (MAX_BRIGHTNESS - MIN_BRIGHTNESS) / 255
        )
        await self.async_set_service(
            SERVICE_BRIGHTNESS,
            {"brightness": device_value},
        )

    async def async_set_color_temperature(self, value: int) -> None:
        self._check_range(
            value,
            MIN_COLOR_TEMP_KELVIN,
            MAX_COLOR_TEMP_KELVIN,
            "color temperature",
        )
        await self.async_set_service(
            SERVICE_CCT,
            {"colorTemperature": value},
        )

    async def async_set_service(
        self,
        sid: str,
        data: dict[str, Any],
    ) -> None:
        """Publish one product command and wait for its service ACK."""

        if sid not in COMMAND_SERVICES:
            raise ValueError(f"unsupported 2QQQ service: {sid}")
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
                    f"2QQQ command rejected: sid={sid} errcode={remote_code}"
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

    @staticmethod
    def _check_range(value: int, minimum: int, maximum: int, name: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} must be an integer")
        if not minimum <= value <= maximum:
            raise ValueError(f"{name} must be between {minimum} and {maximum}")
