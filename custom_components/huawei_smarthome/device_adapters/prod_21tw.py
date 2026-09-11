"""User-contributed protocol for Huawei product 21TW.

Device: 鸿蒙智选 达伦智能台灯2 / DALEN Natural Light Table Lamp
(deviceModel ``MT615-D20WTT``, manufacturer 达伦DALEN, protocolType ``WiFi``).
Profile: https://smarthome-drcn.dbankcdn.com/device/guide/21TW/21TW.json

Exposed entities (every command payload below is copied from a real
``setDeviceInfo`` dispatch site in the vendor H5 bundle, webpack build with
async chunks ``static/js/app.<hash>.js`` + ``chunk_<id>.<hash>.js``):

* ``light``  主灯 (device-name fallback)
             <- ``switch.on`` (power) / ``brightness.brightness`` (int 1..100 %)
* ``select`` "灯光模式"   <- ``lightMode.mode``  (无极调光/读写/阅屏/学习管理)
* ``switch`` "学习模式"   <- ``studyMode.enable``
* ``select`` "学习模式类型" <- ``studyMode.mode`` (番茄模式/课堂模式/自定义)
* ``number`` "学习时长"   <- ``studyMode.totalDuration`` (int 1..180 min)
* ``sensor`` "剩余学习时间" <- ``studyMode.remainDuration`` (int 1..180 min, R)
* ``sensor`` "最近学习模式" <- ``studyResult.mode`` (R enum)
* ``sensor`` "最近学习时长" <- ``studyResult.duration`` (int 1..180 min, R)
* ``sensor`` "最近学习结果" <- ``studyResult.isFinish`` (R bool, 0/1 enum)

Payloads (from the vendor H5):

* ``{switch:{on:N}}``  — home page ``switchAction`` (chunk_2)
* ``{brightness:{brightness:N}}`` — home page ``brightnessProgressValueChanged``;
  when the lamp is off the H5 dispatches ``[{switch:{on:1}}, {brightness:…}]``
  as a multi command — this adapter sends the same two commands in order.
* ``{lightMode:{mode:N}}`` — home page ``sendModeCmd``; the mode grid renders
  3 buttons and calls ``modeSelectAction(s + 1)`` with labels from the ``modes``
  computed: index 0 → ``Dimming`` ("无极调光"), 1 → ``mode_writing`` ("读写"),
  2 → ``mode_reading`` ("阅屏").  This overrides the Profile ``descCh`` for
  value 1 ("自定义") — the H5 home page is the authoritative UI label.
  Value 4 exists only in the Profile enumList (``descCh`` "学习管理");
  the H5 has a dead ``modeSelectAction(4)`` branch that shows the
  "智能模式" auto-mode dialog, but it is never reachable from the rendered
  grid (the loop only builds 3 buttons), so the Profile label is used.
* ``{studyMode:{...}}`` — study pages (chunk_3/chunk_5) send the studyMode
  object with ``remainDuration`` stripped (``e.studyMode.remainDuration=void 0``).
  This adapter sends the single flipped/selected field
  (``{studyMode:{enable:N}}`` / ``{studyMode:{mode:N}}`` /
  ``{studyMode:{totalDuration:N}}``); the protocol applies per-field updates
  (the receiving ``updateState`` merges the reported data into the store),
  and the H5 "send everything" shape is only a UI convenience.

Deliberately *not* exposed:

* ``nightSwitch`` — declared RW bool in the Profile but referenced **zero**
  times in the whole H5 bundle (all chunks + app.js).  The H5 night-light
  state is rendered via ``5 === lightMode`` ("夜灯已开启" banner title) which
  the H5 itself never dispatches either.  With no dispatch site and no
  reported label, the semantics cannot be verified — per the project rule
  ("宁可不出实体，也不做错映射") it stays out until second-source evidence
  shows up.
* ``timer`` / ``delay`` — array/object schedule services managed by the
  native timer page (``jumpTo "com.huawei.smarthome.timerPage"``) and the
  native delay dialog (``showDelayInfoDialog``); the H5 only renders a local
  countdown (``delayTick``) and never dispatches these services.
* ``update`` — OTA flow driven by the app itself.
* ``netInfo`` — diagnostics, consistent with the other adapters.
* ``studyMode.name`` / ``studyMode.category`` — free-text fields used by the
  custom-study-mode editor (chunk_3 ``editstudyPage`` flow); they belong to
  the app's mode-management UI, not to lamp control.

Brightness scaling: the device reports a percentage in 1..100, while HA uses
0..255 and treats 0 as "off".  The mapping therefore targets 1..255 so the
lowest device step stays a visible level instead of collapsing into HA's "off"
value; the round trip is stable for every device value from 1 to 100.

The Profile stores ``min``/`max`` as numbers here, but they are still run
through the string-tolerant ``_number()`` normalization like every adapter.

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

# Light mode.
_LIGHT_MODE_SID = "lightMode"
_LIGHT_MODE_FIELD = "mode"
# Labels: 1..3 from the H5 home-page mode grid (modes computed +
# modeSelectAction(s + 1)); 4 from the Profile enumList descCh.
_LIGHT_MODE_OPTIONS = (
    (1, "无极调光"),
    (2, "读写"),
    (3, "阅屏"),
    (4, "学习管理"),
)

# Study mode.
_STUDY_SID = "studyMode"
_STUDY_ENABLE_FIELD = "enable"
_STUDY_MODE_FIELD = "mode"
_STUDY_TOTAL_FIELD = "totalDuration"
_STUDY_REMAIN_FIELD = "remainDuration"
# Labels: Profile enumList descCh (番茄/课堂/自定义) with the H5 language pack
# spelling (study_mode_tomato "番茄模式", study_mode_class "课堂模式",
# study_mode_custom "自定义").  Value 0 is a real mode ("自定义"), not a
# placeholder, and stays in the options.
_STUDY_MODE_OPTIONS = (
    (0, "自定义"),
    (1, "番茄模式"),
    (2, "课堂模式"),
)

# Study result.
_RESULT_SID = "studyResult"
_RESULT_MODE_FIELD = "mode"
_RESULT_DURATION_FIELD = "duration"
_RESULT_FINISH_FIELD = "isFinish"
# Labels from the Profile enumList descCh: 1 正常结束 / 0 中途中断.
_RESULT_FINISH_OPTIONS = (
    (0, "中途中断"),
    (1, "正常结束"),
)

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
        raise ValueError("21TW Profile range is incomplete")
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
        raise ValueError("21TW brightness range is missing from the Profile")
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
    # H5 (brightnessProgressValueChanged): when the lamp is off it dispatches
    # [{switch:{on:1}}, {brightness:{...}}] — power first, then brightness.
    await context.async_send_service(_SWITCH_SID, {_SWITCH_FIELD: 1})
    if data.get("brightness") is not None:
        field = _field(context.profile or {}, _BRIGHTNESS_SID, _BRIGHTNESS_FIELD)
        if field is None:
            raise ValueError("21TW brightness field is missing from the Profile")
        await context.async_send_service(
            _BRIGHTNESS_SID,
            {
                _BRIGHTNESS_FIELD: _ha_brightness_to_device(
                    data["brightness"],
                    field,
                )
            },
        )


async def _light_turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(_SWITCH_SID, {_SWITCH_FIELD: 0})


async def _light_mode_select_option(
    context: DeviceContext,
    data: Mapping[str, Any],
) -> None:
    # H5 sendModeCmd: {lightMode:{mode:N}} — no power toggle included.
    value = _enum_value(data.get("option"), _LIGHT_MODE_OPTIONS)
    await context.async_send_service(_LIGHT_MODE_SID, {_LIGHT_MODE_FIELD: value})


async def _study_turn_on(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(_STUDY_SID, {_STUDY_ENABLE_FIELD: 1})


async def _study_turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(_STUDY_SID, {_STUDY_ENABLE_FIELD: 0})


async def _study_mode_select_option(
    context: DeviceContext,
    data: Mapping[str, Any],
) -> None:
    value = _enum_value(data.get("option"), _STUDY_MODE_OPTIONS)
    await context.async_send_service(_STUDY_SID, {_STUDY_MODE_FIELD: value})


async def _study_duration_set_value(
    context: DeviceContext,
    data: Mapping[str, Any],
) -> None:
    field = _field(context.profile or {}, _STUDY_SID, _STUDY_TOTAL_FIELD)
    if field is None:
        raise ValueError("21TW study duration field is missing from the Profile")
    await context.async_send_service(
        _STUDY_SID,
        {_STUDY_TOTAL_FIELD: _clamp_to_profile(data.get("value"), field)},
    )


class Product21twAdapter:
    """Keep all 21TW entity and command choices in this file."""

    prod_id = "21TW"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None or not context.has_service(_SWITCH_SID):
            return ()

        specs: list[EntitySpec] = []

        # --- main light ---------------------------------------------------
        brightness = _field(profile, _BRIGHTNESS_SID, _BRIGHTNESS_FIELD)
        brightness_range = _profile_range(brightness)
        # Project stance: without a complete Profile the light is not exposed
        # at all, rather than risking a wrong state mapping or a command the
        # device cannot accept.
        if brightness_range is not None:
            def light_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "is_on": _bool(device.value(_SWITCH_SID, _SWITCH_FIELD)),
                    "brightness": _device_brightness_to_ha(
                        device.value(_BRIGHTNESS_SID, _BRIGHTNESS_FIELD),
                        brightness,
                    ),
                    "color_mode": _COLOR_MODE_BRIGHTNESS,
                }

            specs.append(
                EntitySpec(
                    platform="light",
                    key="light",
                    # Single-light device: the entity falls back to the device
                    # name (达伦智能台灯2).
                    name=None,
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

        # --- study mode switch ----------------------------------------------
        if context.has_service(_STUDY_SID) and _field(
            profile, _STUDY_SID, _STUDY_ENABLE_FIELD
        ) is not None:
            def study_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "is_on": _bool(
                        device.value(_STUDY_SID, _STUDY_ENABLE_FIELD)
                    )
                }

            specs.append(
                EntitySpec(
                    platform="switch",
                    key="study_mode",
                    name="学习模式",
                    state=study_state,
                    actions={
                        "turn_on": _study_turn_on,
                        "turn_off": _study_turn_off,
                    },
                )
            )

        # --- study mode type select -----------------------------------------
        if context.has_service(_STUDY_SID) and _field(
            profile, _STUDY_SID, _STUDY_MODE_FIELD
        ) is not None:
            def study_type_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "current_option": _enum_label(
                        device.value(_STUDY_SID, _STUDY_MODE_FIELD),
                        _STUDY_MODE_OPTIONS,
                    )
                }

            specs.append(
                EntitySpec(
                    platform="select",
                    key="study_mode_type",
                    name="学习模式类型",
                    state=study_type_state,
                    metadata={
                        "options": [label for _, label in _STUDY_MODE_OPTIONS]
                    },
                    actions={"select_option": _study_mode_select_option},
                )
            )

        # --- study duration number -------------------------------------------
        total_field = _field(profile, _STUDY_SID, _STUDY_TOTAL_FIELD)
        total_range = _profile_range(total_field)
        if context.has_service(_STUDY_SID) and total_range is not None:
            def study_duration_state(device: DeviceContext) -> Mapping[str, Any]:
                return {"native_value": _number(
                    device.value(_STUDY_SID, _STUDY_TOTAL_FIELD)
                )}

            specs.append(
                EntitySpec(
                    platform="number",
                    key="study_duration",
                    name="学习时长",
                    state=study_duration_state,
                    metadata={
                        "min": total_range[0],
                        "max": total_range[1],
                        "step": _profile_step(total_field) or 1,
                        # Profile min/max are 1..180 with no unit; the H5
                        # language pack formats study durations in minutes
                        # (tipText "若学习时间大于 45 分钟…", 180 = 3 小时上限).
                        "unit": "min",
                    },
                    actions={"set_value": _study_duration_set_value},
                )
            )

        # --- remaining study time sensor --------------------------------------
        remain_field = _field(profile, _STUDY_SID, _STUDY_REMAIN_FIELD)
        remain_range = _profile_range(remain_field)
        if context.has_service(_STUDY_SID) and remain_range is not None:
            def study_remain_state(device: DeviceContext) -> Mapping[str, Any]:
                return {"native_value": _number(
                    device.value(_STUDY_SID, _STUDY_REMAIN_FIELD)
                )}

            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="study_remain",
                    name="剩余学习时间",
                    state=study_remain_state,
                    metadata={
                        "unit": "min",
                        "state_class": "measurement",
                    },
                )
            )

        # --- study result sensors ----------------------------------------------
        if context.has_service(_RESULT_SID) and _field(
            profile, _RESULT_SID, _RESULT_MODE_FIELD
        ) is not None:
            def result_mode_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "native_value": _enum_label(
                        device.value(_RESULT_SID, _RESULT_MODE_FIELD),
                        _STUDY_MODE_OPTIONS,
                    )
                }

            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="last_study_mode",
                    name="最近学习模式",
                    state=result_mode_state,
                    # Plain-text enum: the sensor platform does not accept an
                    # options list, and 0/1/2 share the study-mode labels.
                )
            )

        if context.has_service(_RESULT_SID) and _field(
            profile, _RESULT_SID, _RESULT_DURATION_FIELD
        ) is not None:
            def result_duration_state(device: DeviceContext) -> Mapping[str, Any]:
                return {"native_value": _number(
                    device.value(_RESULT_SID, _RESULT_DURATION_FIELD)
                )}

            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="last_study_duration",
                    name="最近学习时长",
                    state=result_duration_state,
                    metadata={
                        "unit": "min",
                        "state_class": "measurement",
                    },
                )
            )

        if context.has_service(_RESULT_SID) and _field(
            profile, _RESULT_SID, _RESULT_FINISH_FIELD
        ) is not None:
            def result_finish_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "native_value": _enum_label(
                        device.value(_RESULT_SID, _RESULT_FINISH_FIELD),
                        _RESULT_FINISH_OPTIONS,
                    )
                }

            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="last_study_result",
                    name="最近学习结果",
                    state=result_finish_state,
                    # Exposed as text (正常结束/中途中断) instead of a
                    # binary_sensor so the "interrupted" state is readable,
                    # not just on/off.
                )
            )

        return tuple(specs)


ADAPTER = Product21twAdapter()
