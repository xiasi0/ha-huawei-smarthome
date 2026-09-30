"""User-contributed protocol for Huawei product A0OK (酷宅科技 智能三通道插座).

设备类型: 智能插排 (MultiSocket)
制造商: 酷宅科技, 型号 Smart socket, 协议 WiFi

核心服务:
   switch.on      bool RW 总开关
   switchN.on     bool RW (N=1..3) 分路开关
   switchN.name   string RW 插口名称 (maxLength 16)
   netInfo / update  只读上报

本适配器暴露:
   * 4 个 Home Assistant ``switch``: 总开关 + 开关1..开关3
     （与同系列 A0OM「四通道插座」适配器保持一致的命名）
   * 2 个诊断 ``sensor``: Wi-Fi 信号强度 (netInfo.RSSI)、固件版本 (update.version)

说明: A0OK 的 H5 资源 (h5_001) 返回 403，取不到官方下发证据，因此开关按
Profile 的 RW bool 语义实现（与 A0OM、以及其它酷宅插座一致）。分路名称
(``switchN.name``) 属于 App 侧个性化设置，未映射为实体。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_SWITCH_SERVICES = [
    ("switch", "总开关"),
    ("switch1", "开关1"),
    ("switch2", "开关2"),
    ("switch3", "开关3"),
]


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


def _field(profile: Any, sid: str, name: str) -> Mapping[str, Any] | None:
    if profile is None:
        return None
    for service in profile.get("services", ()):
        if service.get("serviceId") != sid:
            continue
        for characteristic in service.get("characteristics", ()):
            if characteristic.get("characteristicName") == name:
                return characteristic
    return None


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        return value or None
    return str(value)


class ProductA0OKAdapter:
    """A0OK 三路智能插排适配器。"""

    prod_id = "A0OK"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None or not context.has_service("switch"):
            return ()

        def _switch_spec(sid: str, label: str) -> EntitySpec:
            def state(device: DeviceContext) -> Mapping[str, Any]:
                return {"is_on": _as_bool(device.value(sid, "on"))}

            async def turn_on(device: DeviceContext, _data: Mapping[str, Any]) -> None:
                await device.async_send_service(sid, {"on": 1})

            async def turn_off(device: DeviceContext, _data: Mapping[str, Any]) -> None:
                await device.async_send_service(sid, {"on": 0})

            return EntitySpec(
                platform="switch",
                key=sid,
                name=label,
                state=state,
                actions={"turn_on": turn_on, "turn_off": turn_off},
            )

        entities: list[EntitySpec] = [
            _switch_spec(sid, label)
            for sid, label in _SWITCH_SERVICES
            if context.has_service(sid)
        ]

        if _field(profile, "netInfo", "RSSI") is not None:
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="wifi_rssi",
                    name="Wi-Fi 信号",
                    state=lambda ctx: {
                        "native_value": _number(ctx.value("netInfo", "RSSI"))
                    },
                    metadata={
                        "unit": "dBm",
                        "device_class": "signal_strength",
                        "state_class": "measurement",
                        "entity_category": "diagnostic",
                    },
                )
            )

        if _field(profile, "update", "version") is not None:
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="firmware_version",
                    name="固件版本",
                    state=lambda ctx: {
                        "native_value": _text(ctx.value("update", "version"))
                    },
                    metadata={"entity_category": "diagnostic"},
                )
            )

        return tuple(entities)


ADAPTER = ProductA0OKAdapter()
