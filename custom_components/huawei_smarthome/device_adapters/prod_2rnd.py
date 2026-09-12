"""User-contributed protocol for Huawei product 2RND.

Device: 西顿照明 T5 无线灯带照明驱动 / CDN Wireless Strip Light
(deviceModel ``SWBH-QY-240W-2``, deviceTypeId ``226``).
Profile: https://smarthome-drcn.dbankcdn.com/device/guide/2RND/2RND.json

Exposed entity:

* ``light`` "设备名" <- ``switch.on``
                    / ``brightness.brightness``    (int 1..100 %)
                    / ``cct.colorTemperature``     (int 2700..6500 K)

``supported_color_modes`` is ``{"color_temp"}`` only: HA lets that single mode
cover on/off, brightness and colour temperature, and HA rejects combining
``brightness`` with any other mode.  This device has no RGB service, so no
colour mode is advertised.  If the Profile does not describe both a brightness
range and a colour temperature range, no light entity is created at all.

Additional control entities (all backed by rendered cards in the vendor H5
bundle ``data/index.data.js``):

* ``switch`` "指示灯"        <- ``indicator.on``              (bool RW)
* ``select`` "断电记忆"      <- ``commonMemorySwitch.status`` (enum RW 0/1/2)
* ``number`` "渐变时长"      <- ``fadeTimeSetting.fadeTimeMs`` (int 0..5 s)
* ``binary_sensor`` "故障"   <- ``commonFaultDetection.status`` (bool R)
* ``sensor`` "故障码"        <- ``commonFaultDetection.code``   (enum R)

Deliberately *not* exposed:

* ``lightCurveSetting`` — the Profile states this is only available in the
  vendor's 易维 app ("此功能不在智慧生活APP开放"), and the H5 bundle has no
  dedicated rendered card for it (it only appears inside a shared enum map).
* ``relBrightness`` — ``enable`` is a capability flag ("是否支持") and
  ``rotaStatus``/``relBrightness``/``fadetimeMs`` belong to an accessory-knob
  calibration flow; no rendered UI card drives them in this bundle.
* ``update`` — OTA diagnostics, consistent with the other adapters.

Brightness scaling: the device reports a percentage in 1..100, while HA uses
0..255 and treats 0 as "off".  The mapping therefore targets 1..255 so the
lowest device step stays a visible level instead of collapsing into HA's "off"
value; the round trip is stable for every device value from 1 to 100.

Note that the Profile stores ``min``/``max`` as strings ("2700"), so they are
converted to numbers before being handed to HA.

This adapter was derived from the Profile and is not yet verified on a
physical device.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_SWITCH_SID = "switch"
_SWITCH_FIELD = "on"
_BRIGHTNESS_SID = "brightness"
_BRIGHTNESS_FIELD = "brightness"
_CCT_SID = "cct"
_CCT_FIELD = "colorTemperature"

# Indicator light: GeneralBoolIconCard1 in the vendor H5 (开=1 / 关=0).
_INDICATOR_SID = "indicator"
_INDICATOR_FIELD = "on"

# Power-failure memory: GeneralEnumDroplistCard1 droplist in the vendor H5.
_MEMORY_SID = "commonMemorySwitch"
_MEMORY_FIELD = "status"
_MEMORY_OPTIONS = (
    (0, "来电关灯"),
    (1, "来电开灯"),
    (2, "来电保持断电前的状态"),
)

# Fade time: GeneralIntCard3 in the vendor H5, unit "s", int 0..5.
_FADE_SID = "fadeTimeSetting"
_FADE_FIELD = "fadeTimeMs"

# Fault detection: read-only; GeneralWarn banner consumes the same fields.
_FAULT_SID = "commonFaultDetection"
_FAULT_STATUS_FIELD = "status"
_FAULT_CODE_FIELD = "code"
_FAULT_CODE_LABELS = {0: "正常", 1: "短路", 2: "开路"}

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
        raise ValueError("2RND Profile range is incomplete")
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
        raise ValueError("2RND brightness range is missing from the Profile")
    minimum, maximum = value_range
    number = min(max(float(number), _HA_BRIGHTNESS_MIN), _HA_BRIGHTNESS_MAX)
    span = _HA_BRIGHTNESS_MAX - _HA_BRIGHTNESS_MIN
    return _clamp_to_profile(
        minimum + (number - _HA_BRIGHTNESS_MIN) * (maximum - minimum) / span,
        field,
    )


async def _turn_on(context: DeviceContext, data: Mapping[str, Any]) -> None:
    await context.async_send_service(_SWITCH_SID, {_SWITCH_FIELD: 1})
    if data.get("brightness") is not None:
        field = _field(context.profile or {}, _BRIGHTNESS_SID, _BRIGHTNESS_FIELD)
        if field is None:
            raise ValueError("2RND brightness field is missing from the Profile")
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
            raise ValueError("2RND colour temperature field is missing")
        await context.async_send_service(
            _CCT_SID,
            {_CCT_FIELD: _clamp_to_profile(data["color_temp_kelvin"], field)},
        )


async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(_SWITCH_SID, {_SWITCH_FIELD: 0})


async def _indicator_turn_on(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(_INDICATOR_SID, {_INDICATOR_FIELD: 1})


async def _indicator_turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(_INDICATOR_SID, {_INDICATOR_FIELD: 0})


def _memory_label(value: Any) -> str | None:
    number = _number(value)
    if number is None:
        return None
    for enum_value, label in _MEMORY_OPTIONS:
        if number == enum_value:
            return label
    return None


def _memory_select(context: DeviceContext, data: Mapping[str, Any]) -> None:
    option = data.get("option")
    for enum_value, label in _MEMORY_OPTIONS:
        if option == label:
            return enum_value
    raise ValueError(f"unknown option: {option!r}")


async def _memory_select_option(
    context: DeviceContext,
    data: Mapping[str, Any],
) -> None:
    value = _memory_select(context, data)
    await context.async_send_service(_MEMORY_SID, {_MEMORY_FIELD: value})


async def _fade_set_value(context: DeviceContext, data: Mapping[str, Any]) -> None:
    field = _field(context.profile or {}, _FADE_SID, _FADE_FIELD)
    if field is None:
        raise ValueError("2RND fade time field is missing from the Profile")
    await context.async_send_service(
        _FADE_SID,
        {_FADE_FIELD: _clamp_to_profile(data.get("value"), field)},
    )


class Product2rndAdapter:
    """Keep all 2RND entity and command choices in this file."""

    prod_id = "2RND"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None or not context.has_service(_SWITCH_SID):
            return ()

        brightness = _field(profile, _BRIGHTNESS_SID, _BRIGHTNESS_FIELD)
        cct = _field(profile, _CCT_SID, _CCT_FIELD)
        brightness_range = _profile_range(brightness)
        cct_range = _profile_range(cct)
        # Project stance: without a complete Profile the light is not projected
        # at all, rather than risking a wrong state mapping or a command the
        # device cannot accept.  A missing range also makes the percentage
        # scale unusable, so both ranges are required.
        if brightness_range is None or cct_range is None:
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

        specs: list[EntitySpec] = [
            EntitySpec(
                platform="light",
                key="light",
                name=None,
                state=light_state,
                # HA's single "color_temp" mode covers on/off, brightness and
                # colour temperature; HA rejects "brightness" next to it.
                metadata={
                    "supported_color_modes": {_COLOR_MODE_CCT},
                    "min_color_temp_kelvin": int(cct_range[0]),
                    "max_color_temp_kelvin": int(cct_range[1]),
                },
                actions={
                    "turn_on": _turn_on,
                    "turn_off": _turn_off,
                },
            ),
        ]

        # 指示灯开关: the H5 label is "指示灯开关" but the switch platform
        # already implies the 开关 semantics, so the entity is named 指示灯.
        if context.has_service(_INDICATOR_SID) and _field(
            profile, _INDICATOR_SID, _INDICATOR_FIELD
        ) is not None:
            specs.append(
                EntitySpec(
                    platform="switch",
                    key="indicator",
                    name="指示灯",
                    state=lambda device: {
                        "is_on": _bool(
                            device.value(_INDICATOR_SID, _INDICATOR_FIELD)
                        )
                    },
                    actions={
                        "turn_on": _indicator_turn_on,
                        "turn_off": _indicator_turn_off,
                    },
                )
            )

        # 断电记忆 (power-failure memory).
        if context.has_service(_MEMORY_SID) and _field(
            profile, _MEMORY_SID, _MEMORY_FIELD
        ) is not None:
            def memory_state(device: DeviceContext) -> Mapping[str, Any]:
                return {"current_option": _memory_label(
                    device.value(_MEMORY_SID, _MEMORY_FIELD)
                )}

            specs.append(
                EntitySpec(
                    platform="select",
                    key="memory_switch",
                    name="断电记忆",
                    state=memory_state,
                    metadata={
                        "options": [label for _, label in _MEMORY_OPTIONS]
                    },
                    actions={"select_option": _memory_select_option},
                )
            )

        # 渐变时长 (fade time in seconds).
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
                    key="fade_time",
                    name="渐变时长",
                    state=fade_state,
                    metadata={
                        "min": fade_range[0],
                        "max": fade_range[1],
                        "step": _profile_step(fade_field) or 1,
                        # Profile `unit` is empty; the H5 card and the Profile
                        # desc ("单位s") both state seconds.
                        "unit": "s",
                    },
                    actions={"set_value": _fade_set_value},
                )
            )

        # 故障检测: read-only status + error code.
        fault_status = _field(profile, _FAULT_SID, _FAULT_STATUS_FIELD)
        if context.has_service(_FAULT_SID) and fault_status is not None:
            def fault_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "is_on": _bool(
                        device.value(_FAULT_SID, _FAULT_STATUS_FIELD)
                    )
                }

            specs.append(
                EntitySpec(
                    platform="binary_sensor",
                    key="fault",
                    name="故障",
                    state=fault_state,
                    metadata={"device_class": "problem"},
                )
            )

        fault_code = _field(profile, _FAULT_SID, _FAULT_CODE_FIELD)
        if context.has_service(_FAULT_SID) and fault_code is not None:
            def fault_code_state(device: DeviceContext) -> Mapping[str, Any]:
                # Unknown enum values stay unknown rather than guessing a label.
                number = _number(device.value(_FAULT_SID, _FAULT_CODE_FIELD))
                return {
                    "native_value": _FAULT_CODE_LABELS.get(number)
                    if number is not None
                    else None
                }

            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="fault_code",
                    name="故障码",
                    state=fault_code_state,
                )
            )

        return tuple(specs)


ADAPTER = Product2rndAdapter()
