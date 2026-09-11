"""User-contributed protocol for Huawei product 2QQQ.

Device: eachone 一起玩 人体存在平板灯 / Presence Panel Light
(deviceModel ``HF-HM-PBD-D1``, vendor 鸿钧电器, protocolType ``WiFi``).
Profile: https://smarthome-drcn.dbankcdn.com/device/guide/2QQQ/2QQQ.json

Exposed entities (every command payload below is copied from a real
``setDevInfo`` dispatch site in the vendor H5 bundle ``main.js`` /
async chunks ``chunk_2/6/10.js``):

* ``light`` (device-name fallback) <- ``switch.on``
                      / ``brightness.brightness``      (int 1..100 %)
                      / ``cct.colorTemperature``       (int 3000..5000 K)
* ``sensor`` "人在状态"   <- ``humanSensingStatus.status`` (read-only,
                      0 无人存在 / 1 有人存在 / 2 有人进入 / 3 有人离开;
                      values 2/3 come from the H5 language pack, the Profile
                      enumList only declares 0/1)
* ``switch`` "人体感应"   <- ``inductionSwitch.on``
* ``number`` "感应距离"   <- ``inductionCondition.length`` — the device stores
                      centimetres (150..600, step 50); the H5 picker renders
                      ``length / 100`` with a 米 tail, so the HA entity uses
                      metres (1.5..6.0, step 0.5) and converts on both sides
* ``number`` "无人判定时长" <- ``checkTime.time`` (1..30 min, H5 picker tail
                      is "minute")
* ``number`` "感应开启时间" <- ``inductionTime.start`` (0..1440 min, the H5
                      picker confirms with ``60*hour + minute``)
* ``number`` "感应关闭时间" <- ``inductionTime.end`` (0..1440 min)
* ``select`` "灯光模式"   <- ``lightMode.mode`` (休闲/浪漫/工作/清扫/光配方/
                      夜间/空模式)
* ``switch`` "夜间唤醒"   <- ``nightWakeup.enable``
* ``number`` "夜间唤醒开始时间" <- ``nightWakeup.start`` (0..1440 min)
* ``number`` "夜间唤醒结束时间" <- ``nightWakeup.end`` (0..1440 min)
* ``select`` "断电记忆"   <- ``commonMemorySwitch.status`` (0 关 / 1 开 /
                      2 保持上次状态)
* ``switch`` "开关翻转"   <- ``toggleSwitch.toggle`` — a persistent wall-switch
                      inversion setting (H5 tip: only enable with smart wall
                      switches), NOT a stateless toggle; the H5 dispatches
                      ``{toggleSwitch:{toggle:1-current}}`` from a settings row
* ``number`` "渐变时长"   <- ``progressSwitch.range`` (seconds; the H5 renders
                      it as minutes + seconds)

Payloads (real dispatch sites):

* ``{switch:{on:N}}`` / ``{brightness:{brightness:N}}`` / ``{cct:{colorTemperature:N}}``
* ``{inductionSwitch:{on:N}}`` (main.js switchRes, value flip → explicit set)
* ``{inductionCondition:{length:cm}}`` (chunk_6 gyjlConfirm)
* ``{checkTime:{time:min}}`` (chunk_6 wrpdscConfirm)
* ``{inductionTime:{start|min}}`` / ``{inductionTime:{end|min}}`` (chunk_6)
* ``{lightMode:{mode:v}}`` (main.js playListRes)
* ``{nightWakeup:{enable:N}}`` (chunk_10 tap), ``{nightWakeup:{start|min}}`` /
  ``{nightWakeup:{end|min}}`` (chunk_10 confirmStart/EndTime)
* ``{commonMemorySwitch:{status:v}}`` (main.js)
* ``{toggleSwitch:{toggle:N}}`` (main.js switchRes)
* ``{progressSwitch:{range:s}}`` (main.js submitFadeTime)

Known range conflict on ``progressSwitch.range``: the Profile declares
min=1 max=10 while the H5 schema/picker allow up to 360 seconds.  The adapter
clamps to the Profile range — commands the device does not declare are never
sent, even if that limits the slider below what the vendor UI offers.

Deliberately *not* exposed:

* ``preview`` — the light-formula editor's temporary 10-second preview;
  the H5 enables it on page entry and force-disables it on exit, an
  app-managed ephemeral flow (chunk_2).
* ``lightFormulaArray`` / ``preLightFormulaArray`` — array-structured light
  recipes managed through dedicated app pages (LightFormulaList/Set).
* ``delay`` / ``timer`` — array-structured countdown/timer flows managed
  through dedicated pages.
* ``nightWakeup.brightness`` (Profile 1..30) — declared in the schema but no
  dispatch site in the bundle sends it.
* ``humanSensingStatus`` is read-only and covered by the sensor above;
  ``checkSum`` / ``netInfo`` / ``update`` — diagnostics and OTA, consistent
  with the other adapters.

The Profile stores ``min``/``max`` as strings, so they are normalised before
being handed to HA.  Unknown enum values map to ``None`` (unknown) instead of
a guessed label.  This adapter was derived from the Profile and vendor H5
bundle and is not yet verified on a physical device.
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

# Presence sensor (read-only).
_PRESENCE_SID = "humanSensingStatus"
_PRESENCE_FIELD = "status"
# 0/1 from the Profile enumList; 2/3 from the H5 language pack (人在检测_N).
_PRESENCE_OPTIONS = (
    (0, "无人存在"),
    (1, "有人存在"),
    (2, "有人进入"),
    (3, "有人离开"),
)

# Human sensing feature.
_INDUCTION_SWITCH_SID = "inductionSwitch"
_INDUCTION_SWITCH_FIELD = "on"
_DISTANCE_SID = "inductionCondition"
_DISTANCE_FIELD = "length"
# Device stores centimetres; the H5 renders length/100 as 米.
_DISTANCE_CM_PER_METRE = 100
_NODURATION_SID = "checkTime"
_NODURATION_FIELD = "time"
_WINDOW_SID = "inductionTime"

# Light scenes.
_LIGHT_MODE_SID = "lightMode"
_LIGHT_MODE_FIELD = "mode"
# From the Profile enumList.  12 (光配方) is managed by app pages in the H5
# but stays selectable so the state always renders; 100 (空模式) is a
# placeholder reported by the device and stays listed too.
_LIGHT_MODE_OPTIONS = (
    (1, "休闲模式"),
    (5, "浪漫模式"),
    (6, "工作模式"),
    (9, "清扫模式"),
    (12, "光配方"),
    (13, "夜间模式"),
    (100, "空模式"),
)

# Night wake-up.
_WAKE_SID = "nightWakeup"
_WAKE_ENABLE_FIELD = "enable"

# Memory switch.
_MEMORY_SID = "commonMemorySwitch"
_MEMORY_FIELD = "status"
_MEMORY_OPTIONS = (
    (0, "关"),
    (1, "开"),
    (2, "保持上次状态"),
)

# Wall-switch inversion (persistent setting, not a stateless toggle).
_TOGGLE_SID = "toggleSwitch"
_TOGGLE_FIELD = "toggle"

# Gradient duration (seconds).  Profile clamps to 1..10 even though the
# vendor UI offers up to 360 — see module docstring.
_FADE_SID = "progressSwitch"
_FADE_FIELD = "range"

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
        raise ValueError("2QQQ Profile range is incomplete")
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
        raise ValueError("2QQQ brightness range is missing from the Profile")
    minimum, maximum = value_range
    number = min(max(float(number), _HA_BRIGHTNESS_MIN), _HA_BRIGHTNESS_MAX)
    span = _HA_BRIGHTNESS_MAX - _HA_BRIGHTNESS_MIN
    return _clamp_to_profile(
        minimum + (number - _HA_BRIGHTNESS_MIN) * (maximum - minimum) / span,
        field,
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
    await context.async_send_service(_SWITCH_SID, {_SWITCH_FIELD: 1})
    if data.get("brightness") is not None:
        field = _field(context.profile or {}, _BRIGHTNESS_SID, _BRIGHTNESS_FIELD)
        if field is None:
            raise ValueError("2QQQ brightness field is missing from the Profile")
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
            raise ValueError("2QQQ colour temperature field is missing")
        await context.async_send_service(
            _CCT_SID,
            {_CCT_FIELD: _clamp_to_profile(data["color_temp_kelvin"], field)},
        )


async def _light_turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(_SWITCH_SID, {_SWITCH_FIELD: 0})


def _flag_state(sid: str, field_name: str):
    def state(device: DeviceContext) -> Mapping[str, Any]:
        return {"is_on": _bool(device.value(sid, field_name))}

    return state


def _flag_action(sid: str, field_name: str, value: int):
    async def action(context: DeviceContext, _data: Mapping[str, Any]) -> None:
        # The H5 flips the current value; HA uses explicit on/off, so the
        # adapter always writes the requested value instead.
        await context.async_send_service(sid, {field_name: value})

    return action


def _switch_spec(
    sid: str,
    field_name: str,
    key: str,
    name: str,
) -> EntitySpec:
    return EntitySpec(
        platform="switch",
        key=key,
        name=name,
        state=_flag_state(sid, field_name),
        actions={
            "turn_on": _flag_action(sid, field_name, 1),
            "turn_off": _flag_action(sid, field_name, 0),
        },
    )


async def _light_mode_select_option(
    context: DeviceContext,
    data: Mapping[str, Any],
) -> None:
    value = _enum_value(data.get("option"), _LIGHT_MODE_OPTIONS)
    await context.async_send_service(_LIGHT_MODE_SID, {_LIGHT_MODE_FIELD: value})


async def _memory_select_option(
    context: DeviceContext,
    data: Mapping[str, Any],
) -> None:
    value = _enum_value(data.get("option"), _MEMORY_OPTIONS)
    await context.async_send_service(_MEMORY_SID, {_MEMORY_FIELD: value})


def _int_number_spec(
    sid: str,
    field_name: str,
    key: str,
    name: str,
    unit: str,
) -> EntitySpec:
    """Number entity backed 1:1 by an int Profile field (minutes/seconds)."""

    def state(device: DeviceContext) -> Mapping[str, Any]:
        return {"native_value": _number(device.value(sid, field_name))}

    async def set_value(context: DeviceContext, data: Mapping[str, Any]) -> None:
        field = _field(context.profile or {}, sid, field_name)
        if field is None:
            raise ValueError(f"2QQQ {sid}.{field_name} is missing from the Profile")
        await context.async_send_service(
            sid,
            {field_name: _clamp_to_profile(data.get("value"), field)},
        )

    return EntitySpec(
        platform="number",
        key=key,
        name=name,
        state=state,
        metadata={"min": None, "max": None, "step": None, "unit": unit},
        actions={"set_value": set_value},
    )


def _int_number_metadata(
    profile: Mapping[str, Any],
    spec: EntitySpec,
    sid: str,
    field_name: str,
    scale: float = 1.0,
) -> EntitySpec:
    """Fill a _int_number_spec's min/max/step from the Profile, scaled."""

    field = _field(profile, sid, field_name)
    value_range = _profile_range(field)
    metadata = dict(spec.metadata)
    if value_range is not None:
        metadata["min"] = value_range[0] / scale
        metadata["max"] = value_range[1] / scale
    step = _profile_step(field)
    if step is not None:
        metadata["step"] = step / scale
    return EntitySpec(
        platform=spec.platform,
        key=spec.key,
        name=spec.name,
        state=spec.state,
        metadata=metadata,
        actions=spec.actions,
    )


class Product2qqqAdapter:
    """Keep all 2QQQ entity and command choices in this file."""

    prod_id = "2QQQ"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None or not context.has_service(_SWITCH_SID):
            return ()

        specs: list[EntitySpec] = []

        # --- light --------------------------------------------------------
        brightness = _field(profile, _BRIGHTNESS_SID, _BRIGHTNESS_FIELD)
        cct = _field(profile, _CCT_SID, _CCT_FIELD)
        brightness_range = _profile_range(brightness)
        cct_range = _profile_range(cct)
        # Project stance: without a complete Profile the light is not created
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
                    name=None,
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

        # --- presence sensor (read-only) ----------------------------------
        if context.has_service(_PRESENCE_SID) and _field(
            profile, _PRESENCE_SID, _PRESENCE_FIELD
        ) is not None:
            def presence_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "native_value": _enum_label(
                        device.value(_PRESENCE_SID, _PRESENCE_FIELD),
                        _PRESENCE_OPTIONS,
                    )
                }

            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="presence",
                    name="人在状态",
                    state=presence_state,
                    metadata={},
                )
            )

        # --- human sensing ------------------------------------------------
        if context.has_service(_INDUCTION_SWITCH_SID) and _field(
            profile, _INDUCTION_SWITCH_SID, _INDUCTION_SWITCH_FIELD
        ) is not None:
            specs.append(
                _switch_spec(
                    _INDUCTION_SWITCH_SID,
                    _INDUCTION_SWITCH_FIELD,
                    key="induction_switch",
                    name="人体感应",
                )
            )

        # Sensor distance: device centimetres -> HA metres.
        distance_field = _field(profile, _DISTANCE_SID, _DISTANCE_FIELD)
        distance_range = _profile_range(distance_field)
        if context.has_service(_DISTANCE_SID) and distance_range is not None:
            def distance_state(device: DeviceContext) -> Mapping[str, Any]:
                value = _number(device.value(_DISTANCE_SID, _DISTANCE_FIELD))
                if value is None:
                    return {"native_value": None}
                return {"native_value": value / _DISTANCE_CM_PER_METRE}

            async def distance_set_value(
                context: DeviceContext,
                data: Mapping[str, Any],
            ) -> None:
                field = _field(context.profile or {}, _DISTANCE_SID, _DISTANCE_FIELD)
                if field is None:
                    raise ValueError("2QQQ inductionCondition.length is missing")
                metres = _number(data.get("value"))
                if metres is None:
                    raise ValueError("2QQQ sensor distance must be a number")
                await context.async_send_service(
                    _DISTANCE_SID,
                    {
                        _DISTANCE_FIELD: _clamp_to_profile(
                            metres * _DISTANCE_CM_PER_METRE,
                            field,
                        )
                    },
                )

            specs.append(
                EntitySpec(
                    platform="number",
                    key="sensor_distance",
                    name="感应距离",
                    state=distance_state,
                    metadata={
                        "min": distance_range[0] / _DISTANCE_CM_PER_METRE,
                        "max": distance_range[1] / _DISTANCE_CM_PER_METRE,
                        "step": (_profile_step(distance_field) or 1)
                        / _DISTANCE_CM_PER_METRE,
                        # H5 picker renders length/100 with a 米 tail.
                        "unit": "m",
                    },
                    actions={"set_value": distance_set_value},
                )
            )

        # No-one duration (minutes).
        if context.has_service(_NODURATION_SID) and _field(
            profile, _NODURATION_SID, _NODURATION_FIELD
        ) is not None:
            specs.append(
                _int_number_metadata(
                    profile,
                    _int_number_spec(
                        _NODURATION_SID,
                        _NODURATION_FIELD,
                        key="no_one_duration",
                        name="无人判定时长",
                        unit="min",
                    ),
                    _NODURATION_SID,
                    _NODURATION_FIELD,
                )
            )

        # Sensing time window (minutes).  H5 sends 60*hour + minute.
        for field_name, key, name in (
            ("start", "induction_start", "感应开启时间"),
            ("end", "induction_end", "感应关闭时间"),
        ):
            if context.has_service(_WINDOW_SID) and _field(
                profile, _WINDOW_SID, field_name
            ) is not None:
                specs.append(
                    _int_number_metadata(
                        profile,
                        _int_number_spec(
                            _WINDOW_SID,
                            field_name,
                            key=key,
                            name=name,
                            unit="min",
                        ),
                        _WINDOW_SID,
                        field_name,
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

        # --- night wake-up ------------------------------------------------
        if context.has_service(_WAKE_SID) and _field(
            profile, _WAKE_SID, _WAKE_ENABLE_FIELD
        ) is not None:
            specs.append(
                _switch_spec(
                    _WAKE_SID,
                    _WAKE_ENABLE_FIELD,
                    key="night_wakeup",
                    name="夜间唤醒",
                )
            )
            for field_name, key, name in (
                ("start", "night_wakeup_start", "夜间唤醒开始时间"),
                ("end", "night_wakeup_end", "夜间唤醒结束时间"),
            ):
                if _field(profile, _WAKE_SID, field_name) is not None:
                    specs.append(
                        _int_number_metadata(
                            profile,
                            _int_number_spec(
                                _WAKE_SID,
                                field_name,
                                key=key,
                                name=name,
                                unit="min",
                            ),
                            _WAKE_SID,
                            field_name,
                        )
                    )

        # --- memory switch select -----------------------------------------
        if context.has_service(_MEMORY_SID) and _field(
            profile, _MEMORY_SID, _MEMORY_FIELD
        ) is not None:
            def memory_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "current_option": _enum_label(
                        device.value(_MEMORY_SID, _MEMORY_FIELD),
                        _MEMORY_OPTIONS,
                    )
                }

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

        # --- wall-switch inversion ----------------------------------------
        if context.has_service(_TOGGLE_SID) and _field(
            profile, _TOGGLE_SID, _TOGGLE_FIELD
        ) is not None:
            specs.append(
                _switch_spec(
                    _TOGGLE_SID,
                    _TOGGLE_FIELD,
                    key="wall_toggle",
                    name="开关翻转",
                )
            )

        # --- gradient duration (seconds) -----------------------------------
        fade_field = _field(profile, _FADE_SID, _FADE_FIELD)
        fade_range = _profile_range(fade_field)
        if context.has_service(_FADE_SID) and fade_range is not None:
            specs.append(
                _int_number_metadata(
                    profile,
                    _int_number_spec(
                        _FADE_SID,
                        _FADE_FIELD,
                        key="gradient_time",
                        name="渐变时长",
                        unit="s",
                    ),
                    _FADE_SID,
                    _FADE_FIELD,
                )
            )

        return tuple(specs)


ADAPTER = Product2qqqAdapter()
