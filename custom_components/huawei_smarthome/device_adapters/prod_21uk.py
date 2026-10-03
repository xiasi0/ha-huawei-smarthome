"""User-contributed protocol for Huawei product 21UK.

Device: 达伦智能台灯3 Pro (deviceModel ``DL-35W``, manufacturer 达伦, WiFi).
Profile: https://smarthome-drcn.dbankcdn.com/device/guide/21UK/21UK.json

Exposed entities:

* ``light``   主灯          <- ``switch.on`` (power) / ``brightness.brightness``
                               (Profile int range 1..100)
* ``select``  "色温"         <- ``ColorTempStep.ColorTempStep``
                               (0=3500K / 1=4000K / 2=4500K)
* ``switch``  "伴眠模式"      <- ``WithSleepMode.WithSleepMode``
* ``switch``  "自动调光"      <- ``AutoAMode.AutoAMode``
* ``switch``  "课堂模式"      <- ``classroom.on``
* ``switch``  "WiFi指示灯"    <- ``WIFIledSwitch.on``   (config)
* ``sensor``  "信号强度 RSSI" <- ``netInfo.RSSI``       (diagnostic)

Every enum label and value range is resolved from the Profile at runtime, so a
product revision that changes them degrades to a missing entity rather than a
wrong mapping.

Deliberately not exposed:

* ``timer`` / ``delay`` — the Profile declares array/object schedulers
  (``timer.timer``, ``delay.delay``) whose payload shape is a list of parameter
  objects.  Composing one requires knowing the exact object schema the cloud
  expects and nothing in the Profile documents it; sending a guessed shape
  risks creating a malformed schedule on a device that runs unattended (this
  lamp has timer and countdown features the user may already rely on).
* ``update`` — OTA control; triggering a firmware upgrade from an entity
  switch has no safe HA representation.
* ``netInfo`` other fields — ``SSID`` / ``BSSID`` / ``IP`` leak network
  details into the entity registry and ``intensity`` is a derived bucket of
  ``RSSI``; only the raw ``RSSI`` reading is exposed, matching the other
  adapters.

These omissions follow the project rule of preferring a missing entity over a
wrong mapping; they can be added once the payload shapes are confirmed against
the vendor UI or a real dispatch trace.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_PROD_ID = "21UK"

_SWITCH_SID = "switch"
_SWITCH_FIELD = "on"
_BRIGHTNESS_SID = "brightness"
_BRIGHTNESS_FIELD = "brightness"
_COLOR_TEMP_SID = "ColorTempStep"
_COLOR_TEMP_FIELD = "ColorTempStep"
_SLEEP_MODE_SID = "WithSleepMode"
_SLEEP_MODE_FIELD = "WithSleepMode"
_AUTO_DIMMING_SID = "AutoAMode"
_AUTO_DIMMING_FIELD = "AutoAMode"
_CLASSROOM_SID = "classroom"
_CLASSROOM_FIELD = "on"
_WIFI_LED_SID = "WIFIledSwitch"
_WIFI_LED_FIELD = "on"
_NET_INFO_SID = "netInfo"
_RSSI_FIELD = "RSSI"

_HA_BRIGHTNESS_MIN = 1
_HA_BRIGHTNESS_MAX = 255

# The lamp only dims and steps colour temperature; brightness is the only
# continuous channel, so it is the only colour mode HA can honestly report.
_COLOR_MODE_BRIGHTNESS = "brightness"


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
    number = _number(value)
    value_range = _profile_range(field)
    if number is None or value_range is None:
        raise ValueError("21UK brightness range is missing from the Profile")
    minimum, maximum = value_range
    number = min(max(float(number), _HA_BRIGHTNESS_MIN), _HA_BRIGHTNESS_MAX)
    span = _HA_BRIGHTNESS_MAX - _HA_BRIGHTNESS_MIN
    return _clamp_to_profile(
        minimum + (number - _HA_BRIGHTNESS_MIN) * (maximum - minimum) / span,
        field,
    )


def _enum_options(field: Mapping[str, Any] | None) -> tuple[tuple[Any, str], ...]:
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
    await context.async_send_service(_SWITCH_SID, {_SWITCH_FIELD: 1})
    brightness = data.get("brightness")
    if brightness is None:
        return
    field = _field(context.profile or {}, _BRIGHTNESS_SID, _BRIGHTNESS_FIELD)
    if field is None:
        raise ValueError("21UK brightness field is missing from the Profile")
    await context.async_send_service(
        _BRIGHTNESS_SID,
        {_BRIGHTNESS_FIELD: _ha_brightness_to_device(brightness, field)},
    )


async def _light_turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(_SWITCH_SID, {_SWITCH_FIELD: 0})


def _bool_switch(
    sid: str,
    field: str,
    *,
    key: str,
    name: str,
    entity_category: str | None = None,
) -> EntitySpec:
    async def turn_on(context: DeviceContext, _data: Mapping[str, Any]) -> None:
        await context.async_send_service(sid, {field: 1})

    async def turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
        await context.async_send_service(sid, {field: 0})

    def state(device: DeviceContext) -> Mapping[str, Any]:
        return {"is_on": _bool(device.value(sid, field))}

    metadata: dict[str, Any] = {}
    if entity_category is not None:
        metadata["entity_category"] = entity_category
    return EntitySpec(
        platform="switch",
        key=key,
        name=name,
        state=state,
        metadata=metadata,
        actions={"turn_on": turn_on, "turn_off": turn_off},
    )


def _enum_select(
    profile: Mapping[str, Any],
    sid: str,
    field: str,
    *,
    key: str,
    name: str,
) -> EntitySpec:
    async def select_option(context: DeviceContext, data: Mapping[str, Any]) -> None:
        profile_field = _field(context.profile or {}, sid, field)
        options = _enum_options(profile_field)
        if not options:
            raise ValueError(f"21UK {sid}.{field} options are missing from the Profile")
        await context.async_send_service(
            sid,
            {field: _enum_value(data.get("option"), options)},
        )

    def state(device: DeviceContext) -> Mapping[str, Any]:
        profile_field = _field(device.profile or {}, sid, field)
        return {
            "current_option": _enum_label(
                device.value(sid, field),
                _enum_options(profile_field),
            )
        }

    metadata: dict[str, Any] = {
        "options": tuple(
            label for _, label in _enum_options(_field(profile, sid, field))
        ),
    }
    return EntitySpec(
        platform="select",
        key=key,
        name=name,
        state=state,
        metadata=metadata,
        actions={"select_option": select_option},
    )


class Product21UKAdapter:
    """达伦智能台灯3 Pro (DL-35W) 适配器。"""

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
                    return {
                        "is_on": is_on,
                        "brightness": None,
                        "color_mode": _COLOR_MODE_BRIGHTNESS,
                    }
                # The lamp reports brightness 0 while it is off, which means
                # "no brightness" rather than "minimum brightness"; mapping it
                # onto the Profile's 1..100 range would describe a lit lamp at
                # its dimmest.  Off therefore reports no brightness.
                raw = device.value(_BRIGHTNESS_SID, _BRIGHTNESS_FIELD)
                brightness = (
                    None
                    if not is_on and _number(raw) == 0
                    else _device_brightness_to_ha(raw, field)
                )
                return {
                    "is_on": is_on,
                    "brightness": brightness,
                    "color_mode": _COLOR_MODE_BRIGHTNESS,
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

        # --- colour temperature step --------------------------------------
        color_temp_options = _enum_options(
            _field(profile, _COLOR_TEMP_SID, _COLOR_TEMP_FIELD)
        )
        if context.has_service(_COLOR_TEMP_SID) and color_temp_options:
            entities.append(
                _enum_select(
                    profile,
                    _COLOR_TEMP_SID,
                    _COLOR_TEMP_FIELD,
                    key="color_temp",
                    name="色温",
                )
            )

        # --- boolean feature switches --------------------------------------
        for sid, field, key, name, category in (
            (_SLEEP_MODE_SID, _SLEEP_MODE_FIELD, "sleep_mode", "伴眠模式", None),
            (_AUTO_DIMMING_SID, _AUTO_DIMMING_FIELD, "auto_dimming", "自动调光", None),
            (_CLASSROOM_SID, _CLASSROOM_FIELD, "classroom_mode", "课堂模式", None),
            (_WIFI_LED_SID, _WIFI_LED_FIELD, "wifi_led", "WiFi指示灯", "config"),
        ):
            if context.has_service(sid):
                entities.append(
                    _bool_switch(sid, field, key=key, name=name, entity_category=category)
                )

        # --- RSSI diagnostic -----------------------------------------------
        if context.has_service(_NET_INFO_SID):
            rssi_field = _field(profile, _NET_INFO_SID, _RSSI_FIELD)
            if rssi_field is not None:
                def rssi_state(device: DeviceContext) -> Mapping[str, Any]:
                    return {
                        "native_value": _number(device.value(_NET_INFO_SID, _RSSI_FIELD))
                    }

                entities.append(
                    EntitySpec(
                        platform="sensor",
                        key="rssi",
                        name="信号强度 RSSI",
                        state=rssi_state,
                        metadata={
                            "entity_category": "diagnostic",
                            "device_class": "signal_strength",
                            "state_class": "measurement",
                            "unit_of_measurement": "dBm",
                        },
                    )
                )

        return tuple(entities)


ADAPTER = Product21UKAdapter()
