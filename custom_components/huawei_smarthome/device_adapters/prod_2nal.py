"""User-contributed protocol for Huawei product 2NAL.

Device: eachone 一起玩智能风扇灯 / Smart Fan Light
(deviceModel ``HJ-HM-FSD-001``, deviceTypeId from vendor 中山鸿钧科技,
protocolType ``WiFi``).
Profile: https://smarthome-drcn.dbankcdn.com/device/guide/2NAL/2NAL.json

Exposed entities (every command payload below is copied from a real
``setDevInfo`` dispatch site in the vendor H5 bundle ``static/js/main.js``):

* ``light`` "灯"      <- ``switch.on``
                      / ``brightness.brightness``      (int 1..100 %)
                      / ``cct.colorTemperature``       (int 3000..5700 K)
* ``fan`` "风扇"      <- ``switchFan.on`` (power)
                      / ``fan.gear`` (1..6 档, mapped to HA 1..100 %)
* ``select`` "灯光模式"  <- ``lightMode.mode``   (会客/观影/用餐/浪漫/睡眠/阅读)
* ``select`` "风扇模式"  <- ``fanMode.mode``     (空/睡眠风/自然风/循环风)
* ``select`` "风量档位"  <- ``fan.gear``         (空/1档..6档, Profile enumList)
* ``switch`` "风扇反转"  <- ``verticalswing.verticalswing`` (H5 label 风扇反转)
* ``number`` "渐变时间"  <- ``progressSwitchHF.progressSwitch`` (0..59 s)

Payloads (from the H5 ``switchRes``/``selectMode``/``playListRes``/
``submitFadeTime`` methods):

* ``{switch:{on:N}}`` / ``{switchFan:{on:N}}``
* ``{brightness:{brightness:N}}`` / ``{cct:{colorTemperature:N}}``
* ``{fan:{gear:N}}`` / ``{fanMode:{mode:N}}`` / ``{lightMode:{mode:N}}``
* ``{verticalswing:{verticalswing:N}}``
* ``{progressSwitchHF:{progressSwitch:N}}``

Fan gear to percentage mapping: the device has 6 discrete speeds, mapped to
``round(gear * 100 / 6)`` so every gear round-trips; ``set_percentage`` snaps
back to the nearest gear (1..6).  The fan's ``percentage_step`` metadata is
declared as 16, the closest integer below 100/6, because the integration's
fan platform stores the step as an int.

The fan gear is also exposed as a dedicated "风量档位" select so the discrete
gears can be picked by name, not only through the percentage slider.  The
labels (空/1档..6档) come from the Profile enumList; value 0 ("空") is the
placeholder reported by the device and stays in the options.  The H5
FanSpeedCard.selectMode dispatches exactly ``{fan:{gear:e}}`` — no switchFan
power toggle is included — so the select sends the same payload.  The H5 row
is disabled while the fan is off; that is a UI shortcut gate, not a protocol
limit, and persistent entities do not replicate it.

``fanMode.mode`` value 0 ("空") is a placeholder and stays in the select
options, otherwise the entity cannot render the state when the device reports
it.  Unknown enum values map to ``None`` (unknown) instead of a guessed label.

Deliberately *not* exposed:

* ``onOffBeep`` — the settings row label exists in the language pack
  ("Fan Beep") but no ``setDevInfo`` dispatch drives it in this bundle.
* ``countdownht`` — multi-field countdown flow (device selection + timeing +
  state) without a single direct dispatch site.
* ``progressTurnOff`` / ``progressTurnOn`` — sleep-aid / wake-up windows
  (enable/triggerTime/range) with no direct dispatch evidence here.
* ``binding`` / ``unbinding`` / ``remotecontrolid`` — remote-control pairing
  flow driven by the app's remote management page.
* ``timer`` — array-structured timers managed through a dedicated page.
* ``netInfo`` / ``update`` — diagnostics and OTA, consistent with the other
  adapters.

Brightness scaling: the device reports a percentage in 1..100, while HA uses
0..255 and treats 0 as "off".  The mapping therefore targets 1..255 so the
lowest device step stays a visible level instead of collapsing into HA's "off"
value; the round trip is stable for every device value from 1 to 100.

Note that the Profile stores ``min``/``max`` as strings ("3000"), so they are
converted to numbers before being handed to HA.

This adapter was derived from the Profile and vendor H5 bundle and is not yet
verified on a physical device.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

# Light.
_SWITCH_SID = "switch"
_SWITCH_FIELD = "on"
_BRIGHTNESS_SID = "brightness"
_BRIGHTNESS_FIELD = "brightness"
_CCT_SID = "cct"
_CCT_FIELD = "colorTemperature"
_LIGHT_MODE_SID = "lightMode"
_LIGHT_MODE_FIELD = "mode"
_LIGHT_MODE_OPTIONS = (
    (0, "会客模式"),
    (2, "观影模式"),
    (3, "用餐模式"),
    (5, "浪漫模式"),
    (7, "睡眠模式"),
    (8, "阅读模式"),
)

# Fan.
_FAN_SWITCH_SID = "switchFan"
_FAN_SWITCH_FIELD = "on"
_FAN_SID = "fan"
_FAN_GEAR_FIELD = "gear"
_FAN_GEAR_MAX = 6
# Labels from the Profile enumList; 0 ("空") is the placeholder and stays.
_FAN_GEAR_OPTIONS = (
    (0, "空"),
    (1, "1档"),
    (2, "2档"),
    (3, "3档"),
    (4, "4档"),
    (5, "5档"),
    (6, "6档"),
)
_FAN_MODE_SID = "fanMode"
_FAN_MODE_FIELD = "mode"
# Value 0 ("空") is a placeholder reported by the device and stays listed.
_FAN_MODE_OPTIONS = (
    (0, "空"),
    (1, "睡眠风"),
    (2, "自然风"),
    (100, "循环风"),
)
_FAN_REVERSAL_SID = "verticalswing"
_FAN_REVERSAL_FIELD = "verticalswing"

# Shared gradient time (seconds).
_FADE_SID = "progressSwitchHF"
_FADE_FIELD = "progressSwitch"

# HA's brightness scale.  The floor is 1, not 0, because HA renders 0 as "off".
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
        if value.strip().casefold() in {"1", "true", "on"}:
            return True
        if value.strip().casefold() in {"0", "false", "off"}:
            return False
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _profile_range(
    field: Mapping[str, Any] | None,
) -> tuple[float, float] | None:
    """Return the declared range, tolerating Profile values stored as strings."""

    if field is None:
        return None
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


def _clamp_to_profile(value: Any, field: Mapping[str, Any]) -> int | float:
    """Clamp a value into the Profile range, snapping it to the declared step."""

    number = _number(value)
    value_range = _profile_range(field)
    if number is None or value_range is None:
        raise ValueError("2NAL Profile range is incomplete")
    minimum, maximum = value_range
    number = min(max(float(number), minimum), maximum)
    step = _profile_step(field)
    if step is not None:
        number = minimum + round((number - minimum) / step) * step
        # Snapping can overshoot the upper bound; clamp again.
        number = min(max(number, minimum), maximum)
    if str(field.get("characteristicType") or "").casefold() in {
        "int",
        "integer",
        "enum",
    }:
        return int(round(number))
    return int(number) if float(number).is_integer() else number


def _device_brightness_to_ha(
    value: Any,
    field: Mapping[str, Any],
) -> int | None:
    """Convert the product's percentage brightness to HA's 1..255 scale."""

    number = _number(value)
    value_range = _profile_range(field)
    if number is None or value_range is None:
        return None
    minimum, maximum = value_range
    number = min(max(float(number), minimum), maximum)
    span = _HA_BRIGHTNESS_MAX - _HA_BRIGHTNESS_MIN
    return round(
        _HA_BRIGHTNESS_MIN + (number - minimum) * span / (maximum - minimum)
    )


def _ha_brightness_to_device(
    value: Any,
    field: Mapping[str, Any],
) -> int | float:
    """Convert HA's 1..255 brightness to the product Profile percentage."""

    number = _number(value)
    value_range = _profile_range(field)
    if number is None or value_range is None:
        raise ValueError("2NAL brightness range is missing from the Profile")
    minimum, maximum = value_range
    number = min(max(float(number), _HA_BRIGHTNESS_MIN), _HA_BRIGHTNESS_MAX)
    span = _HA_BRIGHTNESS_MAX - _HA_BRIGHTNESS_MIN
    return _clamp_to_profile(
        minimum + (number - _HA_BRIGHTNESS_MIN) * (maximum - minimum) / span,
        field,
    )


def _gear_to_percentage(gear: Any) -> int | None:
    number = _number(gear)
    if number is None or number < 1:
        # gear 0 is the "空" placeholder, not a speed.
        return None
    number = min(number, _FAN_GEAR_MAX)
    return round(number * 100 / _FAN_GEAR_MAX)


def _percentage_to_gear(value: Any) -> int:
    number = _number(value)
    if number is None:
        raise ValueError("2NAL fan percentage must be a number")
    gear = round(float(number) * _FAN_GEAR_MAX / 100)
    return max(1, min(_FAN_GEAR_MAX, gear))


def _enum_label(
    value: Any,
    options: tuple[tuple[int, str], ...],
) -> str | None:
    number = _number(value)
    if number is None:
        return None
    for enum_value, label in options:
        if number == enum_value:
            return label
    return None


def _enum_value(
    option: Any,
    options: tuple[tuple[int, str], ...],
) -> int:
    for enum_value, label in options:
        if option == label:
            return enum_value
    raise ValueError(f"unknown option: {option!r}")


async def _light_turn_on(context: DeviceContext, data: Mapping[str, Any]) -> None:
    await context.async_send_service(_SWITCH_SID, {_SWITCH_FIELD: 1})
    if data.get("brightness") is not None:
        field = _field(context.profile or {}, _BRIGHTNESS_SID, _BRIGHTNESS_FIELD)
        if field is None:
            raise ValueError("2NAL brightness field is missing from the Profile")
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
        field = _field(context.profile or {}, _CCT_SID, _CCT_FIELD)
        if field is None:
            raise ValueError("2NAL colour temperature field is missing")
        await context.async_send_service(
            _CCT_SID,
            {_CCT_FIELD: _clamp_to_profile(data["color_temp_kelvin"], field)},
        )


async def _light_turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(_SWITCH_SID, {_SWITCH_FIELD: 0})


async def _light_mode_select_option(
    context: DeviceContext,
    data: Mapping[str, Any],
) -> None:
    value = _enum_value(data.get("option"), _LIGHT_MODE_OPTIONS)
    await context.async_send_service(_LIGHT_MODE_SID, {_LIGHT_MODE_FIELD: value})


async def _fan_turn_on(context: DeviceContext, data: Mapping[str, Any]) -> None:
    await context.async_send_service(_FAN_SWITCH_SID, {_FAN_SWITCH_FIELD: 1})
    percentage = data.get("percentage")
    if percentage is not None and _number(percentage) not in (None, 0):
        await context.async_send_service(
            _FAN_SID,
            {_FAN_GEAR_FIELD: _percentage_to_gear(percentage)},
        )


async def _fan_turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(_FAN_SWITCH_SID, {_FAN_SWITCH_FIELD: 0})


async def _fan_set_percentage(context: DeviceContext, data: Mapping[str, Any]) -> None:
    percentage = data.get("percentage")
    if percentage is None or _number(percentage) in (None, 0):
        # HA semantics: 0 % means off.
        await context.async_send_service(_FAN_SWITCH_SID, {_FAN_SWITCH_FIELD: 0})
        return
    await context.async_send_service(_FAN_SWITCH_SID, {_FAN_SWITCH_FIELD: 1})
    await context.async_send_service(
        _FAN_SID,
        {_FAN_GEAR_FIELD: _percentage_to_gear(percentage)},
    )


async def _fan_gear_select_option(
    context: DeviceContext,
    data: Mapping[str, Any],
) -> None:
    # H5 FanSpeedCard.selectMode sends {fan:{gear:e}} only — no power toggle.
    value = _enum_value(data.get("option"), _FAN_GEAR_OPTIONS)
    await context.async_send_service(_FAN_SID, {_FAN_GEAR_FIELD: value})


async def _fan_mode_select_option(
    context: DeviceContext,
    data: Mapping[str, Any],
) -> None:
    value = _enum_value(data.get("option"), _FAN_MODE_OPTIONS)
    await context.async_send_service(_FAN_MODE_SID, {_FAN_MODE_FIELD: value})


async def _reversal_turn_on(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(
        _FAN_REVERSAL_SID,
        {_FAN_REVERSAL_FIELD: 1},
    )


async def _reversal_turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(
        _FAN_REVERSAL_SID,
        {_FAN_REVERSAL_FIELD: 0},
    )


async def _fade_set_value(context: DeviceContext, data: Mapping[str, Any]) -> None:
    field = _field(context.profile or {}, _FADE_SID, _FADE_FIELD)
    if field is None:
        raise ValueError("2NAL gradient time field is missing from the Profile")
    await context.async_send_service(
        _FADE_SID,
        {_FADE_FIELD: _clamp_to_profile(data.get("value"), field)},
    )


class Product2nalAdapter:
    """Keep all 2NAL entity and command choices in this file."""

    prod_id = "2NAL"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None or not context.has_service(_SWITCH_SID):
            return ()

        specs: list[EntitySpec] = []

        # --- light -------------------------------------------------------
        brightness = _field(profile, _BRIGHTNESS_SID, _BRIGHTNESS_FIELD)
        cct = _field(profile, _CCT_SID, _CCT_FIELD)
        brightness_range = _profile_range(brightness)
        cct_range = _profile_range(cct)
        # Project stance: without a complete Profile the light is not projected
        # at all, rather than risking a wrong state mapping or a command the
        # device cannot accept.
        if brightness_range is not None and cct_range is not None:
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

            specs.append(
                EntitySpec(
                    platform="light",
                    key="light",
                    # Combo device: a plain device-name fallback would collide
                    # with the fan entity, so the light is named 灯 explicitly.
                    name="灯",
                    state=light_state,
                    metadata={
                        "supported_color_modes": {_COLOR_MODE_CCT},
                        "min_color_temp_kelvin": int(cct_range[0]),
                        "max_color_temp_kelvin": int(cct_range[1]),
                    },
                    actions={
                        "turn_on": _light_turn_on,
                        "turn_off": _light_turn_off,
                    },
                )
            )

        # --- fan ----------------------------------------------------------
        if context.has_service(_FAN_SWITCH_SID) and _field(
            profile, _FAN_SID, _FAN_GEAR_FIELD
        ) is not None:
            def fan_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "is_on": _bool(
                        device.value(_FAN_SWITCH_SID, _FAN_SWITCH_FIELD)
                    ),
                    "percentage": _gear_to_percentage(
                        device.value(_FAN_SID, _FAN_GEAR_FIELD)
                    ),
                    "preset_mode": None,
                    "oscillating": None,
                }

            specs.append(
                EntitySpec(
                    platform="fan",
                    key="fan",
                    name="风扇",
                    state=fan_state,
                    metadata={
                        "supports_percentage": True,
                        # The integration stores the step as int; 16 is the
                        # closest integer below 100/6 gears.  set_percentage
                        # snaps to the nearest gear regardless.
                        "percentage_step": 16,
                    },
                    actions={
                        "turn_on": _fan_turn_on,
                        "turn_off": _fan_turn_off,
                        "set_percentage": _fan_set_percentage,
                    },
                )
            )

        # --- fan gear select ----------------------------------------------
        if context.has_service(_FAN_SID) and _field(
            profile, _FAN_SID, _FAN_GEAR_FIELD
        ) is not None:
            def fan_gear_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "current_option": _enum_label(
                        device.value(_FAN_SID, _FAN_GEAR_FIELD),
                        _FAN_GEAR_OPTIONS,
                    )
                }

            specs.append(
                EntitySpec(
                    platform="select",
                    key="fan_gear",
                    name="风量档位",
                    state=fan_gear_state,
                    metadata={
                        "options": [label for _, label in _FAN_GEAR_OPTIONS]
                    },
                    actions={"select_option": _fan_gear_select_option},
                )
            )

        # --- light scene select -------------------------------------------
        if context.has_service(_LIGHT_MODE_SID) and _field(
            profile, _LIGHT_MODE_SID, _LIGHT_MODE_FIELD
        ) is not None:
            def light_mode_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "current_option": _enum_label(
                        device.value(_LIGHT_MODE_SID, _LIGHT_MODE_FIELD),
                        _LIGHT_MODE_OPTIONS,
                    )
                }

            specs.append(
                EntitySpec(
                    platform="select",
                    key="light_mode",
                    name="灯光模式",
                    state=light_mode_state,
                    metadata={
                        "options": [label for _, label in _LIGHT_MODE_OPTIONS]
                    },
                    actions={"select_option": _light_mode_select_option},
                )
            )

        # --- fan wind mode select -----------------------------------------
        if context.has_service(_FAN_MODE_SID) and _field(
            profile, _FAN_MODE_SID, _FAN_MODE_FIELD
        ) is not None:
            def fan_mode_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "current_option": _enum_label(
                        device.value(_FAN_MODE_SID, _FAN_MODE_FIELD),
                        _FAN_MODE_OPTIONS,
                    )
                }

            specs.append(
                EntitySpec(
                    platform="select",
                    key="fan_mode",
                    name="风扇模式",
                    state=fan_mode_state,
                    metadata={
                        "options": [label for _, label in _FAN_MODE_OPTIONS]
                    },
                    actions={"select_option": _fan_mode_select_option},
                )
            )

        # --- fan reversal switch ------------------------------------------
        if context.has_service(_FAN_REVERSAL_SID) and _field(
            profile, _FAN_REVERSAL_SID, _FAN_REVERSAL_FIELD
        ) is not None:
            def reversal_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "is_on": _bool(
                        device.value(_FAN_REVERSAL_SID, _FAN_REVERSAL_FIELD)
                    )
                }

            specs.append(
                EntitySpec(
                    platform="switch",
                    key="fan_reversal",
                    name="风扇反转",
                    state=reversal_state,
                    actions={
                        "turn_on": _reversal_turn_on,
                        "turn_off": _reversal_turn_off,
                    },
                )
            )

        # --- gradient time number -----------------------------------------
        fade_field = _field(profile, _FADE_SID, _FADE_FIELD)
        fade_range = _profile_range(fade_field)
        if context.has_service(_FADE_SID) and fade_range is not None:
            def fade_state(device: DeviceContext) -> Mapping[str, Any]:
                return {"native_value": _number(
                    device.value(_FADE_SID, _FADE_FIELD)
                )}

            specs.append(
                EntitySpec(
                    platform="number",
                    key="gradient_time",
                    name="渐变时间",
                    state=fade_state,
                    metadata={
                        "min": fade_range[0],
                        "max": fade_range[1],
                        "step": _profile_step(fade_field) or 1,
                        # H5 gradientProps formats the value as 秒 (seconds).
                        "unit": "s",
                    },
                    actions={"set_value": _fade_set_value},
                )
            )

        return tuple(specs)


ADAPTER = Product2nalAdapter()
