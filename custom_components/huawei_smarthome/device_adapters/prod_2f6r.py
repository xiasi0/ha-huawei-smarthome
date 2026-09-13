"""User-contributed protocol for Huawei product 2F6R.

Device: 达伦智能台灯3 (deviceModel ``DL-3HW``, manufacturer 达伦, WiFi).
Profile: https://smarthome-drcn.dbankcdn.com/device/guide/2F6R/2F6R.json

Exposed entities:

* ``light``   主灯         <- ``switch.on`` (power) / ``brightness.brightness``
                              (int range taken from the Profile, 1..100 here)
* ``select``  "灯光模式"    <- ``lightMode.mode``   (读写 / 阅屏 / 手动)
* ``switch``  "指示灯"      <- ``indicator.on``
* ``select``  "渐亮渐暗时长" <- ``fadeTime.time``   (关闭 / 30s / 60s / 90s)
* ``sensor``  "灯状态"      <- ``lightStatus.status`` (closed / closing / opened)

Every enum label and value range is resolved from the Profile at runtime, so a
product revision that changes them degrades to a missing entity rather than a
wrong mapping.

Deliberately not exposed:

* ``timer`` / ``delay`` — the Profile declares array/object schedulers
  (``timer.timer``, ``delay.delay``) whose payload shape is a list of parameter
  objects.  Composing one requires knowing the exact object schema the cloud
  expects, and nothing in the Profile documents it; sending a guessed shape
  risks creating a malformed schedule on a device that runs unattended (this
  lamp has timer and countdown features the user may already rely on).
* ``tomatoClk1``..``tomatoClk4`` — four pomodoro timers, each ~10 writable
  fields (``enable`` / ``mode`` / ``name`` / ``num`` / ``totalTime`` ...) that
  only make sense together as one object.  Home Assistant has no natural way to
  present "create/modify a pomodoro session" without inventing a custom
  service, and a partial mapping would expose fields whose interaction is
  unverified.  Left out rather than half-mapped.
* ``nightWakeup`` / ``progressTurnOff`` — ``nightWakeup`` carries ``start`` and
  ``end`` as bare minute integers with the Profile documenting only "单位：分钟"
  and no epoch, so whether they are minutes-since-midnight or offsets cannot be
  determined from the Profile alone; guessing would write a wake-up window at
  the wrong time of day.  ``progressTurnOff.range`` (brightness-fade duration)
  is a single number with no unit in the Profile.
* ``record`` — a usage log (``date`` + ``time``); it is a local history entry
  rather than device state, and the Profile does not say whether writing it
  records a session or clears one.

These omissions follow the project rule of preferring a missing entity over a
wrong mapping; they can be added once the payload shapes are confirmed against
the vendor UI or a real dispatch trace.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_PROD_ID = "2F6R"

_SWITCH_SID = "switch"
_SWITCH_FIELD = "on"
_BRIGHTNESS_SID = "brightness"
_BRIGHTNESS_FIELD = "brightness"
_LIGHT_MODE_SID = "lightMode"
_LIGHT_MODE_FIELD = "mode"
_INDICATOR_SID = "indicator"
_INDICATOR_FIELD = "on"
_FADE_TIME_SID = "fadeTime"
_FADE_TIME_FIELD = "time"
_LIGHT_STATUS_SID = "lightStatus"
_LIGHT_STATUS_FIELD = "status"

_HA_BRIGHTNESS_MIN = 1
_HA_BRIGHTNESS_MAX = 255


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
        result = float(value)
    except (TypeError, ValueError):
        return None
    return int(result) if result.is_integer() else result


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


def _clamp_to_profile(value: Any, field: Mapping[str, Any]) -> int | float:
    """Clamp and snap a value onto the range the Profile declares."""

    number = _number(value)
    value_range = _profile_range(field)
    if number is None or value_range is None:
        return number if number is not None else value
    minimum, maximum = value_range
    number = min(max(float(number), minimum), maximum)
    step = _profile_step(field)
    if step is not None:
        number = minimum + round((number - minimum) / step) * step
    data_type = str(field.get("characteristicType") or "").casefold()
    if data_type in {"int", "integer", "enum"}:
        return int(round(number))
    return number


def _device_brightness_to_ha(
    value: Any,
    field: Mapping[str, Any],
) -> int | None:
    """Convert the lamp's percentage brightness to HA's 1..255 scale."""

    number = _number(value)
    value_range = _profile_range(field)
    if number is None or value_range is None:
        return None
    minimum, maximum = value_range
    number = min(max(float(number), minimum), maximum)
    span = _HA_BRIGHTNESS_MAX - _HA_BRIGHTNESS_MIN
    return round(_HA_BRIGHTNESS_MIN + (number - minimum) * span / (maximum - minimum))


def _ha_brightness_to_device(
    value: Any,
    field: Mapping[str, Any],
) -> int | float:
    """Convert HA's 1..255 brightness to the lamp's Profile percentage."""

    number = _number(value)
    value_range = _profile_range(field)
    if number is None or value_range is None:
        raise ValueError("2F6R brightness range is missing from the Profile")
    minimum, maximum = value_range
    number = min(max(float(number), _HA_BRIGHTNESS_MIN), _HA_BRIGHTNESS_MAX)
    span = _HA_BRIGHTNESS_MAX - _HA_BRIGHTNESS_MIN
    return _clamp_to_profile(
        minimum + (number - _HA_BRIGHTNESS_MIN) * (maximum - minimum) / span,
        field,
    )


def _enum_options(field: Mapping[str, Any] | None) -> tuple[tuple[Any, str], ...]:
    """Return the Profile's ``(raw value, label)`` pairs in declared order."""

    if field is None:
        return ()
    options: list[tuple[Any, str]] = []
    for option in field.get("enumList", ()):
        if not isinstance(option, Mapping):
            continue
        label = option.get("descCh") or option.get("descEn")
        raw = option.get("enumVal")
        if label is None or raw is None:
            continue
        options.append((raw, str(label)))
    return tuple(options)


def _enum_label(value: Any, options: tuple[tuple[Any, str], ...]) -> str | None:
    number = _number(value)
    if number is None:
        return None
    for raw, label in options:
        if _number(raw) == number:
            return label
    return None


def _enum_value(option: Any, options: tuple[tuple[Any, str], ...]) -> Any:
    for raw, label in options:
        if option == label:
            return raw
    raise ValueError(f"unknown option: {option!r}")


async def _light_turn_on(context: DeviceContext, data: Mapping[str, Any]) -> None:
    """Power the lamp on, applying brightness when one was requested."""

    await context.async_send_service(_SWITCH_SID, {_SWITCH_FIELD: 1})
    brightness = data.get("brightness")
    if brightness is None:
        return
    field = _field(context.profile or {}, _BRIGHTNESS_SID, _BRIGHTNESS_FIELD)
    if field is None:
        raise ValueError("2F6R brightness field is missing from the Profile")
    await context.async_send_service(
        _BRIGHTNESS_SID,
        {_BRIGHTNESS_FIELD: _ha_brightness_to_device(brightness, field)},
    )


async def _light_turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(_SWITCH_SID, {_SWITCH_FIELD: 0})


async def _light_mode_select(context: DeviceContext, data: Mapping[str, Any]) -> None:
    field = _field(context.profile or {}, _LIGHT_MODE_SID, _LIGHT_MODE_FIELD)
    options = _enum_options(field)
    if not options:
        raise ValueError("2F6R lightMode options are missing from the Profile")
    await context.async_send_service(
        _LIGHT_MODE_SID,
        {_LIGHT_MODE_FIELD: _enum_value(data.get("option"), options)},
    )


async def _indicator_turn_on(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(_INDICATOR_SID, {_INDICATOR_FIELD: 1})


async def _indicator_turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(_INDICATOR_SID, {_INDICATOR_FIELD: 0})


async def _fade_time_select(context: DeviceContext, data: Mapping[str, Any]) -> None:
    field = _field(context.profile or {}, _FADE_TIME_SID, _FADE_TIME_FIELD)
    options = _enum_options(field)
    if not options:
        raise ValueError("2F6R fadeTime options are missing from the Profile")
    await context.async_send_service(
        _FADE_TIME_SID,
        {_FADE_TIME_FIELD: _enum_value(data.get("option"), options)},
    )


class Product2F6RAdapter:
    """达伦智能台灯3 (DL-3HW) 适配器。"""

    prod_id = _PROD_ID

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()
        entities: list[EntitySpec] = []

        # --- main light ----------------------------------------------------
        brightness_field = _field(profile, _BRIGHTNESS_SID, _BRIGHTNESS_FIELD)
        if context.has_service(_SWITCH_SID) and brightness_field is not None:
            def light_state(device: DeviceContext) -> Mapping[str, Any]:
                field = _field(device.profile or {}, _BRIGHTNESS_SID, _BRIGHTNESS_FIELD)
                is_on = _bool(device.value(_SWITCH_SID, _SWITCH_FIELD))
                if field is None:
                    return {"is_on": is_on, "brightness": None}
                return {
                    "is_on": is_on,
                    "brightness": _device_brightness_to_ha(
                        device.value(_BRIGHTNESS_SID, _BRIGHTNESS_FIELD), field
                    ),
                }

            entities.append(
                EntitySpec(
                    platform="light",
                    key="light",
                    name=None,
                    state=light_state,
                    metadata={"supported_color_modes": {"brightness"}},
                    actions={
                        "turn_on": _light_turn_on,
                        "turn_off": _light_turn_off,
                    },
                )
            )

        # --- light mode ----------------------------------------------------
        mode_field = _field(profile, _LIGHT_MODE_SID, _LIGHT_MODE_FIELD)
        mode_options = _enum_options(mode_field)
        if context.has_service(_LIGHT_MODE_SID) and mode_options:
            def light_mode_state(device: DeviceContext) -> Mapping[str, Any]:
                field = _field(device.profile or {}, _LIGHT_MODE_SID, _LIGHT_MODE_FIELD)
                return {
                    "current_option": _enum_label(
                        device.value(_LIGHT_MODE_SID, _LIGHT_MODE_FIELD),
                        _enum_options(field),
                    )
                }

            entities.append(
                EntitySpec(
                    platform="select",
                    key="light_mode",
                    name="灯光模式",
                    state=light_mode_state,
                    metadata={"options": tuple(label for _, label in mode_options)},
                    actions={"select_option": _light_mode_select},
                )
            )

        # --- indicator light -----------------------------------------------
        if context.has_service(_INDICATOR_SID):
            def indicator_state(device: DeviceContext) -> Mapping[str, Any]:
                return {"is_on": _bool(device.value(_INDICATOR_SID, _INDICATOR_FIELD))}

            entities.append(
                EntitySpec(
                    platform="switch",
                    key="indicator",
                    name="指示灯",
                    state=indicator_state,
                    metadata={"entity_category": "config"},
                    actions={
                        "turn_on": _indicator_turn_on,
                        "turn_off": _indicator_turn_off,
                    },
                )
            )

        # --- fade time -----------------------------------------------------
        fade_field = _field(profile, _FADE_TIME_SID, _FADE_TIME_FIELD)
        fade_options = _enum_options(fade_field)
        if context.has_service(_FADE_TIME_SID) and fade_options:
            def fade_state(device: DeviceContext) -> Mapping[str, Any]:
                field = _field(device.profile or {}, _FADE_TIME_SID, _FADE_TIME_FIELD)
                return {
                    "current_option": _enum_label(
                        device.value(_FADE_TIME_SID, _FADE_TIME_FIELD),
                        _enum_options(field),
                    )
                }

            entities.append(
                EntitySpec(
                    platform="select",
                    key="fade_time",
                    name="渐亮渐暗时长",
                    state=fade_state,
                    metadata={
                        "options": tuple(label for _, label in fade_options),
                        "entity_category": "config",
                    },
                    actions={"select_option": _fade_time_select},
                )
            )

        # --- status sensor -------------------------------------------------
        status_field = _field(profile, _LIGHT_STATUS_SID, _LIGHT_STATUS_FIELD)
        status_options = _enum_options(status_field)
        if context.has_service(_LIGHT_STATUS_SID):
            def status_state(device: DeviceContext) -> Mapping[str, Any]:
                field = _field(
                    device.profile or {}, _LIGHT_STATUS_SID, _LIGHT_STATUS_FIELD
                )
                return {
                    "native_value": _enum_label(
                        device.value(_LIGHT_STATUS_SID, _LIGHT_STATUS_FIELD),
                        _enum_options(field),
                    )
                }

            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="light_status",
                    name="灯状态",
                    state=status_state,
                    metadata={"entity_category": "diagnostic"},
                )
            )

        return tuple(entities)


ADAPTER = Product2F6RAdapter()
