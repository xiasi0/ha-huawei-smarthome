"""Explicit Huawei SmartHome model for the X0A2 smart speaker."""

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

PROD_ID = "X0A2"
HA_PLATFORM = "media_player"
MANUFACTURER_NAME = "华为"
PROFILE_MODEL = "SKLK-00"
PROFILE_NAME = "华为 AI 音箱 2e"
COMMAND_ACK_TIMEOUT = 10.0

SERVICE_SMARTSPEAKER = "smartspeaker"
SERVICE_AUDIOPLAYER = "audioplayer"
SERVICE_SPEAKER_STATE = "speakerState"

STATE_SERVICES = frozenset(
    {
        SERVICE_SMARTSPEAKER,
        SERVICE_AUDIOPLAYER,
        SERVICE_SPEAKER_STATE,
    }
)
COMMAND_SERVICES = frozenset({SERVICE_SMARTSPEAKER})

# The product profile contains enumVal=2 for both previous and next.
PLAY_CONTROL_PREVIOUS = 2
PLAY_CONTROL_NEXT = 3

SENSOR_KEYS = frozenset({"speaker_state"})
BINARY_SENSOR_KEYS = frozenset()
BINARY_SENSOR_NAMES: dict[str, str] = {}
BINARY_SENSOR_DEVICE_CLASSES: dict[str, str] = {}

SPEAKER_STATE_NAMES = {
    0: "standby",
    1: "listening",
    2: "waiting_response",
    3: "voice_broadcast",
}

StateListener = Callable[[], None]


class HuaweiDevice(HuaweiDeviceStateMixin):
    """Runtime context and protocol mapping for one X0A2 device."""

    prod_id = PROD_ID
    ha_platform = HA_PLATFORM
    state_services = STATE_SERVICES
    sensor_keys = SENSOR_KEYS
    binary_sensor_keys = BINARY_SENSOR_KEYS
    binary_sensor_names = BINARY_SENSOR_NAMES
    binary_sensor_device_classes = BINARY_SENSOR_DEVICE_CLASSES

    def __init__(
        self,
        descriptor: RemoteDeviceDescriptor,
        mqtt: HuaweiMqttClient,
    ) -> None:
        if (descriptor.prod_id or "").strip().upper() != PROD_ID:
            raise ValueError("X0A2 device requires prodId=X0A2")
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
        return self._descriptor.name or PROFILE_NAME

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
    def speaker_state(self) -> str | None:
        """Return the read-only voice interaction state."""

        value = self._int_value(SERVICE_SPEAKER_STATE, "speakerState")
        return SPEAKER_STATE_NAMES.get(value)

    @property
    def play_state(self) -> int | None:
        """Return the raw audioplayer play state."""

        return self._int_value(SERVICE_AUDIOPLAYER, "playState")

    @property
    def volume_level(self) -> float | None:
        """Return the speaker volume in Home Assistant's 0..1 range."""

        value = self._int_value(SERVICE_SMARTSPEAKER, "volume")
        if value is None:
            return None
        return min(max(value, 0), 100) / 100

    @property
    def is_volume_muted(self) -> bool | None:
        """Return the reported mute state when available."""

        value = self.value(SERVICE_SMARTSPEAKER, "muteStatus")
        if value is None:
            return None
        return value in (True, 1, "1")

    @property
    def media_metadata(self) -> Mapping[str, Any]:
        """Decode the nested audioplayer metadata object."""

        value = self.value(SERVICE_AUDIOPLAYER, "metadata")
        if isinstance(value, Mapping):
            return value
        if not isinstance(value, str) or not value:
            return {}
        try:
            metadata = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return metadata if isinstance(metadata, Mapping) else {}

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
            if not isinstance(sid, str) or not isinstance(data, Mapping):
                continue
            changed = (
                self._merge_service_state(sid, data, service.get("ts"))
                or changed
            )
        if changed:
            self._notify_state_changed()
        return changed

    async def async_media_play(self) -> None:
        """Start or resume playback."""

        await self._async_set_play_state(1, {"playControl": 1})

    async def async_media_pause(self) -> None:
        """Pause playback."""

        await self._async_set_play_state(0, {"playControl": 0})

    async def async_media_stop(self) -> None:
        """Stop playback using the product's stop control."""

        await self._async_set_play_state(2, {"playControl": 0})

    async def async_media_previous_track(self) -> None:
        """Skip to the previous track."""

        await self.async_set_service({"playControl": PLAY_CONTROL_PREVIOUS})

    async def async_media_next_track(self) -> None:
        """Skip to the next track."""

        await self.async_set_service({"playControl": PLAY_CONTROL_NEXT})

    async def async_set_volume_level(self, level: float) -> None:
        """Set the speaker volume."""

        if isinstance(level, bool) or not isinstance(level, (int, float)):
            raise ValueError("volume level must be numeric")
        if not 0.0 <= level <= 1.0:
            raise ValueError("volume level must be between 0 and 1")
        await self.async_set_service({"volume": round(level * 100)})

    async def _async_set_play_state(
        self,
        play_state: int,
        command: dict[str, Any],
    ) -> None:
        """Optimistically update playback and roll back a failed command."""

        had_audio_state = SERVICE_AUDIOPLAYER in self._state
        previous_audio_state = dict(
            self._state.get(SERVICE_AUDIOPLAYER, {})
        )
        self._set_local_play_state(play_state)
        optimistic_audio_state = dict(
            self._state.get(SERVICE_AUDIOPLAYER, {})
        )
        try:
            await self.async_set_service(command)
        except Exception:
            if self._state.get(SERVICE_AUDIOPLAYER, {}) == optimistic_audio_state:
                if had_audio_state:
                    self._state[SERVICE_AUDIOPLAYER] = previous_audio_state
                else:
                    self._state.pop(SERVICE_AUDIOPLAYER, None)
                self._notify_state_changed()
            raise

    def _set_local_play_state(self, play_state: int) -> None:
        """Set a local playback state before the command is acknowledged."""

        audio_state = self._state.setdefault(SERVICE_AUDIOPLAYER, {})
        audio_state["playState"] = play_state
        self._notify_state_changed()

    async def async_set_service(self, data: dict[str, Any]) -> None:
        """Publish one speaker command and wait for its service ACK."""

        sid = SERVICE_SMARTSPEAKER
        if sid not in COMMAND_SERVICES:
            raise ValueError(f"unsupported X0A2 service: {sid}")
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
                    f"X0A2 command rejected: sid={sid} errcode={remote_code}"
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
