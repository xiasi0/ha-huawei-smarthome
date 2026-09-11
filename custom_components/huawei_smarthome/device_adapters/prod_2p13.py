"""User-contributed protocol for Huawei product 2P13.

Device: 达伦智能台灯5i(双控版) / Dalen Smart Table Lamp 5i (Bluetooth)
(deviceModel ``DL-01W Pro``, protocolType ``BLE+Mobile Network``).
Profile: https://smarthome-drcn.dbankcdn.com/device/guide/2P13/2P13.json

Exposed entities (command payloads below are copied from real
``setDevInfo`` dispatch sites in the vendor H5 bundle — webpack build,
``static/js/main.js`` + async ``chunk_<id>.js``):

* ``light``  "主灯" <- ``switch.on`` (power) / ``brightness.brightness``
* ``light``  "夜灯" <- ``auxSwitch.on`` (power) / ``auxBrightness.brightness``
* ``select`` "灯光模式"     <- ``lightMode.mode`` (读写100/阅屏101/无极调光102)
* ``switch`` "主灯开关"     <- ``mainSwitch.on``
* ``select`` "延时关灯"     <- ``delayTurnoff.delayTime`` (关/10s/20s/30s)
* ``switch`` "指示灯"       <- ``indicator.on``
* ``switch`` "夜间模式"     <- ``nightWakeup.enable``
* ``number`` "夜间模式开始时间" <- ``nightWakeup.start`` (0..1440 min of day)
* ``number`` "夜间模式结束时间" <- ``nightWakeup.end``   (0..1440 min of day)
* ``sensor`` "折叠角度"     <- ``foldAngles.foldAngles`` (R, 0..360 °)

Evidence notes (vendor H5):

* The bundle serves two products (``isDoubleControl: "2P13" === proId``).
  Its built-in report-validation schema confirms the Profile enum labels for
  ``lightMode``: ``{range:[100,101,102], mean:["读写","阅屏","无极调光"]}``.
* ``switch.on`` is the user-facing device power toggle: the Profile
  ``quickmenu.switchInfo.path`` is ``switch/on``, and the home page
  ``controlAppliance`` toggles ``{switch:{on:1-netStatus}}`` /
  ``{switch:{on:0}}`` (the latter during a delay-off countdown).
* ``mainSwitch.on`` is the main-light active flag per the quickmenu content
  rules (``mainSwitch/on=1`` → tile shows 亮度, ``mainSwitch/on=0 &&
  auxSwitch/on=1`` → tile shows 夜灯).  The home mode grid uses it as the
  active highlight and taps the active mode again to send
  ``{mainSwitch:{on:0}}`` (light off).  ``mainSwitch:{on:1}`` never appears
  in the H5 — it is a structurally certain RW bool payload
  (Profile enum 1=开/0=关) but the on-direction is only backed by the
  Profile, hence the dedicated "主灯开关" switch is documented as
  partially verified.
* ``auxSwitch`` / ``auxBrightness`` have no H5 settings page in this bundle
  (zero chunk hits) — only the quickmenu labels them as 夜灯.  The payloads
  ``{auxSwitch:{on:N}}`` / ``{auxBrightness:{brightness:N}}`` are derived
  from the Profile (RW, 0..100 %).
* ``lightMode`` dispatch: home ``changeLightMode`` sends ONLY
  ``{lightMode:{mode:e}}`` (no power toggle).  Selecting a mode implicitly
  turns the main light on; re-tapping the active mode turns it off via
  ``mainSwitch``.  Persistent entities do not replicate the re-tap-to-off
  UI shortcut; use the light/主灯开关 switches for that.
* ``delayTurnoff``: the delay card (``word: offDelay`` "延时关灯") dispatches
  ``{delayTurnoff:{delayTime:e}}`` with options 1/2/3 = 10/20/30 秒 and a
  close button that sends ``delayTime:0``.  The Profile descCh for 0 is
  just "0"; the label 关闭 comes from the H5 close action (``close`` in the
  language pack).
* ``indicator``: settings cell (``word: pilot`` "指示灯") toggles
  ``{indicator:{on:1-isIndicatorOn}}``.
* ``nightWakeup``: night-mode page (chunk_1) dispatches
  ``{nightWakeup:{enable:Number(t)}}``, ``{nightWakeup:{start:60*h+min}}``
  and ``{nightWakeup:{end:60*h+min}}`` — start/end are minutes of day
  (0..1440, Profile min/max agree).  The language pack labels the feature
  夜间模式 and its tip explains: during the period, touching the lamp panel
  lights the night light.  The H5 also reports a ``week`` bitmask which the
  Profile does NOT declare — not exposed.
* ``foldAngles``: read-only; the H5 derives ``isFold = foldAngles === 0``
  (its ability schema sloppily declares range [0,1] while the Profile
  declares 0..360 °) — exposed as a plain angle sensor.
* Main-light brightness range: the Profile declares min 0, but the H5
  ability schema and the brightness slider (``v-progress`` ``min:1``) both
  use 1..100; a reported 0 is treated as "no level" (unknown) and commands
  are clamped to 1..100 so we never send 0.
* Night-light brightness maps 1..100 → 1..255 (HA 0 = off); a reported 0 is
  unknown, and commands never send 0.

Deliberately *not* exposed:

* ``toggleSwitch`` — zero references in the whole bundle (all chunks +
  main.js).
* ``colourMode`` (R enum) — not present in the H5 report schema and never
  referenced; the 流光 labels cannot be verified for this model.
* ``directlyConnected`` — internal handshake flag: the store derives
  ``isAutoUpdateFirst`` from it and the auto-update flow dispatches
  ``{directlyConnected:{directlyConnected:1}}`` by itself; also used by the
  ``setDevInfo`` transport gate.  Not a user-facing switch.
* ``timeSync`` — clock/timezone sync driven by the app.
* ``timer`` / ``delay`` — array/object schedule services managed by the
  native timer/delay dialogs (``jumpToDelayInfoDialog``).
* ``delayTurnoff.lightStatus`` (R: 关闭/关闭中/打开) — transient countdown
  status of the delay-off feature, app-managed.
* ``update`` / ``netInfo`` — OTA and diagnostics, consistent with the other
  adapters.
* ``childLock`` — the H5 has a 童锁 row but the 2P13 Profile declares no
  such service; without a Profile service the integration cannot address it.

This adapter was derived from the Profile and vendor H5 bundle and is not yet
verified on a physical device.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

# Main light.
_SWITCH_SID = "switch"
_SWITCH_FIELD = "on"
_BRIGHTNESS_SID = "brightness"
_BRIGHTNESS_FIELD = "brightness"
# H5 ability schema + brightness slider both use 1..100 (Profile min 0 is
# treated as "no level reported").
_MAIN_BRIGHTNESS_RANGE = (1.0, 100.0)

# Main-light active flag (quickmenu: mainSwitch/on=1 ⇔ 主灯亮着).
_MAIN_SWITCH_SID = "mainSwitch"
_MAIN_SWITCH_FIELD = "on"

# Light mode.
_LIGHT_MODE_SID = "lightMode"
_LIGHT_MODE_FIELD = "mode"
# Labels confirmed by the H5 ability schema mean list and the Profile.
_LIGHT_MODE_OPTIONS = (
    (100, "读写"),
    (101, "阅屏"),
    (102, "无极调光"),
)

# Night light (夜灯).
_AUX_SWITCH_SID = "auxSwitch"
_AUX_SWITCH_FIELD = "on"
_AUX_BRIGHTNESS_SID = "auxBrightness"
_AUX_BRIGHTNESS_FIELD = "brightness"
_AUX_BRIGHTNESS_RANGE = (1.0, 100.0)

# Delay off (延时关灯).
_DELAY_OFF_SID = "delayTurnoff"
_DELAY_OFF_FIELD = "delayTime"
# 0 = 关闭 (H5 closeDelay button), 1..3 = 10/20/30 秒 (H5 select +
# Profile descCh).
_DELAY_OFF_OPTIONS = (
    (0, "关闭"),
    (1, "延时10秒"),
    (2, "延时20秒"),
    (3, "延时30秒"),
)

# Indicator (指示灯).
_INDICATOR_SID = "indicator"
_INDICATOR_FIELD = "on"

# Night mode (夜间模式).
_NIGHT_SID = "nightWakeup"
_NIGHT_ENABLE_FIELD = "enable"
_NIGHT_START_FIELD = "start"
_NIGHT_END_FIELD = "end"
_NIGHT_MINUTES_RANGE = (0.0, 1440.0)

# Fold angle (折叠角度).
_FOLD_SID = "foldAngles"
_FOLD_FIELD = "foldAngles"

# HA's brightness scale.  The floor is 1, not 0, because HA renders 0 as "off".
_HA_BRIGHTNESS_MIN = 1
_HA_BRIGHTNESS_MAX = 255

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


def _clamp_to_range(
    value: Any,
    value_range: tuple[float, float],
    step: float | None = None,
) -> int:
    """Clamp into an explicit range, snapping to the step when given."""

    number = _number(value)
    if number is None:
        raise ValueError("2P13 value is not a number")
    minimum, maximum = value_range
    number = min(max(float(number), minimum), maximum)
    if step is not None and step > 0:
        number = minimum + round((number - minimum) / step) * step
        number = min(max(number, minimum), maximum)
    return int(round(number))


def _device_brightness_to_ha(
    value: Any,
    value_range: tuple[float, float],
) -> int | None:
    """Convert the product's percentage brightness to HA's 1..255 scale."""

    number = _number(value)
    if number is None:
        return None
    minimum, maximum = value_range
    if number < minimum or number > maximum:
        # 0 (or out-of-range) means "no level reported" — unknown, not off.
        return None
    span = _HA_BRIGHTNESS_MAX - _HA_BRIGHTNESS_MIN
    return round(
        _HA_BRIGHTNESS_MIN + (number - minimum) * span / (maximum - minimum)
    )


def _ha_brightness_to_device(
    value: Any,
    value_range: tuple[float, float],
) -> int:
    """Convert HA's 1..255 brightness to the product percentage (never 0)."""

    number = _number(value)
    if number is None:
        raise ValueError("2P13 brightness must be a number")
    number = min(max(float(number), _HA_BRIGHTNESS_MIN), _HA_BRIGHTNESS_MAX)
    minimum, maximum = value_range
    span = _HA_BRIGHTNESS_MAX - _HA_BRIGHTNESS_MIN
    return _clamp_to_range(
        minimum + (number - _HA_BRIGHTNESS_MIN) * (maximum - minimum) / span,
        value_range,
    )


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
    # H5 controlAppliance toggles switch.on directly; the brightness slider
    # (only shown while the lamp is on and in 无极调光) dispatches
    # {brightness:{brightness:N}} separately.
    await context.async_send_service(_SWITCH_SID, {_SWITCH_FIELD: 1})
    if data.get("brightness") is not None:
        await context.async_send_service(
            _BRIGHTNESS_SID,
            {
                _BRIGHTNESS_FIELD: _ha_brightness_to_device(
                    data["brightness"],
                    _MAIN_BRIGHTNESS_RANGE,
                )
            },
        )


async def _light_turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    # controlAppliance: {switch:{on:0}} — both directly and during the
    # delay-off countdown.
    await context.async_send_service(_SWITCH_SID, {_SWITCH_FIELD: 0})


async def _light_mode_select_option(
    context: DeviceContext,
    data: Mapping[str, Any],
) -> None:
    # H5 changeLightMode sends {lightMode:{mode:e}} only — selecting a mode
    # implicitly turns the main light on.
    value = _enum_value(data.get("option"), _LIGHT_MODE_OPTIONS)
    await context.async_send_service(_LIGHT_MODE_SID, {_LIGHT_MODE_FIELD: value})


async def _main_switch_turn_on(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    # H5 only ever dispatches {mainSwitch:{on:0}} (re-tap the active mode to
    # switch the main light off); the 1 direction is Profile-structural
    # (RW bool, enum 1=开).
    await context.async_send_service(_MAIN_SWITCH_SID, {_MAIN_SWITCH_FIELD: 1})


async def _main_switch_turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(_MAIN_SWITCH_SID, {_MAIN_SWITCH_FIELD: 0})


async def _aux_turn_on(context: DeviceContext, data: Mapping[str, Any]) -> None:
    await context.async_send_service(_AUX_SWITCH_SID, {_AUX_SWITCH_FIELD: 1})
    if data.get("brightness") is not None:
        await context.async_send_service(
            _AUX_BRIGHTNESS_SID,
            {
                _AUX_BRIGHTNESS_FIELD: _ha_brightness_to_device(
                    data["brightness"],
                    _AUX_BRIGHTNESS_RANGE,
                )
            },
        )


async def _aux_turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(_AUX_SWITCH_SID, {_AUX_SWITCH_FIELD: 0})


async def _delay_off_select_option(
    context: DeviceContext,
    data: Mapping[str, Any],
) -> None:
    # H5 delay card: changeDelay dispatches {delayTurnoff:{delayTime:e}},
    # closeDelay dispatches {delayTurnoff:{delayTime:0}}.
    value = _enum_value(data.get("option"), _DELAY_OFF_OPTIONS)
    await context.async_send_service(_DELAY_OFF_SID, {_DELAY_OFF_FIELD: value})


async def _indicator_turn_on(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(_INDICATOR_SID, {_INDICATOR_FIELD: 1})


async def _indicator_turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(_INDICATOR_SID, {_INDICATOR_FIELD: 0})


async def _night_turn_on(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    # H5 night-mode page: {nightWakeup:{enable:Number(t)}}.
    await context.async_send_service(_NIGHT_SID, {_NIGHT_ENABLE_FIELD: 1})


async def _night_turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(_NIGHT_SID, {_NIGHT_ENABLE_FIELD: 0})


def _night_minutes_action(field_name: str):
    async def _set_value(context: DeviceContext, data: Mapping[str, Any]) -> None:
        # H5 timer pickers: {nightWakeup:{start:60*h+min}} / {end:...}.
        await context.async_send_service(
            _NIGHT_SID,
            {
                field_name: _clamp_to_range(
                    data.get("value"),
                    _NIGHT_MINUTES_RANGE,
                    step=1.0,
                )
            },
        )

    return _set_value


_night_start_set_value = _night_minutes_action(_NIGHT_START_FIELD)
_night_end_set_value = _night_minutes_action(_NIGHT_END_FIELD)


class Product2p13Adapter:
    """Keep all 2P13 entity and command choices in this file."""

    prod_id = "2P13"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None or not context.has_service(_SWITCH_SID):
            return ()

        specs: list[EntitySpec] = []

        # --- main light ---------------------------------------------------
        # Project stance: without the brightness field in the Profile the
        # light is not exposed at all, rather than risking a wrong state
        # mapping or a command the device cannot accept.
        if _field(profile, _BRIGHTNESS_SID, _BRIGHTNESS_FIELD) is not None:
            def light_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "is_on": _bool(device.value(_SWITCH_SID, _SWITCH_FIELD)),
                    "brightness": _device_brightness_to_ha(
                        device.value(_BRIGHTNESS_SID, _BRIGHTNESS_FIELD),
                        _MAIN_BRIGHTNESS_RANGE,
                    ),
                    "color_mode": _COLOR_MODE_BRIGHTNESS,
                }

            specs.append(
                EntitySpec(
                    platform="light",
                    key="main_light",
                    # Two lights on one device: explicit names instead of the
                    # device-name fallback.
                    name="主灯",
                    state=light_state,
                    metadata={
                        "supported_color_modes": {_COLOR_MODE_BRIGHTNESS},
                    },
                    actions={
                        "turn_on": _light_turn_on,
                        "turn_off": _light_turn_off,
                    },
                )
            )

        # --- light mode select ---------------------------------------------
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

        # --- main-light switch ----------------------------------------------
        if context.has_service(_MAIN_SWITCH_SID) and _field(
            profile, _MAIN_SWITCH_SID, _MAIN_SWITCH_FIELD
        ) is not None:
            def main_switch_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "is_on": _bool(
                        device.value(_MAIN_SWITCH_SID, _MAIN_SWITCH_FIELD)
                    )
                }

            specs.append(
                EntitySpec(
                    platform="switch",
                    key="main_switch",
                    name="主灯开关",
                    state=main_switch_state,
                    actions={
                        "turn_on": _main_switch_turn_on,
                        "turn_off": _main_switch_turn_off,
                    },
                )
            )

        # --- night light ------------------------------------------------------
        if (
            context.has_service(_AUX_SWITCH_SID)
            and _field(profile, _AUX_SWITCH_SID, _AUX_SWITCH_FIELD) is not None
            and _field(profile, _AUX_BRIGHTNESS_SID, _AUX_BRIGHTNESS_FIELD) is not None
        ):

            def aux_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "is_on": _bool(
                        device.value(_AUX_SWITCH_SID, _AUX_SWITCH_FIELD)
                    ),
                    "brightness": _device_brightness_to_ha(
                        device.value(_AUX_BRIGHTNESS_SID, _AUX_BRIGHTNESS_FIELD),
                        _AUX_BRIGHTNESS_RANGE,
                    ),
                    "color_mode": _COLOR_MODE_BRIGHTNESS,
                }

            specs.append(
                EntitySpec(
                    platform="light",
                    key="night_light",
                    name="夜灯",
                    state=aux_state,
                    metadata={
                        "supported_color_modes": {_COLOR_MODE_BRIGHTNESS},
                    },
                    actions={
                        "turn_on": _aux_turn_on,
                        "turn_off": _aux_turn_off,
                    },
                )
            )

        # --- delay off select ---------------------------------------------------
        if context.has_service(_DELAY_OFF_SID) and _field(
            profile, _DELAY_OFF_SID, _DELAY_OFF_FIELD
        ) is not None:
            def delay_off_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "current_option": _enum_label(
                        device.value(_DELAY_OFF_SID, _DELAY_OFF_FIELD),
                        _DELAY_OFF_OPTIONS,
                    )
                }

            specs.append(
                EntitySpec(
                    platform="select",
                    key="delay_off",
                    name="延时关灯",
                    state=delay_off_state,
                    metadata={
                        "options": [label for _, label in _DELAY_OFF_OPTIONS]
                    },
                    actions={"select_option": _delay_off_select_option},
                )
            )

        # --- indicator switch -----------------------------------------------------
        if context.has_service(_INDICATOR_SID) and _field(
            profile, _INDICATOR_SID, _INDICATOR_FIELD
        ) is not None:
            def indicator_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "is_on": _bool(
                        device.value(_INDICATOR_SID, _INDICATOR_FIELD)
                    )
                }

            specs.append(
                EntitySpec(
                    platform="switch",
                    key="indicator",
                    name="指示灯",
                    state=indicator_state,
                    actions={
                        "turn_on": _indicator_turn_on,
                        "turn_off": _indicator_turn_off,
                    },
                )
            )

        # --- night mode switch + times ---------------------------------------------
        if context.has_service(_NIGHT_SID) and _field(
            profile, _NIGHT_SID, _NIGHT_ENABLE_FIELD
        ) is not None:
            def night_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "is_on": _bool(
                        device.value(_NIGHT_SID, _NIGHT_ENABLE_FIELD)
                    )
                }

            specs.append(
                EntitySpec(
                    platform="switch",
                    key="night_mode",
                    name="夜间模式",
                    state=night_state,
                    actions={
                        "turn_on": _night_turn_on,
                        "turn_off": _night_turn_off,
                    },
                )
            )

        for key, name, field_name, action in (
            ("night_start", "夜间模式开始时间", _NIGHT_START_FIELD, _night_start_set_value),
            ("night_end", "夜间模式结束时间", _NIGHT_END_FIELD, _night_end_set_value),
        ):
            if not context.has_service(_NIGHT_SID) or _field(
                profile, _NIGHT_SID, field_name
            ) is None:
                continue

            def night_minutes_state(
                device: DeviceContext,
                _field_name: str = field_name,
            ) -> Mapping[str, Any]:
                return {"native_value": _number(
                    device.value(_NIGHT_SID, _field_name)
                )}

            specs.append(
                EntitySpec(
                    platform="number",
                    key=key,
                    name=name,
                    state=night_minutes_state,
                    metadata={
                        "min": _NIGHT_MINUTES_RANGE[0],
                        "max": _NIGHT_MINUTES_RANGE[1],
                        "step": 1,
                        # H5 timer pickers send 60*h+min — minutes of day.
                        "unit": "min",
                    },
                    actions={"set_value": action},
                )
            )

        # --- fold angle sensor ---------------------------------------------------
        if context.has_service(_FOLD_SID) and _field(
            profile, _FOLD_SID, _FOLD_FIELD
        ) is not None:
            def fold_state(device: DeviceContext) -> Mapping[str, Any]:
                return {"native_value": _number(
                    device.value(_FOLD_SID, _FOLD_FIELD)
                )}

            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="fold_angle",
                    name="折叠角度",
                    state=fold_state,
                    metadata={
                        # Profile: R, 0..360, unit °.  H5 isFold treats 0 as
                        # folded; the plain angle keeps both readings.
                        "unit": "°",
                        "state_class": "measurement",
                    },
                )
            )

        return tuple(specs)


ADAPTER = Product2p13Adapter()
