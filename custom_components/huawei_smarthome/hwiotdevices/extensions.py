"""Service-level extensions for protocol/profile mismatches and compositions."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from .services import _coerce_profile_value, _field_range, _quantize

if TYPE_CHECKING:
    from .runtime import HuaweiDeviceRuntime


class RgbCctExtension:
    """Coordinate products that require a mode sid before RGB/CCT writes."""

    required_sids = frozenset({"colour", "cct"})

    def __init__(self, device: "HuaweiDeviceRuntime") -> None:
        self.device = device

    @property
    def mode_sid(self) -> str:
        for sid in ("colourMode", "lightMode"):
            if sid in self.device.cloud_service_ids:
                return sid
        raise ValueError("RGB/CCT mode service is unavailable")

    async def async_set_rgb(self, value: tuple[int, int, int]) -> None:
        service = self.device.service("colour")
        if service is None:
            raise ValueError("RGB service is unavailable")
        await self.device.send_service(self.mode_sid, {"mode": 0})
        await service.async_set_rgb(value)  # type: ignore[attr-defined]

    async def async_set_color_temperature(self, value: int) -> None:
        service = self.device.service("cct")
        if service is None:
            raise ValueError("color temperature service is unavailable")
        await self.device.send_service(self.mode_sid, {"mode": 1})
        await service.async_set_color_temperature(value)  # type: ignore[attr-defined]

    async def async_set_light_mode(self, value: int | float | str) -> None:
        """Enter preset-mode context before writing the light preset."""

        if "colourMode" not in self.device.cloud_service_ids:
            raise ValueError("light-mode context service is unavailable")
        if "lightMode" not in self.device.cloud_service_ids:
            raise ValueError("light-mode service is unavailable")
        await self.device.send_service("colourMode", {"mode": 4})
        await self.device.send_service("lightMode", {"mode": value})


class SpeakerExtension:
    """Map speaker logical controls to the runtime speaker service."""

    required_sids = frozenset({"smartspeaker", "audioplayer"})
    volume_fallback_prod_ids = frozenset({"X005"})
    volume_fallback_range = (0.0, 100.0)
    binary_sensor_names = {"charging": "Charging"}
    binary_sensor_device_classes = {"charging": "battery_charging"}
    def __init__(self, device: "HuaweiDeviceRuntime") -> None:
        self.device = device

    def _profile_field(self, sid: str, name: str):
        service = self.device.profile.services.get(sid)
        return service.field(name) if service is not None else None

    def _speaker_state_value(self) -> Any:
        """Read the cloud state key used by the speaker service.

        The public Profile calls the characteristic ``State`` while the
        device MQTT payload reports it as ``speakerState``.
        """

        for field_name in ("speakerState", "State", "state"):
            value = self.device.value("speakerState", field_name)
            if value is not None:
                return value
        return None

    def _volume_range(self) -> tuple[float, float] | None:
        value_range = _field_range(self._profile_field("smartspeaker", "volume"))
        if value_range is not None:
            return value_range
        if self.device.prod_id in self.volume_fallback_prod_ids:
            return self.volume_fallback_range
        return None

    def _play_control_field(self):
        return self._profile_field("smartspeaker", "playControl")

    def _control_value(self, action: str) -> str | None:
        field = self._play_control_field()
        if field is None:
            return None
        matches: list[str] = []
        for raw, description in field.enum_values:
            text = f"{raw} {description or ''}".lower()
            tokens = {
                "play": ("play", "播放中", "启动播放", "开始播放"),
                "pause": ("pause", "暂停"),
                "stop": ("stop", "停止"),
                "previous": ("previous", "上一首"),
                "next": ("next", "下一首"),
            }[action]
            if action == "play":
                matched = "停止" not in text and any(token in text for token in tokens)
            else:
                matched = any(token in text for token in tokens)
            if matched:
                matches.append(raw)
        if not matches:
            return None
        if action == "next":
            previous = self._control_value("previous")
            if previous is not None and previous == matches[0]:
                try:
                    return str(int(previous) + 1)
                except ValueError:
                    return None
        return matches[0]

    @property
    def supported_media_actions(self) -> frozenset[str]:
        actions = {
            action
            for action in ("play", "pause", "stop", "previous", "next")
            if self._control_value(action) is not None
        }
        return frozenset(actions)

    @property
    def media_state(self) -> str | None:
        value = self.device.value("audioplayer", "playState")
        field = self._profile_field("audioplayer", "playState")
        if field is not None:
            for raw, description in field.enum_values:
                if str(value) != raw:
                    continue
                text = (description or "").lower()
                if "暂停" in text or "pause" in text:
                    return "paused"
                if "播放" in text or "play" in text:
                    return "playing"
                if "停止" in text or "stop" in text:
                    return "idle"
        return None

    @property
    def sensor_keys(self) -> frozenset[str]:
        keys: set[str] = set()
        if (
            "battery" in self.device.cloud_service_ids
            and _field_range(self._battery_field()) is not None
        ):
            keys.add("battery_level")
        if (
            "speakerState" in self.device.cloud_service_ids
            and self._profile_field("speakerState", "State") is not None
        ):
            keys.add("speaker_state")
        return frozenset(keys)

    @property
    def binary_sensor_keys(self) -> tuple[str, ...]:
        return ("charging",) if "battery" in self.device.cloud_service_ids else ()

    def _battery_field(self):
        for name in ("level", "battery", "voltage"):
            field = self._profile_field("battery", name)
            if field is not None:
                return field
        return None

    @property
    def volume_level(self) -> float | None:
        value = self.device.value("smartspeaker", "volume")
        value_range = self._volume_range()
        if value_range is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        minimum, maximum = value_range
        number = min(max(number, minimum), maximum)
        return (number - minimum) / (maximum - minimum)

    @property
    def battery_level(self) -> int | None:
        field_name = next(
            (
                name
                for name in ("level", "battery", "voltage")
                if self._profile_field("battery", name) is not None
            ),
            None,
        )
        field = self._profile_field("battery", field_name) if field_name else None
        value_range = _field_range(field)
        if field is None or value_range is None:
            return None
        value = self.device.value("battery", field_name)
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        minimum, maximum = value_range
        number = min(max(number, minimum), maximum)
        return round((number - minimum) * 100 / (maximum - minimum))

    @property
    def speaker_state(self) -> str | None:
        value = self._speaker_state_value()
        field = self._profile_field("speakerState", "State")
        if field is not None:
            for raw, description in field.enum_values:
                if str(value) == raw:
                    return description or raw
        return str(value) if value is not None else None

    def binary_sensor_is_on(self, key: str) -> bool | None:
        if key != "charging":
            raise ValueError(f"unsupported speaker binary sensor: {key}")
        value = self.device.value("battery", "charge")
        if value is None:
            return None
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "on"}
        return value in (True, 1)

    @property
    def is_volume_muted(self) -> bool | None:
        value = self.device.value("smartspeaker", "muteStatus")
        if value is None:
            return None
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "on"}
        return value in (True, 1)

    @property
    def media_metadata(self) -> Mapping[str, Any]:
        value = self.device.value("audioplayer", "metadata")
        if isinstance(value, Mapping):
            return value
        if not isinstance(value, str) or not value:
            return {}
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, Mapping) else {}

    async def async_set_volume_level(self, level: float) -> None:
        if isinstance(level, bool) or not isinstance(level, (int, float)):
            raise ValueError("volume level must be numeric")
        if not 0 <= level <= 1:
            raise ValueError("volume level must be between 0 and 1")
        field = self._profile_field("smartspeaker", "volume")
        value_range = self._volume_range()
        if value_range is None:
            raise ValueError("volume range is missing from the Profile")
        minimum, maximum = value_range
        value = minimum + level * (maximum - minimum)
        limit = self.device.value("battery", "restrictMaxVolume")
        try:
            if limit is not None:
                value = min(value, float(limit))
        except (TypeError, ValueError):
            pass
        if field is not None:
            value = _quantize(value, field)
        await self.device.send_service(
            "smartspeaker",
            {"volume": value},
        )

    @property
    def supports_volume_control(self) -> bool:
        return self._volume_range() is not None

    async def async_set_play_control(self, action: str) -> None:
        raw = self._control_value(action)
        field = self._play_control_field()
        if raw is None or field is None:
            raise ValueError(f"speaker action is unavailable: {action}")
        await self.device.send_service(
            "smartspeaker",
            {"playControl": _coerce_profile_value(raw, field)},
        )

    async def async_media_play(self) -> None:
        await self.async_set_play_control("play")

    async def async_media_pause(self) -> None:
        await self.async_set_play_control("pause")

    async def async_media_stop(self) -> None:
        await self.async_set_play_control("stop")

    async def async_media_previous_track(self) -> None:
        await self.async_set_play_control("previous")

    async def async_media_next_track(self) -> None:
        await self.async_set_play_control("next")


def create_extensions(device: "HuaweiDeviceRuntime") -> tuple[object, ...]:
    """Create extensions from the services actually present on the device."""

    sids = device.cloud_service_ids
    extensions: list[object] = []
    if (
        RgbCctExtension.required_sids <= sids
        and any(sid in sids for sid in ("colourMode", "lightMode"))
        and device.service("colour") is not None
        and device.service("cct") is not None
    ):
        extensions.append(RgbCctExtension(device))
    if SpeakerExtension.required_sids <= sids:
        extensions.append(SpeakerExtension(device))
    return tuple(extensions)
