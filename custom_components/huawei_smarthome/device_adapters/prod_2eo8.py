"""User-contributed protocol for Huawei product 2EO8 (智能照明 / 灯带).

设备类型: 智能照明 (Lamp), 万得彩 HC-XD-068
核心服务:
   switch.on            bool RW (1=开, 0=关)
   brightness.brightness int RW  1-100 亮度
   cct.colorTemperature   int RW  2000-6500 色温(开尔文)

本适配器暴露一个 Home Assistant ``light`` 实体, 支持 开关/亮度/色温.
亮度按设备 1-100 <-> HA 0-255 换算.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_BRIGHTNESS_DIV = 100
_BRIGHTNESS_MAX = 255
_CCT_MIN = 2000
_CCT_MAX = 6500


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, str):
        try:
            return int(round(float(value.strip())))
        except (TypeError, ValueError):
            return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool | None:
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


def _dev_to_ha_brightness(value: int | None) -> int | None:
    if value is None:
        return None
    return max(0, min(_BRIGHTNESS_MAX, round(value / _BRIGHTNESS_DIV * _BRIGHTNESS_MAX)))


def _ha_to_dev_brightness(value: Any) -> int:
    raw = max(0.0, min(float(value), _BRIGHTNESS_MAX))
    return max(1, round(raw / _BRIGHTNESS_MAX * _BRIGHTNESS_DIV))


async def _turn_on(context: DeviceContext, data: Mapping[str, Any]) -> None:
    body = {"on": 1}
    await context.async_send_service("switch", body)
    brightness = data.get("brightness")
    if brightness is not None:
        await context.async_send_service(
            "brightness", {"brightness": _ha_to_dev_brightness(brightness)}
        )
    color_temp = data.get("color_temp_kelvin")
    if color_temp is not None:
        cct = max(_CCT_MIN, min(_CCT_MAX, int(round(float(color_temp)))))
        await context.async_send_service("cct", {"colorTemperature": cct})


async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 0})


class Product2EO8Adapter:
    """2EO8 灯带适配器：一个 light 实体 (开关/亮度/色温)。"""

    prod_id = "2EO8"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service("switch"):
            return ()

        def light_state(device: DeviceContext) -> Mapping[str, Any]:
            brightness = _dev_to_ha_brightness(
                _as_int(device.value("brightness", "brightness"))
            )
            cct = _as_int(device.value("cct", "colorTemperature"))
            return {
                "is_on": _as_bool(device.value("switch", "on")),
                "brightness": brightness,
                "color_temp_kelvin": cct,
                "color_mode": "color_temp" if cct is not None else (brightness is not None and "brightness" or "onoff"),
            }

        return (
            EntitySpec(
                platform="light",
                key="light",
                name=None,
                state=light_state,
                metadata={
                    "supported_color_modes": ["color_temp"],
                    "min_color_temp_kelvin": _CCT_MIN,
                    "max_color_temp_kelvin": _CCT_MAX,
                },
                actions={
                    "turn_on": _turn_on,
                    "turn_off": _turn_off,
                },
            ),
        )


ADAPTER = Product2EO8Adapter()


