"""User-contributed protocol for Huawei product 2OWF.

Device: eachone 一起玩 智能吸顶灯 / Eachone Ceiling Lamp
(deviceModel ``HF-HM-XDD-004``, deviceTypeId ``112``).
Profile: https://smarthome-drcn.dbankcdn.com/device/guide/2OWF/2OWF.json

Exposed entities:

* ``light``  "设备名"    <- ``switch.on``
                        / ``brightness.brightness``  (int 1..100 %)
                        / ``cct.colorTemperature``   (int 3000..5000 K)
* ``select`` "灯光模式"  <- ``lightMode.mode``       (enum, 会客模式 ... 空)

``supported_color_modes`` is ``{"color_temp"}`` only, as in 2RND: HA lets that
single mode cover on/off, brightness and colour temperature, and HA rejects
combining ``brightness`` with any other mode.  This device has no RGB service,
so no colour mode is advertised.  If the Profile does not describe the switch,
the brightness range and the colour temperature range, no light entity is
created at all.

Brightness scaling: the device reports a percentage in 1..100 while HA uses
0..255 and renders 0 as "off", so the mapping targets 1..255 and keeps the
lowest device step a visible level.  Profile ``min``/``max``/``step`` values
are normalised to numbers first because the Profile stores some of them as
strings.

The light mode is a ``select`` entity rather than a light ``effect`` because
``light.py`` does not implement ``effect_list``.  Selecting a mode sends
``lightMode`` and nothing else.  The vendor H5 handler
(``js/index.js`` -> ``LampModeTile1.onClick``) calls
``setDeviceInfo({lightMode: {mode: N}})`` and, next to it,
``updateUI({colourMode: {mode: 4}})`` -- ``updateUI`` only touches the H5's own
render state (elsewhere in the bundle it is guarded by ``if (!window.hilink)``
and always paired with a ``setDeviceInfo`` that performs the real send), and
this Profile has no ``colourMode`` service at all.  The preset's brightness and
colour temperature therefore arrive back through the normal state sync instead
of being composed here.  Selecting a mode does not switch the lamp on either:
the H5 handler sends no ``switch`` command, so neither does this adapter.

This adapter was derived from the Profile and the vendor H5 bundle, and is not
yet verified on a physical device.
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
_MODE_SID = "lightMode"
_MODE_FIELD = "mode"

# HA's brightness scale.  The floor is 1, not 0, because HA renders 0 as "off".
_HA_BRIGHTNESS_MIN = 1
_HA_BRIGHTNESS_MAX = 255

_COLOR_MODE_CCT = "color_temp"
_MODE_ENTITY_NAME = "灯光模式"


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


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _enum_key(value: Any) -> str | None:
    """Normalise an enum value so 0, "0" and 0.0 share one key."""

    if value is None or isinstance(value, bool):
        return None
    number = _number(value)
    if number is not None:
        return str(int(number))
    text = _text(value)
    return text


def _enum_payload(key: str) -> int | str:
    """Turn an enum key back into the value the device expects.

    The vendor H5 sends ``Number(...)`` for this field, and enum characteristics
    carry no ``min``/``max``, so they must not go through the range clamp.
    """

    number = _number(key)
    return int(number) if number is not None else key


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
        raise ValueError("2OWF Profile range is incomplete")
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
        raise ValueError("2OWF brightness range is missing from the Profile")
    minimum, maximum = value_range
    number = min(max(float(number), _HA_BRIGHTNESS_MIN), _HA_BRIGHTNESS_MAX)
    span = _HA_BRIGHTNESS_MAX - _HA_BRIGHTNESS_MIN
    return _clamp_to_profile(
        minimum + (number - _HA_BRIGHTNESS_MIN) * (maximum - minimum) / span,
        field,
    )


def _mode_labels(field: Mapping[str, Any]) -> dict[str, str]:
    """Map each ``lightMode.mode`` enum value to a unique option label.

    The Profile's ``lightMode`` enum skips 4 and ends with 100 ("空"), which is
    the vendor's "no preset active" value.  100 is kept as a selectable option
    so that a device reporting it still matches a declared option instead of
    leaving the entity without a valid ``current_option``.
    """

    labels: dict[str, str] = {}
    repeated: set[str] = set()
    for item in field.get("enumList") or ():
        if not isinstance(item, Mapping):
            continue
        key = _enum_key(item.get("enumVal"))
        if key is None or key in labels:
            continue
        label = _text(item.get("descCh")) or _text(item.get("descEn")) or key
        if label in labels.values():
            repeated.add(label)
        labels[key] = label
    # Disambiguate duplicate vendor labels so every option stays distinct.
    return {
        key: f"{label} ({key})" if label in repeated else label
        for key, label in labels.items()
    }


async def _turn_on(context: DeviceContext, data: Mapping[str, Any]) -> None:
    await context.async_send_service(_SWITCH_SID, {_SWITCH_FIELD: 1})
    if data.get("brightness") is not None:
        field = _field(context.profile or {}, _BRIGHTNESS_SID, _BRIGHTNESS_FIELD)
        if field is None:
            raise ValueError("2OWF brightness field is missing from the Profile")
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
            raise ValueError("2OWF colour temperature field is missing")
        await context.async_send_service(
            _CCT_SID,
            {_CCT_FIELD: _clamp_to_profile(data["color_temp_kelvin"], field)},
        )


async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(_SWITCH_SID, {_SWITCH_FIELD: 0})


class Product2owfAdapter:
    """Keep all 2OWF entity and command choices in this file."""

    prod_id = "2OWF"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        entities: list[EntitySpec] = []
        light = self._light_entity(context, profile)
        if light is not None:
            entities.append(light)
        mode = self._mode_entity(context, profile)
        if mode is not None:
            entities.append(mode)
        return tuple(entities)

    def _light_entity(
        self,
        context: DeviceContext,
        profile: Mapping[str, Any],
    ) -> EntitySpec | None:
        brightness = _field(profile, _BRIGHTNESS_SID, _BRIGHTNESS_FIELD)
        cct = _field(profile, _CCT_SID, _CCT_FIELD)
        brightness_range = _profile_range(brightness)
        cct_range = _profile_range(cct)
        # Project stance: without a complete Profile the light is not projected
        # at all, rather than risking a wrong state mapping or a command the
        # device cannot accept.  A missing range also makes the percentage
        # scale unusable, so both ranges are required.
        if (
            brightness is None
            or brightness_range is None
            or cct_range is None
            or not context.has_service(_SWITCH_SID)
            or not context.has_service(_BRIGHTNESS_SID)
            or not context.has_service(_CCT_SID)
        ):
            return None

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

        return EntitySpec(
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
        )

    def _mode_entity(
        self,
        context: DeviceContext,
        profile: Mapping[str, Any],
    ) -> EntitySpec | None:
        field = _field(profile, _MODE_SID, _MODE_FIELD)
        if field is None or not context.has_service(_MODE_SID):
            return None
        labels = _mode_labels(field)
        if not labels:
            return None

        options = tuple(labels.values())
        label_to_value = {label: key for key, label in labels.items()}

        def mode_state(device: DeviceContext) -> Mapping[str, Any]:
            key = _enum_key(device.value(_MODE_SID, _MODE_FIELD))
            # An unknown enum value stays unknown instead of guessing a label.
            return {"current_option": labels.get(key) if key is not None else None}

        async def select_mode(
            device: DeviceContext,
            data: Mapping[str, Any],
        ) -> None:
            option = data.get("option")
            raw = label_to_value.get(option)
            if raw is None:
                raise ValueError(f"2OWF unknown light mode: {option!r}")
            await device.async_send_service(
                _MODE_SID,
                {_MODE_FIELD: _enum_payload(raw)},
            )

        return EntitySpec(
            platform="select",
            key="light_mode",
            name=_MODE_ENTITY_NAME,
            state=mode_state,
            metadata={"options": options},
            actions={"select_option": select_mode},
        )


ADAPTER = Product2owfAdapter()
