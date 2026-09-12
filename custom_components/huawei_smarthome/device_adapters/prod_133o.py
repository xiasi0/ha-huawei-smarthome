"""User-contributed protocol for Huawei product 133O."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_SWITCH_SID = "switch"
_SWITCH_FIELD = "on"
_BRIGHTNESS_SID = "brightness"
_BRIGHTNESS_FIELD = "brightness"
_COLOUR_MODE_SID = "colourMode"
_COLOUR_MODE_FIELD = "mode"
_CCT_SID = "cct"
_CCT_FIELD = "colorTemperature"

_HA_BRIGHTNESS_MIN = 1
_HA_BRIGHTNESS_MAX = 255
_COLOR_MODE_CCT = "color_temp"


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


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        value = value.strip().casefold()
        if value in {"1", "true", "on"}:
            return True
        if value in {"0", "false", "off"}:
            return False
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _profile_range(
    field: Mapping[str, Any] | None,
) -> tuple[float, float] | None:
    if field is None:
        return None
    minimum = _number(field.get("min"))
    maximum = _number(field.get("max"))
    if minimum is None or maximum is None or maximum <= minimum:
        return None
    return float(minimum), float(maximum)


def _profile_step(field: Mapping[str, Any]) -> float | None:
    step = _number(field.get("step"))
    return float(step) if step is not None and step > 0 else None


def _clamp_to_profile(value: Any, field: Mapping[str, Any]) -> int | float:
    number = _number(value)
    value_range = _profile_range(field)
    if number is None or value_range is None:
        raise ValueError("133O Profile range is incomplete")
    minimum, maximum = value_range
    number = min(max(float(number), minimum), maximum)
    step = _profile_step(field)
    if step is not None:
        number = minimum + round((number - minimum) / step) * step
        number = min(max(number, minimum), maximum)
    if str(field.get("characteristicType") or "").casefold() in {
        "int",
        "integer",
        "enum",
    }:
        return int(round(number))
    return int(number) if number.is_integer() else number


def _device_brightness_to_ha(
    value: Any,
    field: Mapping[str, Any],
) -> int | None:
    number = _number(value)
    value_range = _profile_range(field)
    if number is None or value_range is None:
        return None
    minimum, maximum = value_range
    number = min(max(float(number), minimum), maximum)
    return round(
        _HA_BRIGHTNESS_MIN
        + (number - minimum)
        * (_HA_BRIGHTNESS_MAX - _HA_BRIGHTNESS_MIN)
        / (maximum - minimum)
    )


def _ha_brightness_to_device(
    value: Any,
    field: Mapping[str, Any],
) -> int | float:
    number = _number(value)
    value_range = _profile_range(field)
    if number is None or value_range is None:
        raise ValueError("133O brightness range is missing from the Profile")
    minimum, maximum = value_range
    number = min(max(float(number), _HA_BRIGHTNESS_MIN), _HA_BRIGHTNESS_MAX)
    device_value = minimum + (
        (number - _HA_BRIGHTNESS_MIN)
        * (maximum - minimum)
        / (_HA_BRIGHTNESS_MAX - _HA_BRIGHTNESS_MIN)
    )
    return _clamp_to_profile(device_value, field)


def _colour_mode_value(profile: Mapping[str, Any]) -> int:
    field = _field(profile, _COLOUR_MODE_SID, _COLOUR_MODE_FIELD)
    if field is not None:
        for option in field.get("enumList", ()):
            if isinstance(option, Mapping) and _number(option.get("enumVal")) == 1:
                return int(_number(option.get("enumVal")) or 1)
    return 1


async def _turn_on(context: DeviceContext, data: Mapping[str, Any]) -> None:
    await context.async_send_service(_SWITCH_SID, {_SWITCH_FIELD: 1})
    profile = context.profile or {}
    if data.get("brightness") is not None:
        field = _field(profile, _BRIGHTNESS_SID, _BRIGHTNESS_FIELD)
        if field is None:
            raise ValueError("133O brightness field is missing from the Profile")
        await context.async_send_service(
            _BRIGHTNESS_SID,
            {
                _BRIGHTNESS_FIELD: _ha_brightness_to_device(
                    data["brightness"],
                    field,
                )
            },
        )
    if data.get("color_temp_kelvin") is not None:
        field = _field(profile, _CCT_SID, _CCT_FIELD)
        if field is None:
            raise ValueError("133O colour temperature field is missing")
        if context.has_service(_COLOUR_MODE_SID):
            await context.async_send_service(
                _COLOUR_MODE_SID,
                {_COLOUR_MODE_FIELD: _colour_mode_value(profile)},
            )
        await context.async_send_service(
            _CCT_SID,
            {_CCT_FIELD: _clamp_to_profile(data["color_temp_kelvin"], field)},
        )


async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(_SWITCH_SID, {_SWITCH_FIELD: 0})


class Product133oAdapter:
    """Project the 133O switch, brightness and colour-temperature services."""

    prod_id = "133O"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()
        brightness = _field(profile, _BRIGHTNESS_SID, _BRIGHTNESS_FIELD)
        cct = _field(profile, _CCT_SID, _CCT_FIELD)
        cct_range = _profile_range(cct)
        if (
            not context.has_service(_SWITCH_SID)
            or not context.has_service(_BRIGHTNESS_SID)
            or not context.has_service(_CCT_SID)
            or brightness is None
            or _profile_range(brightness) is None
            or cct_range is None
        ):
            return ()

        def light_state(device: DeviceContext) -> Mapping[str, Any]:
            return {
                "is_on": _bool(device.value(_SWITCH_SID, _SWITCH_FIELD)),
                "brightness": _device_brightness_to_ha(
                    device.value(_BRIGHTNESS_SID, _BRIGHTNESS_FIELD),
                    brightness,
                ),
                "color_temp_kelvin": _number(
                    device.value(_CCT_SID, _CCT_FIELD)
                ),
                "color_mode": _COLOR_MODE_CCT,
            }

        return (
            EntitySpec(
                platform="light",
                key="light",
                name=None,
                state=light_state,
                metadata={
                    "supported_color_modes": {_COLOR_MODE_CCT},
                    "min_color_temp_kelvin": int(cct_range[0]),
                    "max_color_temp_kelvin": int(cct_range[1]),
                },
                actions={"turn_on": _turn_on, "turn_off": _turn_off},
            ),
        )


ADAPTER = Product133oAdapter()
