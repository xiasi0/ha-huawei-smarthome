"""Explicit Huawei SmartHome model for product 2OJL humidifiers."""

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

PROD_ID = "2OJL"
HA_PLATFORM = "humidifier"
MANUFACTURER_NAME = "上海汉枫电子科技有限公司"
PROFILE_MODEL = "HF-HM-JSQ-002"
PROFILE_NAME = "eachone一起玩智能加湿器"
HUMIDIFIER_ENTITY_NAME = "Humidifier"
COMMAND_ACK_TIMEOUT = 10.0

SERVICE_SWITCH = "switch"
SERVICE_WATER_GEAR = "waterGear"
SERVICE_TIMER = "timer"
SERVICE_HUMIDITY = "humidity"
SERVICE_GEAR = "gear"
SERVICE_COUNTDOWN = "countdown"
SERVICE_REMAINING_TIME = "remainingtime"
SERVICE_LIGHT_MODE = "lightmode"

WATER_LACK_KEY = "water_lack"
LIGHT_MODE_KEY = "light_mode"

HUMIDIFIER_MODES = ("constant", "high", "low", "sleep")
HUMIDIFIER_MODE_TO_DEVICE = {
    "constant": 0,
    "high": 1,
    "low": 2,
    "sleep": 3,
}
HUMIDIFIER_MODE_FROM_DEVICE = {
    value: name for name, value in HUMIDIFIER_MODE_TO_DEVICE.items()
}

LIGHT_MODE_OPTIONS = (
    "关闭",
    "七彩变换",
    "紫色",
    "蓝色",
    "青色",
    "绿色",
    "黄色",
    "橙色",
    "红色",
)
LIGHT_MODE_TO_DEVICE = dict(enumerate(LIGHT_MODE_OPTIONS))
LIGHT_MODE_FROM_DEVICE = {
    option: value for value, option in LIGHT_MODE_TO_DEVICE.items()
}

STATE_SERVICES = frozenset(
    {
        SERVICE_SWITCH,
        SERVICE_WATER_GEAR,
        SERVICE_HUMIDITY,
        SERVICE_GEAR,
        SERVICE_LIGHT_MODE,
    }
)
COMMAND_SERVICES = frozenset(
    {
        SERVICE_SWITCH,
        SERVICE_HUMIDITY,
        SERVICE_GEAR,
        SERVICE_LIGHT_MODE,
    }
)

StateListener = Callable[[], None]


class HuaweiDevice(HuaweiDeviceStateMixin):
    """Runtime context and protocol mapping for one 2OJL device."""

    prod_id = PROD_ID
    ha_platform = HA_PLATFORM
    humidifier_entity_name = HUMIDIFIER_ENTITY_NAME
    humidifier_modes = HUMIDIFIER_MODES
    min_target_humidity = 40
    max_target_humidity = 80
    state_services = STATE_SERVICES
    binary_sensor_keys = (WATER_LACK_KEY,)
    binary_sensor_names = {WATER_LACK_KEY: "Water low"}
    binary_sensor_device_classes = {WATER_LACK_KEY: "problem"}
    select_keys = (LIGHT_MODE_KEY,)
    select_names = {LIGHT_MODE_KEY: "Light mode"}
    select_options = {LIGHT_MODE_KEY: LIGHT_MODE_OPTIONS}

    def __init__(
        self,
        descriptor: RemoteDeviceDescriptor,
        mqtt: HuaweiMqttClient,
    ) -> None:
        if (descriptor.prod_id or "").strip().upper() != PROD_ID:
            raise ValueError("2OJL device requires prodId=2OJL")
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
        return self._descriptor.name or PROFILE_NAME

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
        value = self.value(SERVICE_SWITCH, "on")
        if value is None:
            return None
        return value in (True, 1, "1")

    @property
    def current_humidity(self) -> int | None:
        return self._int_value(SERVICE_HUMIDITY, "current")

    @property
    def target_humidity(self) -> int | None:
        return self._int_value(SERVICE_HUMIDITY, "target")

    @property
    def humidifier_mode(self) -> str | None:
        value = self._int_value(SERVICE_GEAR, "gear")
        return HUMIDIFIER_MODE_FROM_DEVICE.get(value)

    @property
    def water_lack(self) -> bool | None:
        value = self._int_value(SERVICE_WATER_GEAR, "gear")
        if value is None:
            return None
        return value == 0

    def value(self, sid: str, name: str) -> Any:
        """Return one cached product characteristic."""

        return self._state.get(sid, {}).get(name)

    def add_state_listener(self, listener: StateListener) -> None:
        self._listeners.add(listener)

    def remove_state_listener(self, listener: StateListener) -> None:
        self._listeners.discard(listener)

    def binary_sensor_is_on(self, key: str) -> bool | None:
        """Return whether the water tank reports a low-water condition."""

        if key != WATER_LACK_KEY:
            raise ValueError(f"unsupported 2OJL binary sensor: {key}")
        return self.water_lack

    def select_value(self, key: str) -> str | None:
        """Return the selected built-in light mode."""

        if key != LIGHT_MODE_KEY:
            raise ValueError(f"unsupported 2OJL select: {key}")
        value = self._int_value(SERVICE_LIGHT_MODE, "Lightmode")
        return LIGHT_MODE_TO_DEVICE.get(value)

    async def async_select_option(self, key: str, option: str) -> None:
        """Set the built-in light mode."""

        if key != LIGHT_MODE_KEY:
            raise ValueError(f"unsupported 2OJL select: {key}")
        try:
            value = LIGHT_MODE_FROM_DEVICE[option]
        except KeyError as error:
            raise ValueError(f"unsupported 2OJL light mode: {option}") from error
        await self.async_set_service(
            SERVICE_LIGHT_MODE,
            {"Lightmode": value},
        )

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
            # An ACK confirms cloud-side handling only; it is not device state.
            return self._handle_command_ack(body, header)
        if notify_type != "deviceDataChanged":
            return False
        if body.get("devId") != self.dev_id:
            return False

        changed = False
        services = body.get("services")
        if not isinstance(services, list):
            return False
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

    async def async_turn_on(self, **kwargs: Any) -> None:
        del kwargs
        await self.async_set_service(SERVICE_SWITCH, {"on": 1})

    async def async_turn_off(self) -> None:
        await self.async_set_service(SERVICE_SWITCH, {"on": 0})

    async def async_set_target_humidity(self, value: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("target humidity must be an integer")
        if not 40 <= value <= 80 or value % 5:
            raise ValueError(
                "target humidity must be a multiple of 5 between 40 and 80"
            )
        await self.async_set_service(
            SERVICE_HUMIDITY,
            {"target": value},
        )

    async def async_set_humidifier_mode(self, mode: str) -> None:
        try:
            value = HUMIDIFIER_MODE_TO_DEVICE[mode]
        except KeyError as error:
            raise ValueError(f"unsupported 2OJL humidifier mode: {mode}") from error
        await self.async_set_service(SERVICE_GEAR, {"gear": value})

    async def async_set_service(
        self,
        sid: str,
        data: dict[str, Any],
    ) -> None:
        """Publish one product command and wait for its service ACK."""

        if sid not in COMMAND_SERVICES:
            raise ValueError(f"unsupported 2OJL service: {sid}")
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
                    f"2OJL command rejected: sid={sid} errcode={remote_code}"
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

    def _notify_state_changed(self) -> None:
        for listener in tuple(self._listeners):
            listener()


def create_humidifier_entity_class() -> type[Any]:
    """Create the Home Assistant entity class for this product only."""

    from homeassistant.components.humidifier import (
        HumidifierEntity,
        HumidifierEntityFeature,
    )
    from homeassistant.helpers.entity import DeviceInfo

    from ...device_registry import device_identifier, profile_configuration_url

    class Huawei2OJLHumidifier(HumidifierEntity):
        """Project one hard-coded 2OJL device as a humidifier."""

        def __init__(self, device: HuaweiDevice) -> None:
            self._device = device
            self._attr_unique_id = (
                f"{device.home_id}_{device.dev_id}_humidifier"
            )
            self._attr_name = HUMIDIFIER_ENTITY_NAME
            self._attr_has_entity_name = True
            self._attr_should_poll = False
            self._attr_supported_features = HumidifierEntityFeature.MODES
            self._attr_available_modes = list(device.humidifier_modes)
            self._attr_min_humidity = device.min_target_humidity
            self._attr_max_humidity = device.max_target_humidity

        @property
        def device_info(self) -> DeviceInfo:
            """Return the shared HA device identity."""

            return DeviceInfo(
                identifiers={device_identifier(self._device.descriptor)},
                name=self._device.name,
                manufacturer=self._device.manufacturer,
                model=self._device.model,
                sw_version=self._device.firmware_version,
                configuration_url=profile_configuration_url(
                    self._device.prod_id,
                ),
            )

        @property
        def available(self) -> bool:
            return self._device.available

        @property
        def is_on(self) -> bool | None:
            return self._device.is_on

        @property
        def current_humidity(self) -> int | None:
            return self._device.current_humidity

        @property
        def target_humidity(self) -> int | None:
            return self._device.target_humidity

        @property
        def mode(self) -> str | None:
            return self._device.humidifier_mode

        async def async_added_to_hass(self) -> None:
            self._device.add_state_listener(self._state_changed)

        async def async_will_remove_from_hass(self) -> None:
            self._device.remove_state_listener(self._state_changed)

        async def async_turn_on(self, **kwargs: Any) -> None:
            del kwargs
            await self._device.async_turn_on()

        async def async_turn_off(self, **kwargs: Any) -> None:
            del kwargs
            await self._device.async_turn_off()

        async def async_set_humidity(self, humidity: int) -> None:
            await self._device.async_set_target_humidity(humidity)

        async def async_set_mode(self, mode: str) -> None:
            await self._device.async_set_humidifier_mode(mode)

        def _state_changed(self) -> None:
            self.async_write_ha_state()

    return Huawei2OJLHumidifier
