"""User-contributed protocol for Huawei product 21G6 (合一电器 FL-12136DRRa 超广角自然风风扇).

Profile: switch.{on RW} / mode.{mode RW 正常风/睡眠风/自然风} / fan.{angle RW, speed RW}
         / endTime.{time RW} / timer / update / netInfo
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

# Fan mode enum (服务 mode).
_MODE_OPTIONS = (
    (0, "正常风"),
    (1, "睡眠风"),
    (2, "自然风"),
)

# Oscillation angle enum (服务 fan.angle).
_OSCILLATION_OPTIONS = (
    (0, "关摆头"),
    (30, "30°"),
    (60, "60°"),
    (90, "90°"),
    (120, "120°"),
)

# speed 字段用于百分比控制，映射到 HA fan percentage.
_FAN_SPEED_SID = "fan"
_FAN_SPEED_FIELD = "speed"

# 最大速度值，用于计算百分比。从 Profile 读取。
_SPEED_MIN = 0
_SPEED_MAX = 100


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
    number = _number(value)
    value_range = _profile_range(field)
    if number is None or value_range is None:
        raise ValueError("21G6 Profile range is incomplete")
    minimum, maximum = value_range
    number = min(max(float(number), minimum), maximum)
    step = _profile_step(field)
    if step is not None:
        number = minimum + round((number - minimum) / step) * step
        number = min(max(number, minimum), maximum)
    if str(field.get("characteristicType") or "").casefold() in {"int", "integer"}:
        return int(round(number))
    return int(number) if float(number).is_integer() else number


def _speed_to_percentage(value: Any, field: Mapping[str, Any]) -> int | None:
    """Convert device speed (0-100) to HA percentage (0-100)."""
    number = _number(value)
    if number is None:
        return None
    value_range = _profile_range(field)
    if value_range is None:
        return int(number)
    minimum, maximum = value_range
    number = min(max(float(number), minimum), maximum)
    if maximum == minimum:
        return 0
    return round((number - minimum) * 100 / (maximum - minimum))


def _percentage_to_speed(value: Any, field: Mapping[str, Any]) -> int:
    """Convert HA percentage (0-100) to device speed."""
    number = _number(value)
    if number is None:
        raise ValueError("21G6 fan percentage must be a number")
    value_range = _profile_range(field)
    if value_range is None:
        return int(number)
    minimum, maximum = value_range
    number = min(max(float(number), 0), 100)
    speed = minimum + number * (maximum - minimum) / 100
    step = _profile_step(field)
    if step is not None:
        speed = minimum + round((speed - minimum) / step) * step
    return int(round(min(max(speed, minimum), maximum)))


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


def _oscillation_angle_to_bool(value: Any) -> bool | None:
    """Convert angle value to oscillation boolean (angle > 0 means oscillating)."""
    number = _number(value)
    if number is None:
        return None
    return number > 0


async def _fan_turn_on(context: DeviceContext, data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 1})
    percentage = data.get("percentage")
    if percentage is not None and _number(percentage) not in (None, 0):
        speed_field = _field(context.profile or {}, _FAN_SPEED_SID, _FAN_SPEED_FIELD)
        if speed_field is not None:
            await context.async_send_service(
                _FAN_SPEED_SID,
                {_FAN_SPEED_FIELD: _percentage_to_speed(percentage, speed_field)},
            )


async def _fan_turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 0})


async def _fan_set_percentage(context: DeviceContext, data: Mapping[str, Any]) -> None:
    percentage = data.get("percentage")
    if percentage is None or _number(percentage) in (None, 0):
        await context.async_send_service("switch", {"on": 0})
        return
    speed_field = _field(context.profile or {}, _FAN_SPEED_SID, _FAN_SPEED_FIELD)
    if speed_field is not None:
        await context.async_send_service(
            _FAN_SPEED_SID,
            {_FAN_SPEED_FIELD: _percentage_to_speed(percentage, speed_field)},
        )


async def _fan_oscillate(context: DeviceContext, data: Mapping[str, Any]) -> None:
    oscillating = data.get("oscillating")
    if oscillating:
        # 开启摆头，默认 90°
        await context.async_send_service("fan", {"angle": 90})
    else:
        await context.async_send_service("fan", {"angle": 0})


async def _mode_select_option(context: DeviceContext, data: Mapping[str, Any]) -> None:
    value = _enum_value(data.get("option"), _MODE_OPTIONS)
    await context.async_send_service("mode", {"mode": value})


class Product21G6Adapter:
    """21G6 合一电器 FL-12136DRRa 超广角自然风风扇适配器。"""

    prod_id = "21G6"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        specs: list[EntitySpec] = []

        # --- fan (percentage + oscillation) ---
        if context.has_service("switch") and context.has_service(_FAN_SPEED_SID):
            speed_field = _field(profile, _FAN_SPEED_SID, _FAN_SPEED_FIELD)
            if speed_field is not None:

                def fan_state(device: DeviceContext) -> Mapping[str, Any]:
                    return {
                        "is_on": _bool(device.value("switch", "on")),
                        "percentage": _speed_to_percentage(
                            device.value(_FAN_SPEED_SID, _FAN_SPEED_FIELD),
                            speed_field,
                        ),
                        "oscillating": _oscillation_angle_to_bool(
                            device.value("fan", "angle"),
                        ),
                    }

                speed_min = _number(speed_field.get("min")) or 0
                speed_max = _number(speed_field.get("max")) or 100
                speed_count = int(speed_max - speed_min)

                specs.append(
                    EntitySpec(
                        platform="fan",
                        key="fan",
                        name="风扇",
                        state=fan_state,
                        metadata={
                            "supports_percentage": True,
                            "supports_oscillation": True,
                            "speed_count": speed_count,
                            "percentage_step": max(1, round(100 / speed_count)),
                        },
                        actions={
                            "turn_on": _fan_turn_on,
                            "turn_off": _fan_turn_off,
                            "set_percentage": _fan_set_percentage,
                            "oscillate": _fan_oscillate,
                        },
                    )
                )

        # --- fan mode select ---
        if context.has_service("mode") and _field(profile, "mode", "mode") is not None:

            def mode_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "current_option": _enum_label(
                        device.value("mode", "mode"),
                        _MODE_OPTIONS,
                    )
                }

            specs.append(
                EntitySpec(
                    platform="select",
                    key="fan_mode",
                    name="风扇模式",
                    state=mode_state,
                    metadata={
                        "options": [label for _, label in _MODE_OPTIONS],
                    },
                    actions={"select_option": _mode_select_option},
                )
            )

        return tuple(specs)


ADAPTER = Product21G6Adapter()
