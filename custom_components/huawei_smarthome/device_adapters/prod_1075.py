"""User-contributed protocol for Huawei product 1075 (水母云 IP65 智能LED筒灯).

设备类型: 智能照明 (汇唐光电 RLO-4W465, WiFi)
核心服务:
   switch.on        bool RW  电源开关
   brightness.brightness int RW  13-255 (与 HA 1-255 基本同量程, 直通)
   colourMode.colourMode int RW  0=RGB/HSB, 1=CCT
   colour.red/green/blue   int RW  0-255
   cct.colorTemperature    int RW  2700-6500 K
其余服务 (lightMode 场景/唤醒/定时/倒计时/netInfo/update) 暂不映射.

本适配器暴露一个 Home Assistant ``light`` 实体:
   开关 + 亮度 + RGB 颜色 + 色温, supported_color_modes = [rgb, color_temp].
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_BRIGHTNESS_MIN = 13
_BRIGHTNESS_MAX = 255
_CCT_MIN = 2700
_CCT_MAX = 6500


def _is_on(value: Any) -> bool | None:
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


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _light_state(device: DeviceContext) -> Mapping[str, Any]:
    rgb = tuple(
        channel
        for channel in (
            _as_int(device.value("colour", name))
            for name in ("red", "green", "blue")
        )
    )
    state: dict[str, Any] = {
        "is_on": _is_on(device.value("switch", "on")),
        "brightness": _as_int(device.value("brightness", "brightness")),
    }
    # colourMode: 0=RGB/HSB, 1=CCT
    mode = _as_int(device.value("colourMode", "colourMode"))
    if mode == 1:
        state["color_mode"] = "color_temp"
        cct = _as_int(device.value("cct", "colorTemperature"))
        if cct is not None:
            state["color_temp_kelvin"] = _clamp(cct, _CCT_MIN, _CCT_MAX)
    elif mode == 0 and all(channel is not None for channel in rgb):
        state["color_mode"] = "rgb"
        state["rgb_color"] = rgb
    return state


async def _turn_on(context: DeviceContext, data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 1})

    brightness = _as_int(data.get("brightness"))
    if brightness is not None:
        await context.async_send_service(
            "brightness",
            {"brightness": _clamp(brightness, _BRIGHTNESS_MIN, _BRIGHTNESS_MAX)},
        )

    rgb = data.get("rgb_color")
    kelvin = _as_int(data.get("color_temp_kelvin"))
    if rgb is not None and len(rgb) == 3:
        await context.async_send_service("colourMode", {"colourMode": 0})
        await context.async_send_service(
            "colour",
            {
                "red": _clamp(_as_int(rgb[0]) or 0, 0, 255),
                "green": _clamp(_as_int(rgb[1]) or 0, 0, 255),
                "blue": _clamp(_as_int(rgb[2]) or 0, 0, 255),
            },
        )
    elif kelvin is not None:
        await context.async_send_service("colourMode", {"colourMode": 1})
        await context.async_send_service(
            "cct", {"colorTemperature": _clamp(kelvin, _CCT_MIN, _CCT_MAX)}
        )


async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 0})


class Product1075Adapter:
    """1075 筒灯适配器: 单 light 实体 (开关/亮度/RGB/色温)."""

    prod_id = "1075"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service("switch"):
            return ()

        return (
            EntitySpec(
                platform="light",
                key="light",
                name=None,
                state=_light_state,
                metadata={
                    "supported_color_modes": ["rgb", "color_temp"],
                    "min_color_temp_kelvin": _CCT_MIN,
                    "max_color_temp_kelvin": _CCT_MAX,
                },
                actions={
                    "turn_on": _turn_on,
                    "turn_off": _turn_off,
                },
            ),
        )


ADAPTER = Product1075Adapter()
