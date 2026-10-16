"""User-contributed protocol for Huawei product ZG13 (调光调色智能灯).

设备类型: 智能照明 (华为全屋智能, deviceTypeId A1B, protocolType VirtualDevice)
本适配器暴露一个 light：开关、亮度、色温。

依据华为公开的产品 Profile (ZG13.json):
   switch.on                  bool RW  0=关 1=开
   brightness.brightness      int  RW  1~100, step 1
   cct.colorTemperature       int  RW  2700~6500 (K), step 100

未纳入:
   fadeTime.value (渐变时间，Profile 中不可写且不上报)、relBrightness.* (旋钮
   相对调光的输入事件，非日常控制项)。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext


def _field(
    profile: Mapping[str, Any],
    sid: str,
    name: str,
) -> Mapping[str, Any] | None:
    for service in profile.get("services", ()):
        if not isinstance(service, Mapping) or service.get("serviceId") != sid:
            continue
        for field in service.get("characteristics", ()):
            if (
                isinstance(field, Mapping)
                and field.get("characteristicName") == name
            ):
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
        if value.casefold() in {"1", "true", "on"}:
            return True
        if value.casefold() in {"0", "false", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _range(field: Mapping[str, Any]) -> tuple[int, int] | None:
    low = _number(field.get("min"))
    high = _number(field.get("max"))
    if low is None or high is None or high <= low:
        return None
    return int(low), int(high)


def _snap(value: float, field: Mapping[str, Any]) -> int:
    """Clamp a value to the Profile range and align it to the Profile step."""

    low, high = _range(field) or (0, 0)
    value = min(max(value, low), high)
    step = _number(field.get("step"))
    if step and step > 0:
        value = low + round((value - low) / step) * step
        value = min(max(value, low), high)
    return int(round(value))


class ProductZG13Adapter:
    """Keep all ZG13 entity and command choices in this file."""

    prod_id = "ZG13"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None or not all(
            context.has_service(sid) for sid in ("switch", "brightness", "cct")
        ):
            return ()

        brightness_field = _field(profile, "brightness", "brightness")
        cct_field = _field(profile, "cct", "colorTemperature")
        if brightness_field is None or cct_field is None:
            return ()
        brightness_range = _range(brightness_field)
        cct_range = _range(cct_field)
        if brightness_range is None or cct_range is None:
            return ()
        brightness_max = brightness_range[1]

        def light_state(device: DeviceContext) -> Mapping[str, Any]:
            raw = _number(device.value("brightness", "brightness"))
            brightness = (
                min(max(round(raw * 255 / brightness_max), 1), 255)
                if raw is not None
                else None
            )
            kelvin = _number(device.value("cct", "colorTemperature"))
            return {
                "is_on": _bool(device.value("switch", "on")),
                "brightness": brightness,
                "color_temp_kelvin": int(kelvin) if kelvin is not None else None,
                "color_mode": "color_temp",
            }

        async def turn_on(device: DeviceContext, data: Mapping[str, Any]) -> None:
            await device.async_send_service("switch", {"on": 1})
            if data.get("brightness") is not None:
                ha_value = _number(data["brightness"])
                if ha_value is None:
                    raise ValueError("brightness must be a number")
                await device.async_send_service(
                    "brightness",
                    {
                        "brightness": _snap(
                            ha_value * brightness_max / 255,
                            brightness_field,
                        )
                    },
                )
            if data.get("color_temp_kelvin") is not None:
                kelvin = _number(data["color_temp_kelvin"])
                if kelvin is None:
                    raise ValueError("color_temp_kelvin must be a number")
                await device.async_send_service(
                    "cct",
                    {"colorTemperature": _snap(kelvin, cct_field)},
                )

        async def turn_off(device: DeviceContext, _data: Mapping[str, Any]) -> None:
            await device.async_send_service("switch", {"on": 0})

        return (
            EntitySpec(
                platform="light",
                key="light",
                name=None,
                state=light_state,
                metadata={
                    "supported_color_modes": {"color_temp"},
                    "min_color_temp_kelvin": cct_range[0],
                    "max_color_temp_kelvin": cct_range[1],
                },
                actions={"turn_on": turn_on, "turn_off": turn_off},
            ),
        )


ADAPTER = ProductZG13Adapter()
