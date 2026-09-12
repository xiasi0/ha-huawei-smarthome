"""User-contributed protocol for Huawei product 2I7C.

Device: 欧普照明 蓝牙Mesh双色温灯带驱动 / OPPLE SMART Strip Light Drive
(Bluetooth, CCT) (deviceModel ``OP-DY220/200-24CV/2-WB``, deviceTypeId
``226``, protocolType ``Mesh``).
Profile: https://smarthome-drcn.dbankcdn.com/device/guide/2I7C/2I7C.json

Exposed entity:

* ``light`` "设备名" <- ``switch.on``
                    / ``brightness.brightness``    (int 1..100 %)
                    / ``cct.colorTemperature``     (int 2700..5700 K)

``supported_color_modes`` is ``{"color_temp"}`` only: HA lets that single mode
cover on/off, brightness and colour temperature, and HA rejects combining
``brightness`` with any other mode.  This device has no RGB service, so no
colour mode is advertised.  If the Profile does not describe both a brightness
range and a colour temperature range, no light entity is created at all.

Deliberately *not* exposed:

* ``toggleSwitch.toggle`` ("开关翻转") — the vendor H5 bundle never calls
  ``setDeviceInfo`` on it (the only outgoing calls are ``switch.on``,
  ``brightness.brightness`` and ``cct.colorTemperature``), and its write
  semantics are a stateless toggle that conflicts with HA's state-driven
  ``light.toggle``.  Following the "no entity over a guessed mapping" rule it
  stays out; users toggle via the light entity itself.
* ``commonFaultDetection`` / ``netInfo`` / ``update`` — read-only diagnostics
  and OTA, consistent with the other strip-light adapters.

Brightness scaling: the device reports a percentage in 1..100, while HA uses
0..255 and treats 0 as "off".  The mapping therefore targets 1..255 so the
lowest device step stays a visible level instead of collapsing into HA's "off"
value; the round trip is stable for every device value from 1 to 100.

Note that the Profile stores ``min``/``max`` as strings ("2700"), so they are
converted to numbers before being handed to HA.

This adapter was derived from the Profile and vendor H5 bundle and is not yet
verified on a physical device.
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
        raise ValueError("2I7C Profile range is incomplete")
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
        raise ValueError("2I7C brightness range is missing from the Profile")
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
            raise ValueError("2I7C brightness field is missing from the Profile")
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
            raise ValueError("2I7C colour temperature field is missing")
        await context.async_send_service(
            _CCT_SID,
            {_CCT_FIELD: _clamp_to_profile(data["color_temp_kelvin"], field)},
        )


async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(_SWITCH_SID, {_SWITCH_FIELD: 0})


class Product2i7cAdapter:
    """Keep all 2I7C entity and command choices in this file."""

    prod_id = "2I7C"

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

        return (
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
        )


ADAPTER = Product2i7cAdapter()
