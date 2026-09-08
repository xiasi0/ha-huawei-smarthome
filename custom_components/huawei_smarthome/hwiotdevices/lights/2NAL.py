"""Explicit Huawei SmartHome model for product 2NAL fan lights."""

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

PROD_ID = "2NAL"
HA_PLATFORM = "light"
HA_PLATFORMS = ("light", "fan")
LIGHT_NAME = "Light"
FAN_ENTITY_NAME = "Fan"
MANUFACTURER_NAME = "中山鸿钧科技有限公司"
PROFILE_MODEL = "HJ-HM-FSD-001"
COMMAND_ACK_TIMEOUT = 10.0
SUPPORTED_COLOR_MODES = frozenset({"color_temp"})
MIN_BRIGHTNESS = 1
MAX_BRIGHTNESS = 100
MIN_COLOR_TEMP_KELVIN = 3000
MAX_COLOR_TEMP_KELVIN = 5700

SERVICE_LIGHT_MODE = "lightMode"
SERVICE_FAN_MODE = "fanMode"
SERVICE_SWITCH = "switch"
SERVICE_SWITCH_FAN = "switchFan"
SERVICE_FAN = "fan"
SERVICE_BRIGHTNESS = "brightness"
SERVICE_CCT = "cct"

STATE_SERVICES = frozenset(
    {
        SERVICE_LIGHT_MODE,
        SERVICE_FAN_MODE,
        SERVICE_SWITCH,
        SERVICE_SWITCH_FAN,
        SERVICE_FAN,
        SERVICE_BRIGHTNESS,
        SERVICE_CCT,
    }
)
COMMAND_SERVICES = frozenset(
    {
        SERVICE_FAN_MODE,
        SERVICE_SWITCH,
        SERVICE_SWITCH_FAN,
        SERVICE_FAN,
        SERVICE_BRIGHTNESS,
        SERVICE_CCT,
    }
)

MODE_BY_PRESET = {
    "normal": 0,
    "sleep": 1,
    "natural": 2,
    "circulation": 100,
}
PRESET_BY_MODE = {value: key for key, value in MODE_BY_PRESET.items()}

StateListener = Callable[[], None]


class HuaweiDevice(HuaweiDeviceStateMixin):
    """Runtime context and protocol mapping for one 2NAL device."""

    prod_id = PROD_ID
    ha_platform = HA_PLATFORM
    ha_platforms = HA_PLATFORMS
    state_services = STATE_SERVICES
    light_name = LIGHT_NAME
    fan_entity_name = FAN_ENTITY_NAME
    supported_color_modes = SUPPORTED_COLOR_MODES
    min_color_temp_kelvin = MIN_COLOR_TEMP_KELVIN
    max_color_temp_kelvin = MAX_COLOR_TEMP_KELVIN
    preset_modes = tuple(MODE_BY_PRESET)
    percentage_step = 1

    def __init__(
        self,
        descriptor: RemoteDeviceDescriptor,
        mqtt: HuaweiMqttClient,
    ) -> None:
        if (descriptor.prod_id or "").strip().upper() != PROD_ID:
            raise ValueError("2NAL device requires prodId=2NAL")
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
        """Return the light switch state."""

        return self._bool_value(SERVICE_SWITCH, "on")

    @property
    def fan_is_on(self) -> bool | None:
        """Return the fan switch state."""

        return self._bool_value(SERVICE_SWITCH_FAN, "on")

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

    @property
    def percentage(self) -> int | None:
        gear = self._int_value(SERVICE_FAN, "gear")
        if gear is None or not 0 <= gear <= 6:
            return None
        return round(gear * 100 / 6)

    @property
    def preset_mode(self) -> str | None:
        mode = self._int_value(SERVICE_FAN_MODE, "mode")
        return PRESET_BY_MODE.get(mode)

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
        """Turn on and apply the requested light attributes."""

        if rgb_color is not None:
            raise ValueError("2NAL does not support RGB")
        await self.async_set_service(SERVICE_SWITCH, {"on": 1})
        if brightness is not None:
            await self.async_set_brightness(brightness)
        if color_temperature is not None:
            await self.async_set_color_temperature(color_temperature)

    async def async_turn_off(self) -> None:
        """Turn the light off."""

        await self.async_set_service(SERVICE_SWITCH, {"on": 0})

    async def async_fan_turn_on(self) -> None:
        """Turn the fan on."""

        await self.async_set_service(SERVICE_SWITCH_FAN, {"on": 1})

    async def async_fan_turn_off(self) -> None:
        """Turn the fan off."""

        await self.async_set_service(SERVICE_SWITCH_FAN, {"on": 0})

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

    async def async_set_percentage(self, percentage: int) -> None:
        if isinstance(percentage, bool) or not isinstance(percentage, int):
            raise ValueError("percentage must be an integer")
        if percentage == 0:
            await self.async_fan_turn_off()
            return
        if not 1 <= percentage <= 100:
            raise ValueError("percentage must be between 0 and 100")
        gear = min(max(round(percentage * 6 / 100), 1), 6)
        await self.async_set_service(SERVICE_FAN, {"gear": gear})

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        try:
            mode = MODE_BY_PRESET[preset_mode]
        except KeyError as error:
            raise ValueError(f"unsupported 2NAL preset mode: {preset_mode}") from error
        await self.async_set_service(SERVICE_FAN_MODE, {"mode": mode})

    async def async_set_service(
        self,
        sid: str,
        data: dict[str, Any],
    ) -> None:
        """Publish one product command and wait for its service ACK."""

        if sid not in COMMAND_SERVICES:
            raise ValueError(f"unsupported 2NAL service: {sid}")
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
                    f"2NAL command rejected: sid={sid} errcode={remote_code}"
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
