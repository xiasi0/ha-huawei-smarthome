"""User-contributed protocol for Huawei product 100z."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_COLOUR_MODE_RGB = 0
_COLOUR_MODE_COLOR_TEMP = 1
_COLOUR_MODE_PRESET = 4


def _service(profile: Mapping[str, Any], sid: str) -> Mapping[str, Any] | None:
    for service in profile.get("services", ()):
        if isinstance(service, Mapping) and service.get("serviceId") == sid:
            return service
    return None


def _field(
    profile: Mapping[str, Any],
    sid: str,
    name: str,
) -> Mapping[str, Any] | None:
    service = _service(profile, sid)
    if service is None:
        return None
    for field in service.get("characteristics", ()):
        if isinstance(field, Mapping) and field.get("characteristicName") == name:
            return field
    return None


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _profile_range(field: Mapping[str, Any]) -> tuple[float, float] | None:
    minimum = _number(field.get("min"))
    maximum = _number(field.get("max"))
    if minimum is None or maximum is None or maximum <= minimum:
        return None
    return float(minimum), float(maximum)


def _profile_step(field: Mapping[str, Any]) -> float | None:
    step = _number(field.get("step"))
    if step is None or step <= 0:
        return None
    return float(step)


def _device_brightness_to_ha(
    value: Any,
    field: Mapping[str, Any],
) -> int | None:
    """Convert a product brightness value to HA's 0..255 scale."""

    number = _number(value)
    value_range = _profile_range(field)
    if number is None or value_range is None:
        return None
    minimum, maximum = value_range
    number = min(max(float(number), minimum), maximum)
    return round((number - minimum) * 255 / (maximum - minimum))


def _ha_brightness_to_device(
    value: Any,
    field: Mapping[str, Any],
) -> int | float:
    """Convert HA's 0..255 brightness to the product Profile range."""

    number = _number(value)
    value_range = _profile_range(field)
    if number is None or value_range is None:
        raise ValueError("100z brightness range is missing from the Profile")
    minimum, maximum = value_range
    number = min(max(float(number), 0.0), 255.0)
    device_value = minimum + number * (maximum - minimum) / 255
    step = _profile_step(field)
    if step is not None:
        device_value = minimum + round((device_value - minimum) / step) * step
    if (field.get("characteristicType") or "").casefold() in {
        "int",
        "integer",
    }:
        return int(round(device_value))
    return device_value


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.casefold() in {"1", "true", "on"}:
            return True
        if value.casefold() in {"0", "false", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _colour_mode_value(context: DeviceContext) -> int | None:
    value = _number(context.value("colourMode", "mode"))
    return int(value) if value is not None else None


def _light_mode_value(context: DeviceContext) -> int | None:
    value = _number(context.value("lightMode", "mode"))
    return int(value) if value is not None else None


def _coerce_profile_value(
    value: Any,
    field: Mapping[str, Any] | None,
) -> Any:
    """Encode a Profile value using its declared characteristic type."""

    data_type = str((field or {}).get("characteristicType") or "").casefold()
    if data_type in {"int", "integer", "enum"}:
        number = _number(value)
        if number is not None:
            return int(number) if float(number).is_integer() else number
    if data_type in {"float", "double", "number"}:
        number = _number(value)
        if number is not None:
            return float(number)
    if not data_type:
        number = _number(value)
        if number is not None:
            return number
    return value


def _mode_value(profile: Mapping[str, Any], value: int) -> int | float:
    field = _field(profile, "colourMode", "mode")
    if field is not None:
        for option in field.get("enumList", ()):
            if not isinstance(option, Mapping):
                continue
            raw = option.get("enumVal")
            if _number(raw) == value:
                converted = _coerce_profile_value(raw, field)
                if isinstance(converted, (int, float)):
                    return converted
    return value


async def _set_colour_mode(context: DeviceContext, value: int) -> None:
    """Select the 100z colour context before writing RGB/CCT or a preset."""

    if not context.has_service("colourMode"):
        return
    profile = context.profile or {}
    # The public Profile can omit this characteristic, but the 100z cloud
    # contract still uses colourMode.mode.
    await context.async_send_service(
        "colourMode",
        {"mode": _mode_value(profile, value)},
    )


def _light_projection_mode(context: DeviceContext) -> str | None:
    """Return the active colour projection, never guessing stale cache state."""

    colour_mode = _colour_mode_value(context)
    if colour_mode == _COLOUR_MODE_RGB:
        return "rgb"
    if colour_mode == _COLOUR_MODE_COLOR_TEMP:
        return "color_temp"
    if colour_mode == _COLOUR_MODE_PRESET:
        return None

    # A reported colour mode is authoritative.  Do not infer a colour mode
    # from the cached RGB/CCT values when Huawei adds another mode.
    if colour_mode is not None:
        return None

    light_mode = _light_mode_value(context)
    if light_mode is None:
        return None
    if light_mode == 0:
        return "rgb"
    return None


async def _turn_on(context: DeviceContext, data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 1})
    if data.get("brightness") is not None:
        brightness_field = _field(
            context.profile or {},
            "brightness",
            "brightness",
        )
        if brightness_field is None:
            raise ValueError("100z brightness field is missing from the Profile")
        await context.async_send_service(
            "brightness",
            {
                "brightness": _ha_brightness_to_device(
                    data["brightness"],
                    brightness_field,
                )
            },
        )
    if data.get("rgb_color") is not None:
        red, green, blue = data["rgb_color"]
        await _set_colour_mode(context, _COLOUR_MODE_RGB)
        await context.async_send_service(
            "colour",
            {"red": red, "green": green, "blue": blue},
        )
    if data.get("color_temp_kelvin") is not None:
        await _set_colour_mode(context, _COLOUR_MODE_COLOR_TEMP)
        await context.async_send_service(
            "cct",
            {"colorTemperature": data["color_temp_kelvin"]},
        )


async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 0})


async def _select_light_mode(
    context: DeviceContext,
    data: Mapping[str, Any],
) -> None:
    profile = context.profile or {}
    field = _field(profile, "lightMode", "mode") or {}
    for option in (field or {}).get("enumList", ()):
        if not isinstance(option, Mapping):
            continue
        label = str(option.get("descCh") or option.get("enumVal"))
        if label == data["option"]:
            await _set_colour_mode(context, _COLOUR_MODE_PRESET)
            await context.async_send_service(
                "lightMode",
                {
                    "mode": _coerce_profile_value(
                        option.get("enumVal"),
                        field,
                    )
                },
            )
            return
    raise ValueError(f"unknown light mode: {data['option']}")


class Product100zAdapter:
    """Keep all 100z entity and command choices in this file."""

    prod_id = "100z"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None or not all(
            context.has_service(sid)
            for sid in ("switch", "brightness", "colour", "cct")
        ):
            return ()

        brightness = _field(profile, "brightness", "brightness") or {}
        cct = _field(profile, "cct", "colorTemperature") or {}
        supported_modes = {"rgb", "color_temp"}
        light_actions = {
            "turn_on": _turn_on,
            "turn_off": _turn_off,
        }

        def light_state(device: DeviceContext) -> Mapping[str, Any]:
            projection_mode = _light_projection_mode(device)
            return {
                "is_on": _bool(device.value("switch", "on")),
                "brightness": _device_brightness_to_ha(
                    device.value("brightness", "brightness"),
                    brightness,
                ),
                "rgb_color": (
                    tuple(
                        _number(device.value("colour", channel))
                        for channel in ("red", "green", "blue")
                    )
                    if projection_mode == "rgb"
                    else None
                ),
                "color_temp_kelvin": (
                    _number(device.value("cct", "colorTemperature"))
                    if projection_mode == "color_temp"
                    else None
                ),
                "color_mode": projection_mode,
            }

        entities = [
            EntitySpec(
                platform="light",
                key="light",
                name=None,
                state=light_state,
                metadata={
                    "supported_color_modes": supported_modes,
                    "min_color_temp_kelvin": cct.get("min"),
                    "max_color_temp_kelvin": cct.get("max"),
                },
                actions=light_actions,
            )
        ]

        if context.has_service("lightMode"):
            mode_field = _field(profile, "lightMode", "mode") or {}
            options = tuple(
                (
                    str(option.get("descCh") or option.get("enumVal")),
                    option.get("enumVal"),
                )
                for option in mode_field.get("enumList", ())
                if isinstance(option, Mapping)
            )

            def mode_state(device: DeviceContext) -> Mapping[str, Any]:
                colour_mode = _colour_mode_value(device)
                if colour_mode in {
                    _COLOUR_MODE_RGB,
                    _COLOUR_MODE_COLOR_TEMP,
                }:
                    return {"current_option": None}
                value = _light_mode_value(device)
                if colour_mode is not None and colour_mode != _COLOUR_MODE_PRESET:
                    return {"current_option": None}
                if value in (None, 0):
                    return {"current_option": None}
                current_option = next(
                    (label for label, raw in options if str(raw) == str(value)),
                    str(value) if value is not None else None,
                )
                return {"current_option": current_option}

            entities.append(
                EntitySpec(
                    platform="select",
                    key="light_mode",
                    name="灯光模式",
                    state=mode_state,
                    metadata={"options": tuple(label for label, _ in options)},
                    actions={"select_option": _select_light_mode},
                )
            )
        return tuple(entities)


ADAPTER = Product100zAdapter()
