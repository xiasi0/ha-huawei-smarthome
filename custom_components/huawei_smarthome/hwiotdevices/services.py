"""Generic Huawei SmartHome service mappings."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TYPE_CHECKING

from .profile import ProfileField, ProfileService

if TYPE_CHECKING:
    from .runtime import HuaweiDeviceRuntime


def _as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, str):
        if value.strip().lower() in {"1", "true", "on"}:
            return True
        if value.strip().lower() in {"0", "false", "off"}:
            return False
    if isinstance(value, (bool, int, float)):
        return bool(value)
    return None


def _coerce_profile_value(value: str, field: ProfileField) -> Any:
    """Convert a raw Profile enum value to its declared data type."""

    data_type = (field.data_type or "").strip().lower()
    if data_type in {"bool", "boolean"}:
        return _as_bool(value)
    if data_type in {"int", "integer"}:
        try:
            return int(value)
        except ValueError:
            return value
    if data_type in {"float", "double", "number"}:
        try:
            return float(value)
        except ValueError:
            return value
    return value


def _switch_value(field: ProfileField | None, enabled: bool) -> Any:
    """Resolve the switch command from the Profile enum definition."""

    if field is not None:
        for raw, description in field.enum_values:
            raw_text = raw.strip().lower()
            label = (description or "").strip().lower()
            is_enabled = raw_text in {"1", "true", "on"} or label in {
                "1",
                "true",
                "on",
                "开",
                "开启",
                "打开",
                "启动",
            }
            is_disabled = raw_text in {"0", "false", "off"} or label in {
                "0",
                "false",
                "off",
                "关",
                "关闭",
                "停止",
            }
            if (enabled and is_enabled) or (not enabled and is_disabled):
                return _coerce_profile_value(raw, field)
        if (field.data_type or "").strip().lower() in {"bool", "boolean"}:
            return enabled
    raise ValueError("switch enum values are missing from the Profile")


class HuaweiService:
    """Base service bound to one raw Huawei ``sid``."""

    def __init__(self, device: "HuaweiDeviceRuntime", spec: ProfileService) -> None:
        self.device = device
        self.spec = spec
        self.sid = spec.sid

    def value(self, field: str) -> Any:
        return self.device.value(self.sid, field)

    async def send(self, body: Mapping[str, Any]) -> None:
        await self.device.send_service(self.sid, body)


class SwitchService(HuaweiService):
    """Basic on/off service."""

    field_name = "on"

    @property
    def is_on(self) -> bool | None:
        return _as_bool(self.value(self.field_name))

    @property
    def field(self) -> ProfileField | None:
        return self.spec.field(self.field_name)

    async def async_turn_on(self) -> None:
        await self.send({self.field_name: _switch_value(self.field, True)})

    async def async_turn_off(self) -> None:
        await self.send({self.field_name: _switch_value(self.field, False)})


class BrightnessService(HuaweiService):
    """Brightness service with Profile range conversion to HA 0..255."""

    field_name = "brightness"

    @property
    def field(self) -> ProfileField | None:
        return self.spec.field(self.field_name)

    @property
    def brightness(self) -> int | None:
        value = self.value(self.field_name)
        if isinstance(value, str):
            try:
                value = float(value)
            except ValueError:
                return None
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        value_range = _field_range(self.field)
        if value_range is None:
            return None
        minimum, maximum = value_range
        value = min(max(float(value), float(minimum)), float(maximum))
        return round((value - minimum) * 255 / (maximum - minimum))

    async def async_set_brightness(self, value: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("brightness must be an integer")
        if not 0 <= value <= 255:
            raise ValueError("brightness must be between 0 and 255")
        value_range = _field_range(self.field)
        if value_range is None or self.field is None:
            raise ValueError("brightness range is missing from the Profile")
        minimum, maximum = value_range
        device_value = _quantize(
            minimum + value * (maximum - minimum) / 255,
            self.field,
        )
        await self.send({self.field_name: device_value})


class ColorTemperatureService(HuaweiService):
    """Color-temperature service using Profile Kelvin bounds."""

    field_name = "colorTemperature"

    @property
    def field(self) -> ProfileField | None:
        return self.spec.field(self.field_name)

    @property
    def color_temperature(self) -> int | None:
        value = self.value(self.field_name)
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    async def async_set_color_temperature(self, value: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("color temperature must be an integer")
        value_range = _field_range(self.field)
        if value_range is None or self.field is None:
            raise ValueError("color temperature range is missing from the Profile")
        minimum, maximum = value_range
        if not minimum <= value <= maximum:
            raise ValueError(
                f"color temperature must be between {minimum} and {maximum}"
            )
        await self.send({self.field_name: _quantize(value, self.field)})


class RgbService(HuaweiService):
    """RGB service using red/green/blue characteristics."""

    field_names = ("red", "green", "blue")

    def _field_for(self, name: str) -> ProfileField | None:
        return self.spec.field(name)

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        values: list[int] = []
        for name in self.field_names:
            field = self._field_for(name)
            value_range = _field_range(field)
            if field is None or value_range is None:
                return None
            value = self.value(name)
            number = _to_ha_range(value, value_range)
            if number is None:
                return None
            values.append(number)
        return tuple(values)  # type: ignore[return-value]

    async def async_set_rgb(self, value: tuple[int, int, int]) -> None:
        if len(value) != 3 or any(
            isinstance(channel, bool) or not isinstance(channel, int)
            or not 0 <= channel <= 255
            for channel in value
        ):
            raise ValueError("RGB color must contain three channels from 0 to 255")
        body: dict[str, int | float] = {}
        for name, channel in zip(self.field_names, value):
            field = self._field_for(name)
            value_range = _field_range(field)
            if field is None or value_range is None or not _field_step_valid(field):
                raise ValueError(f"RGB range is missing from the Profile: {name}")
            minimum, maximum = value_range
            body[name] = _quantize(
                minimum + channel * (maximum - minimum) / 255,
                field,
            )
        await self.send(body)


class FanService(HuaweiService):
    """Generic fan and air-purifier controls from Profile fields."""

    percentage_field_names = ("speed", "gear", "windSpeed")
    preset_field_names = ("mode", "direction")

    @property
    def percentage_field(self) -> tuple[str, ProfileField] | None:
        for name in self.percentage_field_names:
            field = self.spec.field(name)
            if field is not None and _field_range(field) is not None:
                return name, field
        return None

    @property
    def preset_field(self) -> tuple[str, ProfileField] | None:
        for name in self.preset_field_names:
            field = self.spec.field(name)
            if field is not None and field.enum_options:
                return name, field
        return None

    @property
    def supports_percentage(self) -> bool:
        return self.percentage_field is not None

    @property
    def supports_preset(self) -> bool:
        return self.preset_field is not None

    @property
    def percentage_step(self) -> int | None:
        binding = self.percentage_field
        if binding is None:
            return None
        _name, field = binding
        value_range = _field_range(field)
        if value_range is None or field.resolved_step is None:
            return None
        minimum, maximum = value_range
        return max(1, round(float(field.resolved_step) * 100 / (maximum - minimum)))

    @property
    def percentage(self) -> int | None:
        binding = self.percentage_field
        if binding is None:
            return None
        name, field = binding
        value_range = _field_range(field)
        if value_range is None:
            return None
        try:
            value = float(self.value(name))
        except (TypeError, ValueError):
            return None
        minimum, maximum = value_range
        value = min(max(value, minimum), maximum)
        return round((value - minimum) * 100 / (maximum - minimum))

    @property
    def preset_options(self) -> tuple[str, ...]:
        binding = self.preset_field
        return (
            tuple(label for label, _raw in binding[1].enum_options)
            if binding
            else ()
        )

    @property
    def preset_value(self) -> str | None:
        binding = self.preset_field
        if binding is None:
            return None
        name, field = binding
        raw = self.value(name)
        for label, option in field.enum_options:
            if str(raw) == option:
                return label
        return str(raw) if raw is not None else None

    async def async_set_percentage(self, value: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
            raise ValueError("fan percentage must be between 0 and 100")
        binding = self.percentage_field
        if binding is None:
            raise ValueError("fan percentage is unavailable")
        name, field = binding
        value_range = _field_range(field)
        if value_range is None:
            raise ValueError("fan percentage range is missing from the Profile")
        minimum, maximum = value_range
        await self.send(
            {
                name: _quantize(
                    minimum + value * (maximum - minimum) / 100,
                    field,
                )
            }
        )

    async def async_set_preset(self, value: str) -> None:
        binding = self.preset_field
        if binding is None:
            raise ValueError("fan preset is unavailable")
        name, field = binding
        for label, raw in field.enum_options:
            if label == value:
                await self.send({name: _coerce_profile_value(raw, field)})
                return
        raise ValueError(f"unsupported fan preset: {value}")


class CoverService:
    """Compose Profile services that describe a curtain or blind."""

    def __init__(
        self,
        device: "HuaweiDeviceRuntime",
        action_spec: ProfileService | None,
        position_spec: ProfileService | None,
    ) -> None:
        self.device = device
        self.action_spec = action_spec
        self.position_spec = position_spec
        self.action_field = _first_field(action_spec, ("mode", "action"))
        self.target_field = _first_writable_field(
            position_spec,
            ("target", "position", "level"),
        )
        self.current_field = _first_readable_field(
            position_spec,
            ("current", "position", "level"),
        )

    @property
    def current_position(self) -> int | None:
        value = self._position_value(self.current_field)
        if value is None:
            return None
        value_range = _field_range(self.current_field)
        if value_range is None:
            return None
        minimum, maximum = value_range
        return round((value - minimum) * 100 / (maximum - minimum))

    @property
    def is_closed(self) -> bool | None:
        position = self.current_position
        if position is not None:
            return position == 0
        raw = self._action_value()
        if raw is None or self.action_field is None:
            return None
        if self._enum_matches(raw, ("close", "closed", "关", "关闭")):
            return True
        if self._enum_matches(raw, ("open", "opened", "开", "打开")):
            return False
        return None

    @property
    def supports_position(self) -> bool:
        return _field_range(self.target_field) is not None

    @property
    def supports_open(self) -> bool:
        return self._action_raw(("open", "opened", "开", "打开")) is not None

    @property
    def supports_close(self) -> bool:
        return self._action_raw(("close", "closed", "关", "关闭")) is not None

    @property
    def supports_stop(self) -> bool:
        return self._action_raw(("pause", "stop", "暂停", "停止")) is not None

    async def async_open(self) -> None:
        await self._send_action(("open", "opened", "开", "打开"))

    async def async_close(self) -> None:
        await self._send_action(("close", "closed", "关", "关闭"))

    async def async_stop(self) -> None:
        await self._send_action(("pause", "stop", "暂停", "停止"))

    async def async_set_position(self, value: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
            raise ValueError("cover position must be between 0 and 100")
        if self.position_spec is None or self.target_field is None:
            raise ValueError("cover position is unavailable")
        value_range = _field_range(self.target_field)
        if value_range is None:
            raise ValueError("cover position range is missing from the Profile")
        minimum, maximum = value_range
        await self.device.send_service(
            self.position_spec.sid,
            {
                self.target_field.name: _quantize(
                    minimum + value * (maximum - minimum) / 100,
                    self.target_field,
                )
            },
        )

    def _action_raw(self, tokens: tuple[str, ...]) -> Any | None:
        field = self.action_field
        if field is None or not field.writable:
            return None
        for raw, description in field.enum_values:
            text = f"{raw} {description or ''}".lower()
            if any(token.lower() in text for token in tokens):
                return _coerce_profile_value(raw, field)
        return None

    async def _send_action(self, tokens: tuple[str, ...]) -> None:
        if self.action_spec is None or self.action_field is None:
            raise ValueError("cover action is unavailable")
        value = self._action_raw(tokens)
        if value is None:
            raise ValueError("cover action is unavailable in the Profile")
        await self.device.send_service(
            self.action_spec.sid,
            {self.action_field.name: value},
        )

    def _action_value(self) -> Any:
        if self.action_spec is None or self.action_field is None:
            return None
        return self.device.value(self.action_spec.sid, self.action_field.name)

    def _position_value(self, field: ProfileField | None) -> float | None:
        if field is None or self.position_spec is None:
            return None
        value = self.device.value(self.position_spec.sid, field.name)
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _enum_matches(self, value: Any, tokens: tuple[str, ...]) -> bool:
        if self.action_field is None:
            return False
        for raw, description in self.action_field.enum_values:
            if str(value) != raw:
                continue
            text = f"{raw} {description or ''}".lower()
            return any(token.lower() in text for token in tokens)
        return False


class HumidifierService:
    """Compose Profile services that describe a humidifier."""

    def __init__(
        self,
        device: "HuaweiDeviceRuntime",
        humidity_spec: ProfileService,
        gear_spec: ProfileService | None,
        switch: SwitchService,
    ) -> None:
        self.device = device
        self.humidity_spec = humidity_spec
        self.gear_spec = gear_spec
        self.switch = switch
        self.current_field = _first_readable_field(
            humidity_spec,
            ("current", "humidity", "value"),
        )
        self.target_field = _first_writable_field(
            humidity_spec,
            ("target", "humidity", "value"),
        )
        self.mode_field = _first_enum_field(gear_spec, ("gear", "mode"))

    @property
    def is_on(self) -> bool | None:
        return self.switch.is_on

    @property
    def current_humidity(self) -> int | None:
        value = self._value(self.current_field)
        return round(value) if value is not None else None

    @property
    def target_humidity(self) -> int | None:
        value = self._value(self.target_field)
        return round(value) if value is not None else None

    @property
    def min_target_humidity(self) -> int | None:
        value = self.target_field.min_value if self.target_field else None
        return int(value) if value is not None else None

    @property
    def max_target_humidity(self) -> int | None:
        value = self.target_field.max_value if self.target_field else None
        return int(value) if value is not None else None

    @property
    def modes(self) -> tuple[str, ...]:
        return (
            tuple(label for label, _raw in self.mode_field.enum_options)
            if self.mode_field is not None
            else ()
        )

    @property
    def mode(self) -> str | None:
        if self.mode_field is None or self.gear_spec is None:
            return None
        raw = self.device.value(self.gear_spec.sid, self.mode_field.name)
        for label, option in self.mode_field.enum_options:
            if str(raw) == option:
                return label
        return str(raw) if raw is not None else None

    async def async_turn_on(self) -> None:
        await self.switch.async_turn_on()

    async def async_turn_off(self) -> None:
        await self.switch.async_turn_off()

    async def async_set_humidity(self, value: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or self.target_field is None:
            raise ValueError("target humidity is invalid")
        if (
            self.target_field.min_value is not None
            and value < self.target_field.min_value
        ) or (
            self.target_field.max_value is not None
            and value > self.target_field.max_value
        ):
            raise ValueError("target humidity is outside the Profile range")
        await self.device.send_service(
            self.humidity_spec.sid,
            {
                self.target_field.name: _quantize(value, self.target_field)
                if self.target_field.resolved_step is not None
                else value
            },
        )

    async def async_set_mode(self, value: str) -> None:
        if self.mode_field is None or self.gear_spec is None:
            raise ValueError("humidifier modes are unavailable")
        for label, raw in self.mode_field.enum_options:
            if label == value:
                await self.device.send_service(
                    self.gear_spec.sid,
                    {self.mode_field.name: _coerce_profile_value(raw, self.mode_field)},
                )
                return
        raise ValueError(f"unsupported humidifier mode: {value}")

    def _value(self, field: ProfileField | None) -> float | None:
        if field is None:
            return None
        value = self.device.value(self.humidity_spec.sid, field.name)
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None


def create_basic_service(
    device: "HuaweiDeviceRuntime",
    spec: ProfileService,
) -> HuaweiService | None:
    """Create a basic service only when its Profile mapping is unambiguous."""

    service_type = spec.kind
    if service_type == "switch" or _is_switch_sid(spec.sid):
        field = spec.field("on")
        return SwitchService(device, spec) if field and field.writable else None
    if service_type == "brightness" or spec.sid == "brightness":
        field = spec.field("brightness")
        return (
            BrightnessService(device, spec)
            if (
                field
                and field.writable
                and _field_range(field) is not None
                and _field_step_valid(field)
            )
            else None
        )
    if service_type in {"cct", "colortemperature", "color_temperature"} or spec.sid == "cct":
        field = spec.field("colorTemperature")
        return (
            ColorTemperatureService(device, spec)
            if (
                field
                and field.writable
                and _field_range(field) is not None
                and _field_step_valid(field)
            )
            else None
        )
    if service_type in {"colour", "color", "rgb"} or spec.sid in {"colour", "color"}:
        if all(
            (
                (field := spec.field(name)) is not None
                and field.writable
                and _field_range(field) is not None
                and _field_step_valid(field)
            )
            for name in ("red", "green", "blue")
        ):
            return RgbService(device, spec)
    if service_type in {"fan", "airpurifying", "wind"} or spec.sid in {
        "fan",
        "airPurifying",
        "wind",
    }:
        service = FanService(device, spec)
        if service.supports_percentage or service.supports_preset:
            return service
    return None


def create_cover_service(
    device: "HuaweiDeviceRuntime",
    profile: "ProductProfile",
    cloud_service_ids: set[str],
) -> CoverService | None:
    """Create a cover composition from Profile action/position services."""

    action_spec = next(
        (
            spec
            for sid, spec in profile.services.items()
            if sid in cloud_service_ids
            and sid.lower() in {"mode", "action", "cover", "curtain"}
            and _first_enum_field(spec, ("mode", "action")) is not None
        ),
        None,
    )
    position_spec = next(
        (
            spec
            for sid, spec in profile.services.items()
            if sid in cloud_service_ids
            and sid.lower() in {"opener", "position", "cover", "curtain", "blind"}
            and (
                _first_readable_field(spec, ("current", "position", "level"))
                is not None
                or _first_writable_field(spec, ("target", "position", "level"))
                is not None
            )
        ),
        None,
    )
    if action_spec is None and position_spec is None:
        return None
    service = CoverService(device, action_spec, position_spec)
    if not any(
        (
            service.supports_open,
            service.supports_close,
            service.supports_stop,
            service.supports_position,
        )
    ):
        return None
    return service


def create_humidifier_service(
    device: "HuaweiDeviceRuntime",
    profile: "ProductProfile",
    cloud_service_ids: set[str],
) -> HumidifierService | None:
    """Create a humidifier composition from Profile humidity services."""

    switch = device.service("switch")
    if not isinstance(switch, SwitchService):
        return None
    humidity_spec = next(
        (
            spec
            for sid, spec in profile.services.items()
            if sid in cloud_service_ids
            and sid.lower() in {"humidity", "humidifier"}
            and _first_writable_field(spec, ("target", "humidity", "value"))
            is not None
        ),
        None,
    )
    if humidity_spec is None:
        return None
    gear_spec = next(
        (
            spec
            for sid, spec in profile.services.items()
            if sid in cloud_service_ids
            and sid.lower() in {"gear", "humiditymode", "mode"}
            and _first_enum_field(spec, ("gear", "mode")) is not None
        ),
        None,
    )
    return HumidifierService(device, humidity_spec, gear_spec, switch)


def _is_switch_sid(sid: str) -> bool:
    suffix = sid.strip().lower()[6:]
    return sid.strip().lower() == "switch" or (
        suffix.isdigit() and bool(suffix)
    )


def _first_field(
    spec: ProfileService | None,
    names: tuple[str, ...],
) -> ProfileField | None:
    if spec is None:
        return None
    return next((spec.field(name) for name in names if spec.field(name)), None)


def _first_writable_field(
    spec: ProfileService | None,
    names: tuple[str, ...],
) -> ProfileField | None:
    field = _first_field(spec, names)
    return field if field is not None and field.writable else None


def _first_readable_field(
    spec: ProfileService | None,
    names: tuple[str, ...],
) -> ProfileField | None:
    field = _first_field(spec, names)
    return field if field is not None and field.readable else None


def _first_enum_field(
    spec: ProfileService | None,
    names: tuple[str, ...],
) -> ProfileField | None:
    field = _first_field(spec, names)
    return field if field is not None and field.enum_options else None


def _field_range(field: ProfileField | None) -> tuple[float, float] | None:
    """Return a valid Profile range without inventing product limits."""

    if field is None:
        return None
    minimum = field.min_value
    maximum = field.max_value
    if minimum is None or maximum is None or maximum <= minimum:
        return None
    return float(minimum), float(maximum)


def _field_step_valid(field: ProfileField) -> bool:
    """Return whether a declared Profile step can be applied."""

    step = field.resolved_step
    return step is None or step > 0


def _to_ha_range(
    value: Any,
    value_range: tuple[float, float],
) -> int | None:
    """Convert one Profile value to the HA RGB channel range."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    minimum, maximum = value_range
    number = min(max(number, minimum), maximum)
    return round((number - minimum) * 255 / (maximum - minimum))


def _quantize(value: float, field: ProfileField) -> int | float:
    """Round a device value to the Profile step, when one is declared."""

    step = field.resolved_step
    if step is None:
        return value
    if step <= 0:
        raise ValueError(f"invalid Profile step for {field.name}")
    if field.min_value is None:
        raise ValueError(f"Profile minimum is missing for {field.name}")
    minimum = float(field.min_value)
    quantized = minimum + round((value - minimum) / float(step)) * float(step)
    if isinstance(step, int) and isinstance(field.min_value, int):
        return int(round(quantized))
    return quantized


