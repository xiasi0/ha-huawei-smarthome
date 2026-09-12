"""User-contributed protocol for Huawei product 113E (豪恩 中控主机 / 网关).

设备类型: 中控主机 (Bridge), 型号 T2
用途: 作为 Zigbee 子设备网关; 内置夜灯可控制.
核心服务(本次使用的):
   light.lightEnable    enum RW (0=夜灯关, 1=夜灯开)
   light.brightness     int  RW (0-100 亮度)
   light.inductionEnable enum RW (0=关闭, 1=开启 感应)

本适配器暴露一个 Home Assistant ``light`` 实体(夜灯), 支持 开关/亮度.
其余为网关子设备管理/报警器/门铃/语音留言, 需要私有配置, 暂不映射.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_BRIGHTNESS_DIV = 100
_BRIGHTNESS_MAX = 255


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
    await context.async_send_service("light", {"lightEnable": 1})
    brightness = data.get("brightness")
    if brightness is not None:
        await context.async_send_service(
            "light", {"brightness": _ha_to_dev_brightness(brightness)}
        )


async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("light", {"lightEnable": 0})


class Product113EAdapter:
    """113E 豪恩网关适配器：夜灯 light 实体。"""

    prod_id = "113E"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service("light"):
            return ()

        def light_state(device: DeviceContext) -> Mapping[str, Any]:
            brightness = _dev_to_ha_brightness(
                _as_int(device.value("light", "brightness"))
            )
            return {
                "is_on": _as_bool(device.value("light", "lightEnable")),
                "brightness": brightness,
                "color_mode": "brightness" if brightness is not None else "onoff",
            }

        return (
            EntitySpec(
                platform="light",
                key="nightlight",
                name="夜灯",
                state=light_state,
                metadata={"supported_color_modes": ["brightness"]},
                actions={
                    "turn_on": _turn_on,
                    "turn_off": _turn_off,
                },
            ),
        )


ADAPTER = Product113EAdapter()


