"""Product adapter for the MIR-SM01-PLC smoke alarm (2MXF, PLC).

Profile: smokeSensor.level enum(1=正常, 2=告警) / silencer.on bool(消音) /
alarm.alarm bool(超标告警) / selfCheck.on bool(1=开始自检, 0=完成自检) /
commonFaultDetection.{status, code 0正常/1探头异常/2设备被拆除/99设备通讯异常}
/ netInfo / update.

H5 evidence (h5_001 "ordinary SDK" page):

- silencer and selfCheck are rendered as GeneralBoolIconCard toggles whose
  onclick forwards ``{sid:{on:value}}`` through
  ``SmartHomeUI.device.setDeviceInfo`` — the only dispatch sites.
  data.js carries the semantics: silencer tip "静音 90s，若 90s 后仍处于
  报警状态蜂鸣器继续鸣叫"; selfCheck label 功能自检/安全自检 with tip
  "主要用于对设备进行故障自检，并不包括烟雾状态的检测" (the device
  reports on=0 完成自检 when done, so the toggle mirrors the H5 card).
- smokeSensor.level / alarm.alarm / commonFaultDetection / netInfo are
  display-only bindings.

Not exposed (宁可不出):
- alarm.alarm (超标告警) duplicates smokeSensor.level for this device
  (the smoke enum has exactly the two states 正常/告警 the alarm bool
  represents) — one binary_sensor is enough.
- update (OTA, app-managed).
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


def _flag_switch(
    key: str,
    name: str,
    sid: str,
) -> EntitySpec:
    async def turn(ctx: DeviceContext, data: Mapping[str, Any]) -> None:
        del data
        await ctx.async_send_service(sid, {"on": 1})

    async def turn_off(ctx: DeviceContext, data: Mapping[str, Any]) -> None:
        del data
        await ctx.async_send_service(sid, {"on": 0})

    return EntitySpec(
        platform="switch",
        key=key,
        name=name,
        state=lambda ctx: {"is_on": _flag_value(ctx.value(sid, "on"))},
        metadata={},
        actions={"turn_on": turn, "turn_off": turn_off},
    )


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


class Product2MXFAdapter:
    """MIR-SM01-PLC smoke alarm (2MXF)."""

    prod_id = "2MXF"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        entities: list[EntitySpec] = []

        # Smoke detection: 1=正常, 2=告警 → HA smoke class (on = alarm).
        if context.has_service("smokeSensor") and _field(
            profile, "smokeSensor", "level"
        ) is not None:
            def smoke_state(ctx: DeviceContext) -> Mapping[str, Any]:
                raw = ctx.value("smokeSensor", "level")
                if raw is None or isinstance(raw, bool):
                    return {"is_on": None}
                try:
                    number = int(str(raw).strip())
                except (TypeError, ValueError):
                    return {"is_on": None}
                # Profile enum: 1=正常, 2=告警; unknown values stay unknown
                if number not in (1, 2):
                    return {"is_on": None}
                return {"is_on": number == 2}

            entities.append(
                EntitySpec(
                    platform="binary_sensor",
                    key="smoke_alarm",
                    name="烟雾告警",
                    state=smoke_state,
                    metadata={"device_class": "smoke"},
                )
            )

        if context.has_service("silencer") and _field(profile, "silencer", "on") is not None:
            entities.append(_flag_switch("silencer", "消音", "silencer"))

        if context.has_service("selfCheck") and _field(profile, "selfCheck", "on") is not None:
            entities.append(_flag_switch("self_check", "功能自检", "selfCheck"))

        if context.has_service("commonFaultDetection"):
            if _field(profile, "commonFaultDetection", "code") is not None:
                entities.append(
                    EntitySpec(
                        platform="sensor",
                        key="fault_state",
                        name="故障状态",
                        state=lambda ctx: {
                            "native_value": _enum_text(
                                ctx, "commonFaultDetection", "code"
                            )
                        },
                        metadata={},
                    )
                )
            if _field(profile, "commonFaultDetection", "status") is not None:
                entities.append(
                    EntitySpec(
                        platform="binary_sensor",
                        key="fault_problem",
                        name="故障告警",
                        state=lambda ctx: {
                            "is_on": _flag_value(
                                ctx.value("commonFaultDetection", "status")
                            )
                        },
                        metadata={"device_class": "problem"},
                    )
                )

        entities.extend(_net_info_entities(context, profile))
        return tuple(entities)


ADAPTER = Product2MXFAdapter()
