"""User-contributed protocol for Huawei product 21JC."""

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
_LIGHT_MODE_SID = "lightMode"
_LIGHT_MODE_FIELD = "mode"

_HA_BRIGHTNESS_MIN = 1
_HA_BRIGHTNESS_MAX = 255
_COLOR_MODE_CCT = "color_temp"
_MODE_ENTITY_NAME = "灯光模式"
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
        raise ValueError("21JC Profile range is incomplete")
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
        raise ValueError("21JC brightness range is missing from the Profile")
    minimum, maximum = value_range
    number = min(max(float(number), _HA_BRIGHTNESS_MIN), _HA_BRIGHTNESS_MAX)
    device_value = minimum + (
        (number - _HA_BRIGHTNESS_MIN)
        * (maximum - minimum)
        / (_HA_BRIGHTNESS_MAX - _HA_BRIGHTNESS_MIN)
    )
    return _clamp_to_profile(device_value, field)


def _enum_key(value: Any) -> str | None:
    number = _number(value)
    if number is not None:
        return str(int(number))
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _mode_labels(field: Mapping[str, Any]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for option in field.get("enumList", ()):
        if not isinstance(option, Mapping):
            continue
        key = _enum_key(option.get("enumVal"))
        if key is None:
            continue
        label = str(option.get("descCh") or option.get("descEn") or key)
        labels.setdefault(key, label)
    return labels


def _enum_payload(key: str) -> int | str:
    number = _number(key)
    return int(number) if number is not None else key


async def _turn_on(context: DeviceContext, data: Mapping[str, Any]) -> None:
    await context.async_send_service(_SWITCH_SID, {_SWITCH_FIELD: 1})
    profile = context.profile or {}
    if data.get("brightness") is not None:
        field = _field(profile, _BRIGHTNESS_SID, _BRIGHTNESS_FIELD)
        if field is None:
            raise ValueError("21JC brightness field is missing from the Profile")
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
            raise ValueError("21JC colour temperature field is missing")
        await context.async_send_service(
            _CCT_SID,
            {_CCT_FIELD: _clamp_to_profile(data["color_temp_kelvin"], field)},
        )


async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(_SWITCH_SID, {_SWITCH_FIELD: 0})


class Product21jcAdapter:
    """Project the 21JC light and its preset light modes."""

    prod_id = "21JC"

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

        entities: list[EntitySpec] = [
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
            )
        ]

        mode_field = _field(profile, _LIGHT_MODE_SID, _LIGHT_MODE_FIELD)
        if context.has_service(_LIGHT_MODE_SID) and mode_field is not None:
            labels = _mode_labels(mode_field)
            if labels:
                def mode_state(device: DeviceContext) -> Mapping[str, Any]:
                    colour_mode = _enum_key(
                        device.value(_COLOUR_MODE_SID, _COLOUR_MODE_FIELD)
                    )
                    if colour_mode != str(_COLOUR_MODE_PRESET):
                        return {"current_option": None}
                    value = _enum_key(
                        device.value(_LIGHT_MODE_SID, _LIGHT_MODE_FIELD)
                    )
                    return {"current_option": labels.get(value)}

                async def select_mode(
                    device: DeviceContext,
                    data: Mapping[str, Any],
                ) -> None:
                    label_to_value = {
                        label: key for key, label in labels.items()
                    }
                    raw = label_to_value.get(data.get("option"))
                    if raw is None:
                        raise ValueError(
                            f"21JC unknown light mode: {data.get('option')!r}"
                        )
                    await device.async_send_service(
                        _LIGHT_MODE_SID,
                        {_LIGHT_MODE_FIELD: _enum_payload(raw)},
                    )

                entities.append(
                    EntitySpec(
                        platform="select",
                        key="light_mode",
                        name=_MODE_ENTITY_NAME,
                        state=mode_state,
                        metadata={"options": tuple(labels.values())},
                        actions={"select_option": select_mode},
                    )
                )
        return tuple(entities)


ADAPTER = Product21jcAdapter()
