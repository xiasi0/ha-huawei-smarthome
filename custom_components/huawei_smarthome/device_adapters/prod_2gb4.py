"""Product adapter for the MIR-IR100 PIR + luminance sensor (2GB4, Mesh).

Profile: luminance.{level enum(1微光..4强光), current int 0..1000 lux step 10}
/ pir.status enum(0=无人, 1=有人) / battery.{level, alarm} /
commonFaultDetection.{status, code} / netInfo / update.

H5 evidence (h5_001 "ordinary SDK" read-only dashboard, same generation as
2GB1): the page binds luminance.current / pir.status / battery /
commonFaultDetection / netInfo and has zero dispatch sites.  Profile enums
carry the labels.  luminance.current is a plain lux value (unit declared in
the Profile, step 10) — no scaling, unlike the 2GB1 tenth-unit readings.

Not exposed (宁可不出): luminance.level (device-derived comfort label),
update (OTA, app-managed).
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


class Product2GB4Adapter:
    """MIR-IR100 PIR + luminance sensor (2GB4)."""

    prod_id = "2GB4"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        entities: list[EntitySpec] = []

        # Occupancy: 0=无人, 1=有人 → HA motion class (on = someone present).
        if context.has_service("pir") and _field(profile, "pir", "status") is not None:
            entities.append(
                EntitySpec(
                    platform="binary_sensor",
                    key="occupancy",
                    name="人体移动",
                    state=lambda ctx: {"is_on": _flag_value(ctx.value("pir", "status"))},
                    metadata={"device_class": "motion"},
                )
            )

        if context.has_service("luminance") and _field(
            profile, "luminance", "current"
        ) is not None:
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="luminance",
                    name="光照度",
                    state=lambda ctx: {"native_value": _number(ctx.value("luminance", "current"))},
                    metadata={"device_class": "illuminance", "state_class": "measurement", "unit": "lux"},
                )
            )

        if context.has_service("battery") and _field(profile, "battery", "level") is not None:
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="battery_level",
                    name="电池电量",
                    state=lambda ctx: {"native_value": _number(ctx.value("battery", "level"))},
                    metadata={"device_class": "battery", "state_class": "measurement", "unit": "%"},
                )
            )
        if _field(profile, "battery", "alarm") is not None:
            entities.append(
                EntitySpec(
                    platform="binary_sensor",
                    key="battery_low",
                    name="低电量告警",
                    state=lambda ctx: {"is_on": _flag_value(ctx.value("battery", "alarm"))},
                    metadata={"device_class": "battery"},
                )
            )

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


ADAPTER = Product2GB4Adapter()
