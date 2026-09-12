"""Product adapter for the LDN-C01 smart host SE (ZF0C, 华为全屋智能 智能主机SE).

Profile: switch.on enum(0=关闭自动扫描添加, 1=开启自动扫描添加) /
clickedScene.id W / devOta / netInfo.

H5 evidence (h5_001 "通用场景" scene-management bundle):

- The shipped H5 is the host's SCENE page.  The only device dispatch is
  scene execution: ``{clickedScene:{<sceneIdKey>: <id>, ctrlSrc: 6}}``
  (executeManualSceneById) — scene ids are runtime data, so no static
  entity can be built for them.
- The switch.on 自动扫描添加 toggle and devOta have ZERO dispatch sites
  in this bundle (the device card lives in the native app), so per the
  evidence rules nothing is exposed for them.
- netInfo (RSSI/intensity/SSID/IP/BSSID) is display-only reporting →
  diagnostic sensors.

Result: diagnostics only.  This is deliberately minimal (宁可不出) — the
host SE is an infrastructure device whose control surface is the native
app.
"""

from __future__ import annotations

from typing import Any, Mapping

from .api import EntitySpec
from .context import DeviceContext


def _service(profile: Any, sid: str) -> Any:
    if profile is None:
        return None
    for service in profile.get("services", ()):
        if service.get("serviceId") == sid:
            return service
    return None


def _field(profile: Any, sid: str, name: str) -> Mapping[str, Any] | None:
    service = _service(profile, sid)
    if service is None:
        return None
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


def _enum_text(context: DeviceContext, sid: str, name: str) -> str | None:
    raw = context.value(sid, name)
    if raw is None or isinstance(raw, bool):
        return None
    try:
        key = str(int(str(raw).strip()))
    except (TypeError, ValueError):
        return _text(raw)
    field = _field(context.profile, sid, name)
    if field is None:
        return None
    for option in field.get("enumList", ()) or ():
        if str(option.get("enumVal")) == key:
            return str(option.get("descCh") or option.get("enumVal"))
    return None


class ProductZF0CAdapter:
    """LDN-C01 smart host SE (ZF0C) — diagnostics only."""

    prod_id = "ZF0C"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        entities: list[EntitySpec] = []

        if context.has_service("netInfo"):
            if _field(profile, "netInfo", "RSSI") is not None:
                entities.append(
                    EntitySpec(
                        platform="sensor",
                        key="wifi_rssi",
                        name="信号强度",
                        state=lambda ctx: {
                            "native_value": _number(ctx.value("netInfo", "RSSI"))
                        },
                        metadata={"state_class": "measurement"},
                    )
                )
            if _field(profile, "netInfo", "intensity") is not None:
                entities.append(
                    EntitySpec(
                        platform="sensor",
                        key="wifi_level",
                        name="信号等级",
                        state=lambda ctx: {
                            "native_value": _enum_text(ctx, "netInfo", "intensity")
                        },
                        metadata={},
                    )
                )
            for char_name, key, label in (
                ("SSID", "wifi_ssid", "Wi-Fi 名称"),
                ("IP", "wifi_ip", "IP 地址"),
                ("BSSID", "wifi_bssid", "BSSID"),
            ):
                if _field(profile, "netInfo", char_name) is None:
                    continue
                entities.append(
                    EntitySpec(
                        platform="sensor",
                        key=key,
                        name=label,
                        state=lambda ctx, _n=char_name: {
                            "native_value": _text(ctx.value("netInfo", _n))
                        },
                        metadata={},
                    )
                )

        return tuple(entities)


ADAPTER = ProductZF0CAdapter()
