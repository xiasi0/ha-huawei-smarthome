"""Product adapter for the MC3 PLUS HVAC gateway (2JMN, 暖通网关, WiFi).

Profile: 20+ gateway-management services (device/group/protocol lists,
backup, ports, 485, vrv, logReport, offlineOta, operation ...) /
faultDetection.{code 0=正常/1=异常, status 0=无异常/1=继电器MCU异常/2=空调
MCU异常/3=485端口异常/4=空调端口异常} / reboot.{rebootCapability, action
0=重启本设备/1=重启所有设备/2=批量重启网关+子设备/3=批量重启子设备,
devList} / connectMode.connect enum(0=网线, 1=WIFI, 2=PLC) / netInfo.

H5 evidence (h5_001 "暖通网关" webpack bundle):

- reboot: the only gateway dispatch is ``{reboot:{action:0}}`` (重启网关
  button, restartResult callback + 60 s timeout).  action 0 = 重启本设备
  per the Profile — a self-reboot, safe to expose as a button.  Values
  1/2/3 (all/batch) are never sent and need devList → not exposed.
- faultDetection: report handler stores faultStatus/faultCode — display
  only; NOTE the reversed roles on this product: code is the simple
  0/1 abnormal flag (→ binary_sensor) and status carries the specific
  fault kind (→ sensor).
- connectMode: report handler + UI rendering 网线连接/WIFI连接/PLC连接 →
  diagnostic sensor.
- Everything else — device/group/protocol list CRUD, backup, ports,
  485, vrvProtocol, automaticGroup, offlineOta, operation, logReport —
  is gateway configuration managed through dedicated app pages with
  multi-step payloads; none of it maps to simple HA entities (宁可不出).
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


def _flag_value(raw: Any) -> bool | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    try:
        number = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if number == 1:
        return True
    if number == 0:
        return False
    return None


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


def _net_info_entities(context: DeviceContext, profile: Any) -> list[EntitySpec]:
    if not context.has_service("netInfo"):
        return []
    entities: list[EntitySpec] = []
    if _field(profile, "netInfo", "RSSI") is not None:
        entities.append(
            EntitySpec(
                platform="sensor",
                key="wifi_rssi",
                name="信号强度",
                state=lambda ctx: {"native_value": _number(ctx.value("netInfo", "RSSI"))},
                metadata={"state_class": "measurement"},
            )
        )
    if _field(profile, "netInfo", "intensity") is not None:
        entities.append(
            EntitySpec(
                platform="sensor",
                key="wifi_level",
                name="信号等级",
                state=lambda ctx: {"native_value": _enum_text(ctx, "netInfo", "intensity")},
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
                state=lambda ctx, _n=char_name: {"native_value": _text(ctx.value("netInfo", _n))},
                metadata={},
            )
        )
    return entities


class Product2JMNAdapter:
    """MC3 PLUS HVAC gateway (2JMN) — diagnostics + gateway self-reboot."""

    prod_id = "2JMN"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        entities: list[EntitySpec] = []

        # Gateway self-reboot: H5 重启网关 button → {reboot:{action:0}}.
        if context.has_service("reboot") and _field(profile, "reboot", "action") is not None:
            async def reboot(ctx: DeviceContext, data: Mapping[str, Any]) -> None:
                del data
                await ctx.async_send_service("reboot", {"action": 0})

            entities.append(
                EntitySpec(
                    platform="button",
                    key="gateway_reboot",
                    name="重启网关",
                    state=lambda ctx: {},
                    metadata={},
                    actions={"press": reboot},
                )
            )

        # Fault kind: status 0=无异常 / 1=继电器MCU异常 / 2=空调MCU异常 /
        # 3=485端口异常 / 4=空调端口异常 (reversed roles vs. sibling devices).
        if context.has_service("faultDetection"):
            if _field(profile, "faultDetection", "status") is not None:
                entities.append(
                    EntitySpec(
                        platform="sensor",
                        key="fault_state",
                        name="故障状态",
                        state=lambda ctx: {
                            "native_value": _enum_text(ctx, "faultDetection", "status")
                        },
                        metadata={},
                    )
                )
            if _field(profile, "faultDetection", "code") is not None:
                entities.append(
                    EntitySpec(
                        platform="binary_sensor",
                        key="fault_problem",
                        name="故障告警",
                        # code enum: 0=正常, 1=异常
                        state=lambda ctx: {
                            "is_on": _flag_value(ctx.value("faultDetection", "code"))
                        },
                        metadata={"device_class": "problem"},
                    )
                )

        if context.has_service("connectMode") and _field(
            profile, "connectMode", "connect"
        ) is not None:
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="connect_mode",
                    name="连接方式",
                    state=lambda ctx: {
                        "native_value": _enum_text(ctx, "connectMode", "connect")
                    },
                    metadata={},
                )
            )

        entities.extend(_net_info_entities(context, profile))
        return tuple(entities)


ADAPTER = Product2JMNAdapter()
