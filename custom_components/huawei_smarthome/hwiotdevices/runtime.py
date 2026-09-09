"""Lightweight service-centered runtime for one Huawei SmartHome device."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ..domain.models import RemoteDeviceDescriptor, RemoteServiceState, is_older_remote_timestamp
from ..mqtt.commands import HuaweiCommandGateway
from ..mqtt.protocol import decode_message
from ..mqtt_client import HuaweiMqttClient
from .extensions import RgbCctExtension, SpeakerExtension, create_extensions
from .profile import ProductProfile
from .services import (
    BrightnessService,
    ColorTemperatureService,
    CoverService,
    FanService,
    HumidifierService,
    HuaweiService,
    RgbService,
    SwitchService,
    _coerce_profile_value,
    create_basic_service,
    create_cover_service,
    create_humidifier_service,
)


StateListener = Callable[[], None]


@dataclass(frozen=True, slots=True)
class HuaweiDeviceEvent:
    """One physical button event decoded from a device scene service."""

    action: str
    key_code: int
    button_id: int | None
    name: str | None
    timestamp: str | None


EventListener = Callable[[HuaweiDeviceEvent], None]

_SCENE_ACTION_FIELDS = {
    "num": "single",
    "single": "single",
    "singleClick": "single",
    "DoubleClick": "double",
    "doubleClick": "double",
    "LongClick": "long",
    "longClick": "long",
}
_EVENT_SERVICE_RULES = {
    "keyevent": (("key", "keyCode", "code"), "key_event"),
    "bellstatus": (("status", "value", "code"), "button_pressed"),
    "devstateserv": (("value", "status", "code"), "ring"),
}

_SENSOR_RULES = {
    "battery_level": ({"battery"}, {"level", "voltage", "battery"}),
    "co2": ({"co2"}, {"co2", "concentration", "current"}),
    "electric_current": (
        {"current", "electric", "electricity"},
        ("current", "electricCurrent"),
    ),
    "energy_consumption": (
        {
            "consumption",
            "electric",
            "electricity",
            "energy",
            "powerelectricity",
        },
        (
            "totalElectricity",
            "TotalElectricity",
            "totalConsum",
            "consumption",
            "electricity",
            "energy",
        ),
    ),
    "formaldehyde": (
        {"formaldehyde", "hcho"},
        ("currentFloat", "current", "concentration"),
    ),
    "gas_concentration": (
        {"equipmentstatus", "gas"},
        {"ConcentrationValue", "current", "concentration", "gas"},
    ),
    "humidity": (
        {"humidity"},
        {"current", "currentFloat", "humidity", "relativeHumidity"},
    ),
    "illuminance": ({"illuminance"}, {"current", "illuminance", "lux"}),
    "pm2p5": ({"pm2p5"}, {"current", "currentFloat", "pm2p5", "pm2p5Value"}),
    "power": ({"power", "electricity", "powerelectricity"}, {"current", "power"}),
    "temperature": (
        {"temperature"},
        {"current", "currentFloat", "temperature"},
    ),
    "voltage": (
        {"electric", "electricity", "voltage"},
        ("voltage", "current"),
    ),
    "tds": ({"water"}, {"tds"}),
}
_SENSOR_FIELD_PRIORITIES = {
    "electric_current": {"electricCurrent": 20, "current": 10},
    "energy_consumption": {
        "totalElectricity": 50,
        "TotalElectricity": 50,
        "totalConsum": 40,
        "consumption": 30,
        "electricity": 20,
        "energy": 10,
    },
    "power": {"power": 20, "current": 10},
    "voltage": {"voltage": 20, "current": 10},
}
_BINARY_SERVICE_TYPES = frozenset(
    {
        "battery",
        "doorcontact",
        "gas",
        "motionsensor",
        "pir",
        "smoke",
        "waterleak",
    }
)
_BINARY_FIELDS = {
    "charging": {"charge", "charging"},
    "battery_low": {"lowBattery", "emergentBattery", "alarm"},
    "door": {"status", "state", "door"},
    "motion": {"status", "state", "motion", "presence", "alarm"},
    "presence": {"status", "state", "presence", "motion", "alarm"},
    "gas": {"status", "state", "gas", "level", "alarm"},
    "smoke": {"status", "state", "smoke", "level"},
    "water_leak": {"status", "state", "waterLeak"},
}


def _int_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
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


def _smoke_level_is_on(value: Any) -> bool | None:
    """Convert the verified smoke level values into an alarm state."""

    level = _int_value(value)
    if level == 2:
        return True
    if level == 1:
        return False
    return None


def _gas_level_is_on(value: Any) -> bool | None:
    """Convert the verified LEL level ranges into an alarm state."""

    level = _int_value(value)
    if level is None:
        return None
    if level >= 9:
        return True
    if level <= 8:
        return False
    return None


def _gas_alarm_is_on(value: Any, field: Any) -> bool | None:
    """Convert a gas alarm enum using the values declared by its Profile."""

    level = _int_value(value)
    if level is None or field is None:
        return None
    enum_values = {raw for raw, _ in field.enum_values}
    if {"2", "3"} & enum_values:
        if level in {2, 3}:
            return True
        if level in {0, 1}:
            return False
        return None
    if level == 1:
        return True
    if level == 0:
        return False
    return None


class HuaweiDeviceRuntime:
    """One device context with Profile-backed service bindings."""

    def __init__(
        self,
        descriptor: RemoteDeviceDescriptor,
        mqtt: HuaweiMqttClient,
        profile: ProductProfile,
        *,
        command_gateway: HuaweiCommandGateway | None = None,
    ) -> None:
        if descriptor.prod_id and descriptor.prod_id.strip().lower() != profile.prod_id.strip().lower():
            raise ValueError("Profile prodId does not match device descriptor")
        self._descriptor = descriptor
        self.profile = profile
        self.command_gateway = command_gateway or HuaweiCommandGateway(mqtt)
        self._cloud_service_ids: set[str] = set(descriptor.service_states)
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
        self._event_listeners: set[EventListener] = set()
        self._services_by_sid: dict[str, HuaweiService] = {}
        self._extensions: tuple[object, ...] = ()
        self._cover_service: CoverService | None = None
        self._humidifier_service: HumidifierService | None = None
        self._sensor_bindings: dict[str, tuple[str, str]] = {}
        self._sensor_binding_priorities: dict[str, int] = {}
        self._binary_bindings: dict[str, tuple[str, str]] = {}
        self._binary_semantics: dict[str, str] = {}
        self._number_bindings: dict[str, tuple[str, str]] = {}
        self._select_bindings: dict[str, tuple[str, str]] = {}
        self._rebuild_bindings()

    @property
    def descriptor(self) -> RemoteDeviceDescriptor:
        return self._descriptor

    @property
    def prod_id(self) -> str:
        return self.profile.prod_id

    @property
    def dev_id(self) -> str:
        return self._descriptor.dev_id

    @property
    def home_id(self) -> str:
        return self._descriptor.home_id

    @property
    def name(self) -> str:
        return self._descriptor.name

    @property
    def model(self) -> str | None:
        return self._descriptor.model or self.profile.model

    @property
    def product_name(self) -> str:
        """Return the Profile deviceName used by composite HA entities."""

        return self.profile.device_name or self._descriptor.name

    @property
    def manufacturer(self) -> str | None:
        return self._descriptor.manufacturer or self.profile.manufacturer

    @property
    def firmware_version(self) -> str | None:
        return self._descriptor.firmware_version

    @property
    def available(self) -> bool:
        return self._descriptor.online is not False

    @property
    def ha_platforms(self) -> frozenset[str]:
        """Return every HA platform represented by this device context."""

        platforms: set[str] = set()
        is_light = bool(self.switch_keys) and any(
            sid in self._services_by_sid
            for sid in ("brightness", "colour", "cct")
        )
        if is_light:
            platforms.add("light")
        if self.extension(SpeakerExtension) is not None:
            platforms.add("media_player")
        if self.fan_service is not None:
            platforms.add("fan")
        if self.cover_service is not None:
            platforms.add("cover")
        if self.humidifier_service is not None:
            platforms.add("humidifier")
        if self.button_event_actions:
            platforms.add("event")
        if self.switch_entity_keys:
            platforms.add("switch")
        if self._number_bindings:
            platforms.add("number")
        if self._select_bindings:
            platforms.add("select")
        return frozenset(platforms)

    @property
    def supported_color_modes(self) -> frozenset[str]:
        modes: set[str] = set()
        if "colour" in self._services_by_sid:
            modes.add("rgb")
        if "cct" in self._services_by_sid:
            modes.add("color_temp")
        if not modes and "brightness" in self._services_by_sid:
            modes.add("brightness")
        if not modes and self.switch_keys:
            modes.add("onoff")
        return frozenset(modes)

    @property
    def switch_keys(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                sid
                for sid, service in self._services_by_sid.items()
                if isinstance(service, SwitchService)
            )
        )

    @property
    def switch_entity_keys(self) -> tuple[str, ...]:
        """Return switch services not absorbed by another composite entity."""

        if not self.switch_keys:
            return ()
        if (
            any(
                sid in self._services_by_sid
                for sid in ("brightness", "colour", "cct")
            )
            or self.cover_service is not None
            or self.humidifier_service is not None
        ):
            return ()
        keys = self.switch_keys
        if self.fan_service is not None and self._primary_switch_key is not None:
            return tuple(key for key in keys if key != self._primary_switch_key)
        return keys

    @property
    def switch_names(self) -> Mapping[str, str]:
        names: dict[str, str] = {}
        for sid in self.switch_keys:
            spec = self.profile.services.get(sid)
            field = spec.field("on") if spec is not None else None
            if sid == "switch":
                fallback = "Switch"
            else:
                fallback = f"Switch {sid.removeprefix('switch')}"
            names[sid] = (
                (spec.description if spec is not None else None)
                or (field.label if field is not None else None)
                or (spec.name if spec is not None else None)
                or fallback
            )
        return names

    @property
    def min_color_temp_kelvin(self) -> int | None:
        service = self._services_by_sid.get("cct")
        if not isinstance(service, ColorTemperatureService) or service.field is None:
            return None
        value = service.field.min_value
        return int(value) if value is not None else None

    @property
    def max_color_temp_kelvin(self) -> int | None:
        service = self._services_by_sid.get("cct")
        if not isinstance(service, ColorTemperatureService) or service.field is None:
            return None
        value = service.field.max_value
        return int(value) if value is not None else None

    @property
    def is_on(self) -> bool | None:
        key = self._primary_switch_key
        return self.switch_is_on(key) if key is not None else None

    def switch_is_on(self, key: str) -> bool | None:
        service = self._services_by_sid.get(key)
        return service.is_on if isinstance(service, SwitchService) else None

    async def async_switch_turn_on(self, key: str) -> None:
        service = self._services_by_sid.get(key)
        if not isinstance(service, SwitchService):
            raise ValueError(f"switch service is unavailable: {key}")
        await service.async_turn_on()

    async def async_switch_turn_off(self, key: str) -> None:
        service = self._services_by_sid.get(key)
        if not isinstance(service, SwitchService):
            raise ValueError(f"switch service is unavailable: {key}")
        await service.async_turn_off()

    @property
    def fan_service(self) -> FanService | None:
        for sid in ("fan", "airPurifying", "wind"):
            service = self._services_by_sid.get(sid)
            if isinstance(service, FanService):
                return service
        return None

    @property
    def fan_is_on(self) -> bool | None:
        return self.is_on

    @property
    def fan_supports_turn_on_off(self) -> bool:
        """Return whether the Fan composite has a switch service."""

        return self._primary_switch_key is not None

    @property
    def cover_service(self) -> CoverService | None:
        return self._cover_service

    @property
    def cover_is_closed(self) -> bool | None:
        return self.cover_service.is_closed if self.cover_service else None

    @property
    def cover_position(self) -> int | None:
        return self.cover_service.current_position if self.cover_service else None

    @property
    def cover_supported_features(self) -> frozenset[str]:
        service = self.cover_service
        if service is None:
            return frozenset()
        return frozenset(
            feature
            for feature, supported in (
                ("open", service.supports_open),
                ("close", service.supports_close),
                ("stop", service.supports_stop),
                ("position", service.supports_position),
            )
            if supported
        )

    async def async_open_cover(self) -> None:
        if self.cover_service is None:
            raise ValueError("cover service is unavailable")
        await self.cover_service.async_open()

    async def async_close_cover(self) -> None:
        if self.cover_service is None:
            raise ValueError("cover service is unavailable")
        await self.cover_service.async_close()

    async def async_stop_cover(self) -> None:
        if self.cover_service is None:
            raise ValueError("cover service is unavailable")
        await self.cover_service.async_stop()

    async def async_set_cover_position(self, value: int) -> None:
        if self.cover_service is None:
            raise ValueError("cover service is unavailable")
        await self.cover_service.async_set_position(value)

    @property
    def humidifier_service(self) -> HumidifierService | None:
        return self._humidifier_service

    @property
    def humidifier_is_on(self) -> bool | None:
        return self.humidifier_service.is_on if self.humidifier_service else None

    @property
    def current_humidity(self) -> int | None:
        return self.humidifier_service.current_humidity if self.humidifier_service else None

    @property
    def target_humidity(self) -> int | None:
        return self.humidifier_service.target_humidity if self.humidifier_service else None

    @property
    def min_target_humidity(self) -> int | None:
        return self.humidifier_service.min_target_humidity if self.humidifier_service else None

    @property
    def max_target_humidity(self) -> int | None:
        return self.humidifier_service.max_target_humidity if self.humidifier_service else None

    @property
    def humidifier_modes(self) -> tuple[str, ...]:
        return self.humidifier_service.modes if self.humidifier_service else ()

    @property
    def humidifier_mode(self) -> str | None:
        return self.humidifier_service.mode if self.humidifier_service else None

    async def async_humidifier_turn_on(self) -> None:
        if self.humidifier_service is None:
            raise ValueError("humidifier service is unavailable")
        await self.humidifier_service.async_turn_on()

    async def async_humidifier_turn_off(self) -> None:
        if self.humidifier_service is None:
            raise ValueError("humidifier service is unavailable")
        await self.humidifier_service.async_turn_off()

    async def async_set_humidity(self, value: int) -> None:
        if self.humidifier_service is None:
            raise ValueError("humidifier service is unavailable")
        await self.humidifier_service.async_set_humidity(value)

    async def async_set_humidifier_mode(self, value: str) -> None:
        if self.humidifier_service is None:
            raise ValueError("humidifier service is unavailable")
        await self.humidifier_service.async_set_mode(value)

    @property
    def percentage(self) -> int | None:
        service = self.fan_service
        return service.percentage if service is not None else None

    @property
    def percentage_step(self) -> int | None:
        service = self.fan_service
        return service.percentage_step if service is not None else None

    @property
    def fan_supports_percentage(self) -> bool:
        service = self.fan_service
        return service is not None and service.supports_percentage

    @property
    def preset_modes(self) -> tuple[str, ...]:
        service = self.fan_service
        return service.preset_options if service is not None else ()

    @property
    def preset_mode(self) -> str | None:
        service = self.fan_service
        return service.preset_value if service is not None else None

    async def async_fan_turn_on(self) -> None:
        key = self._primary_switch_key
        if key is not None:
            await self.async_switch_turn_on(key)

    async def async_fan_turn_off(self) -> None:
        key = self._primary_switch_key
        if key is not None:
            await self.async_switch_turn_off(key)

    async def async_set_percentage(self, value: int) -> None:
        service = self.fan_service
        if service is None:
            raise ValueError("fan service is unavailable")
        await service.async_set_percentage(value)

    async def async_set_preset_mode(self, value: str) -> None:
        service = self.fan_service
        if service is None:
            raise ValueError("fan service is unavailable")
        await service.async_set_preset(value)

    @property
    def fan_supports_oscillation(self) -> bool:
        service = self.fan_service
        return service is not None and service.supports_oscillation

    @property
    def fan_oscillating(self) -> bool | None:
        service = self.fan_service
        return service.oscillating if service is not None else None

    async def async_set_oscillating(self, value: bool) -> None:
        service = self.fan_service
        if service is None:
            raise ValueError("fan service is unavailable")
        await service.async_set_oscillating(value)

    @property
    def brightness(self) -> int | None:
        service = self._services_by_sid.get("brightness")
        return service.brightness if isinstance(service, BrightnessService) else None

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        service = self._services_by_sid.get("colour")
        return service.rgb_color if isinstance(service, RgbService) else None

    @property
    def color_temperature(self) -> int | None:
        service = self._services_by_sid.get("cct")
        return (
            service.color_temperature
            if isinstance(service, ColorTemperatureService)
            else None
        )

    @property
    def colour_mode(self) -> int | None:
        value = self.value("colourMode", "mode")
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def supports_volume_control(self) -> bool:
        extension = self.extension(SpeakerExtension)
        return extension is not None and extension.supports_volume_control

    @property
    def sensor_keys(self) -> frozenset[str]:
        extension = self.extension(SpeakerExtension)
        keys = set(self._sensor_bindings)
        if extension is not None:
            keys.update(extension.sensor_keys)
        return frozenset(keys)

    @property
    def sensor_units(self) -> Mapping[str, str | None]:
        units: dict[str, str | None] = {}
        for key, (sid, field_name) in self._sensor_bindings.items():
            spec = self.profile.services.get(sid)
            field = spec.field(field_name) if spec is not None else None
            if field is not None:
                units[key] = field.unit
        return units

    @property
    def sensor_names(self) -> Mapping[str, str]:
        names: dict[str, str] = {}
        for key, (sid, field_name) in self._sensor_bindings.items():
            spec = self.profile.services.get(sid)
            field = spec.field(field_name) if spec is not None else None
            if field is not None:
                names[key] = (
                    (spec.description if spec is not None else None)
                    or field.label
                    or field.description
                    or (spec.name if spec is not None else None)
                    or field_name
                )
        return names

    @property
    def binary_sensor_keys(self) -> tuple[str, ...]:
        extension = self.extension(SpeakerExtension)
        keys = set(self._binary_bindings)
        if extension is not None:
            keys.update(extension.binary_sensor_keys)
        return tuple(sorted(keys))

    @property
    def binary_sensor_names(self) -> Mapping[str, str]:
        extension = self.extension(SpeakerExtension)
        names = {
            "battery_low": "Low battery",
            "charging": "Charging",
            "door": "Door",
            "motion": "Motion",
            "presence": "Presence",
            "gas": "Gas",
            "smoke": "Smoke",
            "water_leak": "Water leak",
        }
        for key, (sid, field_name) in self._binary_bindings.items():
            spec = self.profile.services.get(sid)
            field = spec.field(field_name) if spec is not None else None
            if field is not None:
                names[key] = (
                    (spec.description if spec is not None else None)
                    or field.label
                    or field.description
                    or (spec.name if spec is not None else None)
                    or key
                )
        if extension is not None:
            names.update(extension.binary_sensor_names)
        return names

    @property
    def binary_sensor_device_classes(self) -> Mapping[str, str]:
        extension = self.extension(SpeakerExtension)
        classes = {
            "battery_low": "battery",
            "charging": "battery_charging",
            "door": "door",
            "motion": "motion",
            "presence": "occupancy",
            "gas": "gas",
            "smoke": "smoke",
            "water_leak": "moisture",
        }
        if extension is not None:
            classes.update(extension.binary_sensor_device_classes)
        return classes

    @property
    def battery_level(self) -> int | None:
        extension = self.extension(SpeakerExtension)
        return extension.battery_level if extension is not None else None

    @property
    def speaker_state(self) -> str | None:
        extension = self.extension(SpeakerExtension)
        return extension.speaker_state if extension is not None else None

    def binary_sensor_is_on(self, key: str) -> bool | None:
        extension = self.extension(SpeakerExtension)
        if extension is not None and key in extension.binary_sensor_keys:
            return extension.binary_sensor_is_on(key)
        binding = self._binary_bindings.get(key)
        if binding is None:
            raise ValueError(f"unsupported binary sensor: {key}")
        sid, field = binding
        value = self.value(sid, field)
        if self._binary_semantics.get(key) == "smoke_level":
            return _smoke_level_is_on(value)
        if self._binary_semantics.get(key) == "gas_level":
            return _gas_level_is_on(value)
        if self._binary_semantics.get(key) == "gas_alarm":
            spec = self.profile.services.get(sid)
            profile_field = spec.field(field) if spec is not None else None
            return _gas_alarm_is_on(value, profile_field)
        if isinstance(value, str):
            return value.strip().lower() in {
                "1", "true", "on", "open", "detected"
            }
        if value is None:
            return None
        return value in (True, 1)

    def sensor_value(self, key: str) -> Any:
        extension = self.extension(SpeakerExtension)
        if extension is not None:
            if key == "battery_level":
                return extension.battery_level
            if key == "speaker_state":
                return extension.speaker_state
        binding = self._sensor_bindings.get(key)
        if binding is None:
            return None
        sid, field = binding
        value = self.value(sid, field)
        if isinstance(value, str):
            try:
                return float(value) if "." in value else int(value)
            except ValueError:
                return value
        return value

    @property
    def number_keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._number_bindings))

    @property
    def number_metadata(self) -> Mapping[str, tuple[str, float, float, float, str | None]]:
        metadata: dict[str, tuple[str, float, float, float, str | None]] = {}
        for key, (sid, field_name) in self._number_bindings.items():
            spec = self.profile.services.get(sid)
            field = spec.field(field_name) if spec is not None else None
            if (
                field is None
                or field.min_value is None
                or field.max_value is None
                or field.resolved_step is None
            ):
                continue
            label = field.label or field.description or f"{sid} {field_name}"
            label = spec.description or label
            metadata[key] = (
                label,
                float(field.min_value),
                float(field.max_value),
                float(field.resolved_step),
                field.unit,
            )
        return metadata

    def number_value(self, key: str) -> float | None:
        binding = self._number_bindings.get(key)
        if binding is None:
            return None
        sid, field = binding
        value = self.value(sid, field)
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    async def async_set_number(self, key: str, value: float) -> None:
        binding = self._number_bindings.get(key)
        if binding is None:
            raise ValueError(f"unsupported number: {key}")
        sid, field_name = binding
        spec = self.profile.services.get(sid)
        field = spec.field(field_name) if spec is not None else None
        if field is None or field.min_value is None or field.max_value is None:
            raise ValueError(f"number range is missing from the Profile: {key}")
        if not field.min_value <= value <= field.max_value:
            raise ValueError(f"number is outside the Profile range: {key}")
        from .services import _quantize

        await self.send_service(sid, {field_name: _quantize(value, field)})

    @property
    def select_keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._select_bindings))

    @property
    def select_names(self) -> Mapping[str, str]:
        names: dict[str, str] = {}
        for key, (sid, field_name) in self._select_bindings.items():
            spec = self.profile.services.get(sid)
            field = spec.field(field_name) if spec is not None else None
            if field is not None:
                names[key] = (
                    spec.description
                    or field.label
                    or field.description
                    or f"{sid} {field_name}"
                )
        return names

    @property
    def select_options(self) -> Mapping[str, tuple[str, ...]]:
        options: dict[str, tuple[str, ...]] = {}
        for key, (sid, field_name) in self._select_bindings.items():
            spec = self.profile.services.get(sid)
            field = spec.field(field_name) if spec is not None else None
            if field is not None:
                options[key] = tuple(label for label, _raw in field.enum_options)
        return options

    def select_value(self, key: str) -> str | None:
        binding = self._select_bindings.get(key)
        if binding is None:
            return None
        sid, field_name = binding
        spec = self.profile.services.get(sid)
        field = spec.field(field_name) if spec is not None else None
        if field is None:
            return None
        if sid == "lightMode" and field_name == "mode":
            context = self.value("colourMode", "mode")
            if context is not None:
                try:
                    if int(context) != 4:
                        return None
                except (TypeError, ValueError):
                    return None
        raw = self.value(sid, field_name)
        for label, option in field.enum_options:
            if str(raw) == option:
                return label
        return str(raw) if raw is not None else None

    async def async_select_option(self, key: str, option: str) -> None:
        binding = self._select_bindings.get(key)
        if binding is None:
            raise ValueError(f"unsupported select: {key}")
        sid, field_name = binding
        spec = self.profile.services.get(sid)
        field = spec.field(field_name) if spec is not None else None
        if field is None:
            raise ValueError(f"select field is missing from the Profile: {key}")
        for label, raw in field.enum_options:
            if label == option:
                extension = self.extension(RgbCctExtension)
                if (
                    extension is not None
                    and sid == "lightMode"
                    and field_name == "mode"
                ):
                    await extension.async_set_light_mode(
                        _coerce_profile_value(raw, field)
                    )
                    return
                await self.send_service(
                    sid,
                    {field_name: _coerce_profile_value(raw, field)},
                )
                return
        raise ValueError(f"unsupported select option: {option}")

    @property
    def media_state(self) -> str | None:
        extension = self.extension(SpeakerExtension)
        return extension.media_state if extension is not None else None

    @property
    def supported_media_actions(self) -> frozenset[str]:
        extension = self.extension(SpeakerExtension)
        return extension.supported_media_actions if extension is not None else frozenset()

    @property
    def volume_level(self) -> float | None:
        extension = self.extension(SpeakerExtension)
        return extension.volume_level if extension is not None else None

    @property
    def is_volume_muted(self) -> bool | None:
        extension = self.extension(SpeakerExtension)
        return extension.is_volume_muted if extension is not None else None

    @property
    def media_metadata(self) -> Mapping[str, Any]:
        extension = self.extension(SpeakerExtension)
        return extension.media_metadata if extension is not None else {}

    @property
    def cloud_service_ids(self) -> frozenset[str]:
        return frozenset(self._cloud_service_ids)

    @property
    def services_by_sid(self) -> Mapping[str, HuaweiService]:
        return self._services_by_sid

    @property
    def extensions(self) -> tuple[object, ...]:
        return self._extensions

    def service(self, sid: str) -> HuaweiService | None:
        return self._services_by_sid.get(sid)

    def extension(self, extension_type: type[Any]) -> Any | None:
        return next(
            (extension for extension in self._extensions if isinstance(extension, extension_type)),
            None,
        )

    def value(self, sid: str, field: str) -> Any:
        return self._state.get(sid, {}).get(field)

    @property
    def _primary_switch_key(self) -> str | None:
        if "switch" in self.switch_keys:
            return "switch"
        return self.switch_keys[0] if self.switch_keys else None

    async def send_service(self, sid: str, body: Mapping[str, Any]) -> None:
        if sid not in self.cloud_service_ids:
            raise ValueError(f"service is not present on device: {sid}")
        await self.command_gateway.async_send(
            device_id=self.dev_id,
            sid=sid,
            body=body,
        )

    async def async_turn_on(
        self,
        *,
        brightness: int | None = None,
        rgb_color: tuple[int, int, int] | None = None,
        color_temperature: int | None = None,
    ) -> None:
        key = self._primary_switch_key
        if key is not None:
            await self.async_switch_turn_on(key)
        if brightness is not None:
            await self.async_set_brightness(brightness)
        if rgb_color is not None:
            await self.async_set_rgb(rgb_color)
        if color_temperature is not None:
            await self.async_set_color_temperature(color_temperature)

    async def async_turn_off(self) -> None:
        key = self._primary_switch_key
        if key is not None:
            await self.async_switch_turn_off(key)

    async def async_set_brightness(self, value: int) -> None:
        service = self._services_by_sid.get("brightness")
        if service is None:
            raise ValueError("brightness service is unavailable")
        await service.async_set_brightness(value)  # type: ignore[attr-defined]

    async def async_set_rgb(self, value: tuple[int, int, int]) -> None:
        extension = self.extension(RgbCctExtension)
        if extension is not None:
            await extension.async_set_rgb(value)
            return
        service = self._services_by_sid.get("colour")
        if service is None:
            raise ValueError("RGB service is unavailable")
        await service.async_set_rgb(value)  # type: ignore[attr-defined]

    async def async_set_color_temperature(self, value: int) -> None:
        extension = self.extension(RgbCctExtension)
        if extension is not None:
            await extension.async_set_color_temperature(value)
            return
        service = self._services_by_sid.get("cct")
        if service is None:
            raise ValueError("color temperature service is unavailable")
        await service.async_set_color_temperature(value)  # type: ignore[attr-defined]

    async def async_media_play(self) -> None:
        extension = self.extension(SpeakerExtension)
        if extension is None:
            raise ValueError("speaker service is unavailable")
        await extension.async_media_play()

    async def async_media_pause(self) -> None:
        extension = self.extension(SpeakerExtension)
        if extension is None:
            raise ValueError("speaker service is unavailable")
        await extension.async_media_pause()

    async def async_media_stop(self) -> None:
        extension = self.extension(SpeakerExtension)
        if extension is None:
            raise ValueError("speaker service is unavailable")
        await extension.async_media_stop()

    async def async_media_previous_track(self) -> None:
        extension = self.extension(SpeakerExtension)
        if extension is None:
            raise ValueError("speaker service is unavailable")
        await extension.async_media_previous_track()

    async def async_media_next_track(self) -> None:
        extension = self.extension(SpeakerExtension)
        if extension is None:
            raise ValueError("speaker service is unavailable")
        await extension.async_media_next_track()

    async def async_set_volume_level(self, level: float) -> None:
        extension = self.extension(SpeakerExtension)
        if extension is None:
            raise ValueError("speaker service is unavailable")
        await extension.async_set_volume_level(level)

    def add_state_listener(self, listener: StateListener) -> None:
        self._listeners.add(listener)

    def remove_state_listener(self, listener: StateListener) -> None:
        self._listeners.discard(listener)

    @property
    def button_event_actions(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                action for _sid, _field_name, action in self._event_bindings()
            )
        )

    @property
    def button_event_names(self) -> Mapping[str, str]:
        names: dict[str, str] = {}
        for sid, _field_name, action in self._event_bindings():
            spec = self.profile.services.get(sid)
            if spec is not None:
                names.setdefault(action, spec.description or action)
        return names

    def add_event_listener(self, listener: EventListener) -> None:
        self._event_listeners.add(listener)

    def remove_event_listener(self, listener: EventListener) -> None:
        self._event_listeners.discard(listener)

    def handle_mqtt_message(self, topic: str, payload: bytes) -> bool:
        """Handle command ACKs and device state without mixing their semantics."""

        del topic
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
        events: list[HuaweiDeviceEvent] = []
        changed = False
        for item in services:
            if not isinstance(item, Mapping):
                continue
            sid = item.get("sid")
            data = item.get("data")
            if not isinstance(sid, str) or not isinstance(data, Mapping):
                continue
            timestamp = item.get("ts")
            if sid in self._event_service_ids() and not is_older_remote_timestamp(
                timestamp if isinstance(timestamp, str) else None,
                self._state_timestamps.get(sid),
            ):
                events.extend(self._parse_events(sid, data, timestamp))
            changed = self._merge_service_state(
                sid,
                data,
                timestamp,
            ) or changed
        if changed:
            self._notify_state_changed()
        for event in events:
            for listener in tuple(self._event_listeners):
                listener(event)
        return changed or bool(events)

    def apply_state_snapshot(
        self,
        services: Mapping[str, RemoteServiceState],
        *,
        online: bool | None = None,
    ) -> bool:
        changed = False
        for sid, service in services.items():
            changed = self._merge_service_state(
                sid,
                service.data,
                service.reported_timestamp,
            ) or changed
        if online is not None and online != self._descriptor.online:
            from dataclasses import replace

            self._descriptor = replace(self._descriptor, online=online)
            changed = True
        if changed:
            self._notify_state_changed()
        return changed

    def update_descriptor(self, descriptor: RemoteDeviceDescriptor) -> None:
        from dataclasses import replace

        self._descriptor = descriptor
        for sid, service in descriptor.service_states.items():
            if sid not in self._state:
                self._state[sid] = dict(service.data)
            if sid not in self._state_timestamps and service.reported_timestamp:
                self._state_timestamps[sid] = service.reported_timestamp
        self._cloud_service_ids = set(descriptor.service_states)
        self._rebuild_bindings()

    def close(self) -> None:
        self.command_gateway.close()
        self._listeners.clear()
        self._event_listeners.clear()

    def _rebuild_bindings(self) -> None:
        self._services_by_sid = {
            service.sid: service
            for service in (
                create_basic_service(self, spec)
                for spec in self.profile.available_services(self._cloud_service_ids)
            )
            if service is not None
        }
        self._bind_fan_preset_service()
        self._cover_service = create_cover_service(
            self,
            self.profile,
            self._cloud_service_ids,
        )
        self._humidifier_service = create_humidifier_service(
            self,
            self.profile,
            self._cloud_service_ids,
        )
        self._extensions = create_extensions(self)
        self._build_generic_bindings()

    def _bind_fan_preset_service(self) -> None:
        service = self._services_by_sid.get("fan")
        if not isinstance(service, FanService):
            return
        for sid, spec in self.profile.services.items():
            if sid == service.sid or sid not in self._cloud_service_ids:
                continue
            if spec.kind not in {"mode", "fanmode"}:
                continue
            for field_name in service.preset_field_names:
                field = spec.field(field_name)
                if field is not None and field.enum_options:
                    service.bind_preset_service(spec)
                    return

    def _build_generic_bindings(self) -> None:
        self._sensor_bindings = {}
        self._sensor_binding_priorities = {}
        self._binary_bindings = {}
        self._binary_semantics = {}
        self._number_bindings = {}
        self._select_bindings = {}
        ignored_control_kinds = {
            "delay",
            "devota",
            "netinfo",
            "ota",
            "streamer",
            "timer",
            "update",
        }
        select_kinds = {
            "airpurifying",
            "colourmode",
            "fan",
            "gear",
            "lightmode",
            "mode",
        }
        number_kinds = {
            "airpurifying",
            "alarmthreshold",
            "electricity",
            "fan",
            "gear",
            "powerelectricity",
            "temperature",
            "water",
            "wind",
        }
        has_smoke_service = any(
            candidate_sid in self._cloud_service_ids
            and candidate_spec.kind == "smoke"
            for candidate_sid, candidate_spec in self.profile.services.items()
        )
        has_gas_service = any(
            candidate_sid in self._cloud_service_ids
            and (
                candidate_spec.kind == "gas"
                or (
                    candidate_spec.kind == "equipmentstatus"
                    and candidate_spec.field("ConcentrationValue") is not None
                )
            )
            for candidate_sid, candidate_spec in self.profile.services.items()
        )
        alarm_sensor_key = (
            "smoke" if has_smoke_service else "gas" if has_gas_service else None
        )
        for sid, spec in self.profile.services.items():
            if sid not in self._cloud_service_ids:
                continue
            if self._is_absorbed_by_composite(sid, spec):
                continue
            service_type = spec.kind
            fields = set(spec.fields)
            for key, (service_kinds, candidates) in _SENSOR_RULES.items():
                if service_type not in service_kinds:
                    continue
                field = next(
                    (item for item in candidates if item in fields),
                    None,
                )
                if field is not None:
                    priority = _SENSOR_FIELD_PRIORITIES.get(key, {}).get(field, 0)
                    if priority > self._sensor_binding_priorities.get(key, -1):
                        self._sensor_bindings[key] = (sid, field)
                        self._sensor_binding_priorities[key] = priority
            if service_type in _BINARY_SERVICE_TYPES or (
                service_type == "alarm" and alarm_sensor_key is not None
            ):
                if service_type == "pir":
                    binary_fields = {"presence": _BINARY_FIELDS["presence"]}
                elif service_type == "motionsensor":
                    binary_fields = {"motion": _BINARY_FIELDS["motion"]}
                elif service_type == "gas":
                    binary_fields = {"gas": _BINARY_FIELDS["gas"]}
                elif service_type == "smoke":
                    binary_fields = {"smoke": _BINARY_FIELDS["smoke"]}
                elif service_type == "battery":
                    binary_fields = {"battery_low": _BINARY_FIELDS["battery_low"]}
                elif service_type == "alarm" and alarm_sensor_key is not None:
                    binary_fields = {alarm_sensor_key: {"alarm"}}
                else:
                    binary_fields = _BINARY_FIELDS
                for key, candidates in binary_fields.items():
                    field = next(
                        (item for item in candidates if item in fields),
                        None,
                    )
                    if field is not None and (
                        key not in self._binary_bindings or service_type == "alarm"
                    ):
                        self._binary_bindings[key] = (sid, field)
                        self._binary_semantics[key] = (
                            "smoke_level"
                            if service_type == "smoke" and field == "level"
                            else "gas_level"
                            if service_type == "gas" and field == "level"
                            else "gas_alarm"
                            if service_type == "alarm"
                            and key == "gas"
                            and field == "alarm"
                            else "boolean"
                        )

            fan_service = self._services_by_sid.get(sid)
            fan_fields: set[str] = set()
            if isinstance(fan_service, FanService):
                if fan_service.percentage_field is not None:
                    fan_fields.add(fan_service.percentage_field[0])
                if fan_service.preset_field is not None:
                    fan_fields.add(fan_service.preset_field[0])
                if fan_service.oscillation_field is not None:
                    fan_fields.add(fan_service.oscillation_field[0])
            if service_type not in ignored_control_kinds:
                for field_name, field in spec.fields.items():
                    if not field.writable or field_name in fan_fields:
                        continue
                    key = f"{sid}.{field_name}"
                    if field.enum_options and service_type in select_kinds:
                        self._select_bindings[key] = (sid, field_name)
                    if (
                        service_type in number_kinds
                        and not field.enum_options
                        and field.min_value is not None
                        and field.max_value is not None
                        and field.resolved_step is not None
                        and (field.data_type or "").strip().lower()
                        in {"int", "integer", "float", "double", "number"}
                        and sid not in {"brightness", "cct", "colour"}
                    ):
                        self._number_bindings[key] = (sid, field_name)

    def _is_absorbed_by_composite(
        self,
        sid: str,
        spec: Any,
    ) -> bool:
        field_names = set(spec.fields)
        if self.cover_service is not None and sid in {
            item
            for item in (
                self.cover_service.action_spec.sid
                if self.cover_service.action_spec is not None
                else None,
                self.cover_service.position_spec.sid
                if self.cover_service.position_spec is not None
                else None,
            )
            if item is not None
        }:
            return True
        if self.humidifier_service is not None:
            if sid == self.humidifier_service.humidity_spec.sid:
                return field_names.intersection({"current", "target", "humidity", "value"}) != set()
            if (
                self.humidifier_service.gear_spec is not None
                and sid == self.humidifier_service.gear_spec.sid
            ):
                return True
        fan_service = self.fan_service
        if (
            fan_service is not None
            and sid == fan_service.preset_sid
            and sid != fan_service.sid
        ):
            return True
        return False

    def _event_service_ids(self) -> frozenset[str]:
        return frozenset(sid for sid, _field, _action in self._event_bindings())

    def _event_bindings(self) -> tuple[tuple[str, str, str], ...]:
        bindings: list[tuple[str, str, str]] = []
        for sid in sorted(self._cloud_service_ids):
            spec = self.profile.services.get(sid)
            if spec is None:
                continue
            sid_key = sid.lower()
            if sid_key == "scene":
                fields = tuple(_SCENE_ACTION_FIELDS.items())
            else:
                rule = _EVENT_SERVICE_RULES.get(sid_key)
                fields = (
                    tuple((field_name, rule[1]) for field_name in rule[0])
                    if rule is not None
                    else ()
                )
            for field_name, action in fields:
                if spec.field(field_name) is not None:
                    bindings.append((sid, field_name, action))
        return tuple(bindings)

    def _parse_events(
        self,
        sid: str,
        data: Mapping[str, Any],
        timestamp: Any,
    ) -> list[HuaweiDeviceEvent]:
        events: list[HuaweiDeviceEvent] = []
        bindings = {
            (binding_sid, field_name): action
            for binding_sid, field_name, action in self._event_bindings()
            if binding_sid == sid
        }
        for (_binding_sid, field_name), action in bindings.items():
            key_code = _int_value(data.get(field_name))
            if key_code is None or key_code <= 0:
                continue
            button_id = None if sid.lower() == "devstateserv" else key_code
            name = self._event_name(sid, field_name, key_code, action)
            events.append(
                HuaweiDeviceEvent(
                    action=action,
                    key_code=key_code,
                    button_id=button_id,
                    name=name,
                    timestamp=timestamp if isinstance(timestamp, str) else None,
                )
            )
        return events

    def _event_name(
        self,
        sid: str,
        field_name: str,
        value: int,
        action: str,
    ) -> str | None:
        spec = self.profile.services.get(sid)
        field = spec.field(field_name) if spec is not None else None
        if field is not None:
            for label, raw in field.enum_options:
                if str(value) == raw:
                    return label
        button_id, button_name = self._button_for_code(value)
        if button_name is not None:
            return button_name
        if action == "ring":
            return f"Ring {value}"
        return f"Button {button_id or value}"

    def _button_for_code(self, key_code: int) -> tuple[int | None, str | None]:
        button_ids = sorted(
            (
                int(sid[6:]),
                sid,
            )
            for sid in self._cloud_service_ids
            if sid.lower().startswith("button") and sid[6:].isdigit()
        )
        for button_id, sid in button_ids:
            if button_id != key_code:
                continue
            spec = self.profile.services.get(sid)
            name_field = spec.field("name") if spec is not None else None
            value = self.value(sid, "name")
            return button_id, value if isinstance(value, str) and value else (
                name_field.label if name_field is not None else f"Button {button_id}"
            )
        return None, None

    def _merge_service_state(
        self,
        sid: str,
        data: Mapping[str, Any],
        timestamp: Any,
    ) -> bool:
        timestamp_text = timestamp if isinstance(timestamp, str) and timestamp else None
        previous_timestamp = self._state_timestamps.get(sid)
        if is_older_remote_timestamp(timestamp_text, previous_timestamp):
            return False
        before = self._state.get(sid, {})
        after = {**before, **dict(data)}
        changed = after != before
        if changed:
            self._state[sid] = after
        if timestamp_text and timestamp_text != previous_timestamp:
            self._state_timestamps[sid] = timestamp_text
        return changed

    def _notify_state_changed(self) -> None:
        for listener in tuple(self._listeners):
            listener()
