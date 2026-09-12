"""User-contributed protocol for Huawei product 2RJB.

Device: 迈睿人体存在传感器 电池版 / MeRiTech battery-powered presence
sensor (deviceModel ``MH3``, vendor 深圳迈睿智能科技, protocolType ``Mesh``).
Profile: https://smarthome-drcn.dbankcdn.com/device/guide/2RJB/2RJB.json

Exposed entities (every command payload below is copied from a real
``setDevInfo`` dispatch site in the vendor H5 bundle ``main.js`` /
async chunks; the sub pages live in webpack async chunks addressed via
the manifest chunk map):

* ``binary_sensor`` "人体存在"     <- ``pir.status`` (1 有人 / 0 无人,
                      device_class ``motion``; the vendor home page renders it
                      as 人在检测/Motion status)
* ``sensor`` "光照度"              <- ``luminance.current`` (unit ``lx``,
                      the vendor home page renders 光照度: <n>lux)
* ``sensor`` "光照强度"            <- ``luminance.level`` (text labels from the
                      Profile: 暗光(0～10)/微光(11～20)/弱光(21～30)/
                      适中(31～300)/较强(301～500)/很强(501以上))
* ``sensor`` "目标距离"            <- ``targetDistance.distance`` — the device
                      reports decimetres; the auto-measure page saves
                      ``triggerDistance = 10 * distance`` (cm) and renders
                      ``distance / 10`` as 米.  255 is the "measuring"
                      sentinel and maps to unknown.
* ``sensor`` "电池电量"            <- ``battery.level`` (1..100 %, the vendor
                      page highlights values <= 20)
* ``binary_sensor`` "低电量告警"   <- ``battery.alarm`` (device_class
                      ``battery``: on = low)
* ``switch`` "设备开关"            <- ``deviceSwitch.on`` (vendor home power)
* ``switch`` "指示灯闪烁"          <- ``indicator.indicator`` — the 指示灯 page
                      row "检测到有人时，指示灯会闪烁一次"
* ``select`` "触发有人灵敏度"      <- ``sensitivity.gear`` (0 高 / 1 中 / 2 低)
* ``select`` "维持有人灵敏度"      <- ``sensitivity.radarGear`` (0 高 / 1 中 / 2 低)
* ``select`` "配置模式"            <- ``detectionPara.cfgMode`` (0 普通模式 /
                      1 极客模式)
* ``number`` "触发有人检测距离"    <- ``detectionPara.triggerDistance`` — device
                      centimetres (100..600, step 50) exposed as metres
                      1.0..6.0, matching the vendor UI which works in 米
* ``number`` "维持有人感应范围"    <- ``detectionPara.detectionDistance`` —
                      device centimetres (100..400, step 50) as metres
                      1.0..4.0 (vendor picker 1..4 米)
* ``number`` "无人检测最短时间"    <- ``delayTime.time`` (20..180 s; vendor
                      picker titles are "<n> 秒")
* ``switch`` "自动抗干扰"          <- ``envNoiseMgmt.autoAntiInterference``
* ``button`` "重置无人状态"        <- ``{action:{action:1}}`` (chunk_3
                      resetBtn; vendor desc: report absence instantly)
* ``button`` "排除干扰"            <- ``{action:{action:101}}`` (chunk_2
                      setAction(101))

Payloads (real dispatch sites):

* ``{deviceSwitch:{on:N}}`` (main.js home power toggle)
* ``{indicator:{indicator:N}}`` / ``{ledSwitch:{on:N}}`` (chunk_7)
* ``{sensitivity:{gear:e}}`` / ``{sensitivity:{radarGear:e}}`` (chunk_3)
* ``{detectionPara:{cfgMode:1-current}}`` (chunk_3), ``{triggerDistance:e}``
  (chunk_0/4/6), ``{detectionDistance:e}`` (chunk_3)
* ``{delayTime:{time:e}}`` (chunk_3)
* ``{envNoiseMgmt:{autoAntiInterference:e}}`` (chunk_2)
* ``{action:{action:1}}`` (chunk_3), ``{action:{action:101}}`` (chunk_2)

Deliberately *not* exposed:

* ``ledSwitch`` — declared in the schema but no rendered row anywhere in
  this build (the 指示灯 page only renders the 指示灯闪烁 row).
* ``selfCheck`` — zero references in the whole H5 bundle.
* ``checkResult.status`` — connection-check state used only as a logic gate
  inside the app (delay/learning flows), never rendered.
* ``envNoiseMgmt.mode`` / ``disturbanceDist`` — noise-learning diagnostics;
  ``disturbanceDist`` is a per-bit centimetre mask (bit0 = 0-50 cm …) whose
  bits the app never surfaces individually.
* ``action`` value 100 (自动设置距离) — an app flow: trigger the measurement,
  poll ``targetDistance``, then save ``triggerDistance`` from the app; the
  bare command does not persist anything.
* ``battery`` schema extras (charging/capacity/threshold) — not in this
  device's Profile.
* ``update`` — OTA, consistent with the other adapters.

The Profile stores ``min``/``max`` as strings, normalised before handing to
HA.  Unknown enum values map to ``None`` (unknown).  This adapter was derived
from the Profile and vendor H5 bundle and is not yet verified on a physical
device.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

# Presence.
_PIR_SID = "pir"
_PIR_FIELD = "status"

# Illuminance.
_LUMI_SID = "luminance"
_LUMI_CURRENT_FIELD = "current"
_LUMI_LEVEL_FIELD = "level"
# Labels from the Profile enumList descriptions.
_LIGHT_LEVEL_OPTIONS = (
    (1, "暗光(0～10)"),
    (2, "微光(11～20)"),
    (3, "弱光(21～30)"),
    (4, "适中(31～300)"),
    (5, "较强(301～500)"),
    (6, "很强(501以上)"),
)

# Target distance: device decimetres; 255 = "measuring" sentinel.
_TARGET_SID = "targetDistance"
_TARGET_FIELD = "distance"
_TARGET_SENTINEL = 255
_TARGET_CM_PER_UNIT = 10  # device unit = 10 cm

# Battery.
_BATTERY_SID = "battery"
_BATTERY_ALARM_FIELD = "alarm"
_BATTERY_LEVEL_FIELD = "level"

# Switches.
_DEVICE_SWITCH_SID = "deviceSwitch"
_DEVICE_SWITCH_FIELD = "on"
_INDICATOR_SID = "indicator"
_INDICATOR_FIELD = "indicator"

# Sensitivity selects.
_SENSITIVITY_SID = "sensitivity"
_SENS_GEAR_FIELD = "gear"
_SENS_RADAR_FIELD = "radarGear"
# Profile labels: 0 高 / 1 中 / 2 低 (both gears share the scale).
_GEAR_OPTIONS = (
    (0, "高"),
    (1, "中"),
    (2, "低"),
)

# Detection parameters.
_DETECTION_SID = "detectionPara"
_CFG_MODE_FIELD = "cfgMode"
_CFG_MODE_OPTIONS = (
    (0, "普通模式"),
    (1, "极客模式"),
)
_TRIGGER_FIELD = "triggerDistance"
_DETECTION_FIELD = "detectionDistance"
_CM_PER_METRE = 100

# Hold time (seconds).
_DELAY_SID = "delayTime"
_DELAY_FIELD = "time"

# Noise management.
_NOISE_SID = "envNoiseMgmt"
_NOISE_AUTO_FIELD = "autoAntiInterference"

# Action buttons.
_ACTION_SID = "action"
_ACTION_FIELD = "action"
_ACTION_RESET_ABSENCE = 1
_ACTION_EXCLUDE_INTERFERENCE = 101

_SENSOR_UNIT_LUX = "lx"
_SENSOR_UNIT_METRE = "m"
_SENSOR_UNIT_PERCENT = "%"


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
        raise ValueError("2RJB Profile range is incomplete")
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


def _button_spec(sid: str, key: str, name: str, action_value: int) -> EntitySpec:
    async def press(context: DeviceContext, _data: Mapping[str, Any]) -> None:
        await context.async_send_service(sid, {_ACTION_FIELD: action_value})

    return EntitySpec(
        platform="button",
        key=key,
        name=name,
        state=lambda _device: {},
        actions={"press": press},
    )


def _select_spec(
    sid: str,
    field_name: str,
    key: str,
    name: str,
    options: tuple[tuple[int, str], ...],
) -> EntitySpec:
    def state(device: DeviceContext) -> Mapping[str, Any]:
        return {
            "current_option": _enum_label(device.value(sid, field_name), options)
        }

    async def select_option(context: DeviceContext, data: Mapping[str, Any]) -> None:
        value = _enum_value(data.get("option"), options)
        await context.async_send_service(sid, {field_name: value})

    return EntitySpec(
        platform="select",
        key=key,
        name=name,
        state=state,
        metadata={"options": [label for _, label in options]},
        actions={"select_option": select_option},
    )


def _distance_number_spec(
    sid: str,
    field_name: str,
    key: str,
    name: str,
    field: Mapping[str, Any],
    value_range: tuple[float, float],
) -> EntitySpec:
    """Number entity over a centimetre field, exposed in metres."""

    def state(device: DeviceContext) -> Mapping[str, Any]:
        value = _number(device.value(sid, field_name))
        if value is None:
            return {"native_value": None}
        return {"native_value": value / _CM_PER_METRE}

    async def set_value(context: DeviceContext, data: Mapping[str, Any]) -> None:
        active_field = _field(context.profile or {}, sid, field_name)
        if active_field is None:
            raise ValueError(f"2RJB {sid}.{field_name} is missing from the Profile")
        metres = _number(data.get("value"))
        if metres is None:
            raise ValueError("2RJB distance must be a number")
        await context.async_send_service(
            sid,
            {field_name: _clamp_to_profile(metres * _CM_PER_METRE, active_field)},
        )

    step = _profile_step(field) or 1
    return EntitySpec(
        platform="number",
        key=key,
        name=name,
        state=state,
        metadata={
            "min": value_range[0] / _CM_PER_METRE,
            "max": value_range[1] / _CM_PER_METRE,
            "step": step / _CM_PER_METRE,
            # The vendor pickers work in 米 (cm / 100).
            "unit": _SENSOR_UNIT_METRE,
        },
        actions={"set_value": set_value},
    )


class Product2rjbAdapter:
    """Keep all 2RJB entity and command choices in this file."""

    prod_id = "2RJB"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        specs: list[EntitySpec] = []

        # --- presence (read-only) -----------------------------------------
        if context.has_service(_PIR_SID) and _field(
            profile, _PIR_SID, _PIR_FIELD
        ) is not None:
            def presence_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "is_on": _bool(device.value(_PIR_SID, _PIR_FIELD))
                }

            specs.append(
                EntitySpec(
                    platform="binary_sensor",
                    key="presence",
                    name="人体存在",
                    state=presence_state,
                    metadata={"device_class": "motion"},
                )
            )

        # --- illuminance (read-only, lux) ----------------------------------
        if context.has_service(_LUMI_SID) and _field(
            profile, _LUMI_SID, _LUMI_CURRENT_FIELD
        ) is not None:
            def illuminance_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "native_value": _number(
                        device.value(_LUMI_SID, _LUMI_CURRENT_FIELD)
                    )
                }

            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="illuminance",
                    name="光照度",
                    state=illuminance_state,
                    metadata={
                        "device_class": "illuminance",
                        "state_class": "measurement",
                        # Vendor home page renders 光照度: <n>lux.
                        "unit": _SENSOR_UNIT_LUX,
                    },
                )
            )

        # --- light level (read-only, text) ---------------------------------
        if context.has_service(_LUMI_SID) and _field(
            profile, _LUMI_SID, _LUMI_LEVEL_FIELD
        ) is not None:
            def light_level_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "native_value": _enum_label(
                        device.value(_LUMI_SID, _LUMI_LEVEL_FIELD),
                        _LIGHT_LEVEL_OPTIONS,
                    )
                }

            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="light_level",
                    name="光照强度",
                    state=light_level_state,
                    metadata={},
                )
            )

        # --- target distance (read-only, decimetres -> metres) -------------
        if context.has_service(_TARGET_SID) and _field(
            profile, _TARGET_SID, _TARGET_FIELD
        ) is not None:
            def target_state(device: DeviceContext) -> Mapping[str, Any]:
                value = _number(device.value(_TARGET_SID, _TARGET_FIELD))
                # 255 is the vendor "measuring" sentinel (正在检测).
                if value is None or value == _TARGET_SENTINEL:
                    return {"native_value": None}
                return {"native_value": value * _TARGET_CM_PER_UNIT / _CM_PER_METRE}

            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="target_distance",
                    name="目标距离",
                    state=target_state,
                    metadata={
                        # The auto-measure page saves triggerDistance (cm) =
                        # 10 * distance and renders distance / 10 as 米.
                        "unit": _SENSOR_UNIT_METRE,
                    },
                )
            )

        # --- battery (read-only) -------------------------------------------
        if context.has_service(_BATTERY_SID):
            if _field(profile, _BATTERY_SID, _BATTERY_LEVEL_FIELD) is not None:
                def battery_state(device: DeviceContext) -> Mapping[str, Any]:
                    return {
                        "native_value": _number(
                            device.value(_BATTERY_SID, _BATTERY_LEVEL_FIELD)
                        )
                    }

                specs.append(
                    EntitySpec(
                        platform="sensor",
                        key="battery_level",
                        name="电池电量",
                        state=battery_state,
                        metadata={
                            "device_class": "battery",
                            "state_class": "measurement",
                            "unit": _SENSOR_UNIT_PERCENT,
                        },
                    )
                )
            if _field(profile, _BATTERY_SID, _BATTERY_ALARM_FIELD) is not None:
                def alarm_state(device: DeviceContext) -> Mapping[str, Any]:
                    return {
                        "is_on": _bool(
                            device.value(_BATTERY_SID, _BATTERY_ALARM_FIELD)
                        )
                    }

                specs.append(
                    EntitySpec(
                        platform="binary_sensor",
                        key="battery_alarm",
                        name="低电量告警",
                        state=alarm_state,
                        metadata={"device_class": "battery"},
                    )
                )

        # --- switches -------------------------------------------------------
        if context.has_service(_DEVICE_SWITCH_SID) and _field(
            profile, _DEVICE_SWITCH_SID, _DEVICE_SWITCH_FIELD
        ) is not None:
            specs.append(
                _switch_spec(
                    _DEVICE_SWITCH_SID,
                    _DEVICE_SWITCH_FIELD,
                    key="device_switch",
                    name="设备开关",
                )
            )
        if context.has_service(_INDICATOR_SID) and _field(
            profile, _INDICATOR_SID, _INDICATOR_FIELD
        ) is not None:
            specs.append(
                _switch_spec(
                    _INDICATOR_SID,
                    _INDICATOR_FIELD,
                    key="indicator_flash",
                    name="指示灯闪烁",
                )
            )

        # --- sensitivity selects --------------------------------------------
        if context.has_service(_SENSITIVITY_SID):
            if _field(profile, _SENSITIVITY_SID, _SENS_GEAR_FIELD) is not None:
                specs.append(
                    _select_spec(
                        _SENSITIVITY_SID,
                        _SENS_GEAR_FIELD,
                        key="trigger_sensitivity",
                        name="触发有人灵敏度",
                        options=_GEAR_OPTIONS,
                    )
                )
            if _field(profile, _SENSITIVITY_SID, _SENS_RADAR_FIELD) is not None:
                specs.append(
                    _select_spec(
                        _SENSITIVITY_SID,
                        _SENS_RADAR_FIELD,
                        key="maintain_sensitivity",
                        name="维持有人灵敏度",
                        options=_GEAR_OPTIONS,
                    )
                )

        # --- detection parameters -------------------------------------------
        if context.has_service(_DETECTION_SID):
            if _field(profile, _DETECTION_SID, _CFG_MODE_FIELD) is not None:
                specs.append(
                    _select_spec(
                        _DETECTION_SID,
                        _CFG_MODE_FIELD,
                        key="cfg_mode",
                        name="配置模式",
                        options=_CFG_MODE_OPTIONS,
                    )
                )
            trigger_field = _field(profile, _DETECTION_SID, _TRIGGER_FIELD)
            trigger_range = _profile_range(trigger_field)
            if trigger_range is not None:
                specs.append(
                    _distance_number_spec(
                        _DETECTION_SID,
                        _TRIGGER_FIELD,
                        key="trigger_distance",
                        name="触发有人检测距离",
                        field=trigger_field,
                        value_range=trigger_range,
                    )
                )
            detection_field = _field(profile, _DETECTION_SID, _DETECTION_FIELD)
            detection_range = _profile_range(detection_field)
            if detection_range is not None:
                specs.append(
                    _distance_number_spec(
                        _DETECTION_SID,
                        _DETECTION_FIELD,
                        key="maintain_range",
                        name="维持有人感应范围",
                        field=detection_field,
                        value_range=detection_range,
                    )
                )

        # --- hold time (seconds) ---------------------------------------------
        if context.has_service(_DELAY_SID) and _field(
            profile, _DELAY_SID, _DELAY_FIELD
        ) is not None:
            def hold_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "native_value": _number(device.value(_DELAY_SID, _DELAY_FIELD))
                }

            async def hold_set_value(
                context: DeviceContext,
                data: Mapping[str, Any],
            ) -> None:
                field = _field(context.profile or {}, _DELAY_SID, _DELAY_FIELD)
                if field is None:
                    raise ValueError("2RJB delayTime.time is missing from the Profile")
                await context.async_send_service(
                    _DELAY_SID,
                    {_DELAY_FIELD: _clamp_to_profile(data.get("value"), field)},
                )

            hold_field = _field(profile, _DELAY_SID, _DELAY_FIELD)
            hold_range = _profile_range(hold_field)
            if hold_range is not None:
                specs.append(
                    EntitySpec(
                        platform="number",
                        key="hold_time",
                        name="无人检测最短时间",
                        state=hold_state,
                        metadata={
                            "min": hold_range[0],
                            "max": hold_range[1],
                            "step": _profile_step(hold_field) or 1,
                            # Vendor picker titles are "<n> 秒".
                            "unit": "s",
                        },
                        actions={"set_value": hold_set_value},
                    )
                )

        # --- noise management -------------------------------------------------
        if context.has_service(_NOISE_SID) and _field(
            profile, _NOISE_SID, _NOISE_AUTO_FIELD
        ) is not None:
            specs.append(
                _switch_spec(
                    _NOISE_SID,
                    _NOISE_AUTO_FIELD,
                    key="auto_anti_interference",
                    name="自动抗干扰",
                )
            )

        # --- action buttons -----------------------------------------------------
        if context.has_service(_ACTION_SID):
            if _field(profile, _ACTION_SID, _ACTION_FIELD) is not None:
                specs.append(
                    _button_spec(
                        _ACTION_SID,
                        key="reset_absence",
                        name="重置无人状态",
                        action_value=_ACTION_RESET_ABSENCE,
                    )
                )
                specs.append(
                    _button_spec(
                        _ACTION_SID,
                        key="exclude_interference",
                        name="排除干扰",
                        action_value=_ACTION_EXCLUDE_INTERFERENCE,
                    )
                )

        return tuple(specs)


ADAPTER = Product2rjbAdapter()
