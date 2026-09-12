"""Product adapter for the MIR-TE100 temperature/humidity sensor (2GB1, Mesh).

Profile: temperature.{level enum, current int -100..400 unit ℃} /
humidity.{level enum, current int 0..1000 unit %, target RW 0..100} /
battery.{level 0..100, alarm bool} / commonFaultDetection.{status, code} /
update / netInfo.

H5 evidence (h5_001 "ordinary SDK" low-code page: data/index.data.js +
js/index.js):

- The page is a read-only dashboard.  The display config declares
  temperature_current min=-100 max=400 unit ℃ and humidity_current
  min=0 max=1000 unit %, with no divisor applied anywhere in the page
  engine.  The raw characteristic values are therefore TENTHS: the
  sibling 2QBO air monitor reports temperature.currentFloat -20..60 ℃
  and humidity 0..100 % directly, so 2GB1's -100..400 and 0..1000 map
  to -10.0..40.0 ℃ and 0.0..100.0 % via ÷10 — the only physically
  consistent reading for the -10..40 ℃ / 0..100 % sensor hardware.
- No dispatch sites at all: the page only forwards status-bar clicks.
  All services are read-only in practice (humidity.target is never
  referenced by the page and has no documented write semantics → not
  exposed).
- battery.alarm bool (1=低电量告警), commonFaultDetection.code
  (0=正常/1=低压故障) and .status (1=异常) map directly to entities.

Not exposed (宁可不出): temperature.level / humidity.level comfort enums
(device-derived labels duplicating the measured value), humidity.target
(unreferenced, no write semantics), update (OTA, app-managed).
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
    """Map a reported enum value onto its Profile descCh label."""
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


def _scale_tenths(context: DeviceContext, sid: str, name: str) -> float | None:
    """Raw tenth-unit reading → physical value."""
    raw = _number(context.value(sid, name))
    return None if raw is None else raw / 10.0


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


class Product2GB1Adapter:
    """MIR-TE100 temperature/humidity sensor (2GB1)."""

    prod_id = "2GB1"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        entities: list[EntitySpec] = []

        if context.has_service("temperature") and _field(
            profile, "temperature", "current"
        ) is not None:
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="temperature",
                    name="温度",
                    state=lambda ctx: {
                        "native_value": _scale_tenths(ctx, "temperature", "current")
                    },
                    metadata={"device_class": "temperature", "state_class": "measurement", "unit": "℃"},
                )
            )

        if context.has_service("humidity") and _field(
            profile, "humidity", "current"
        ) is not None:
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="humidity",
                    name="湿度",
                    state=lambda ctx: {
                        "native_value": _scale_tenths(ctx, "humidity", "current")
                    },
                    metadata={"device_class": "humidity", "state_class": "measurement", "unit": "%"},
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


ADAPTER = Product2GB1Adapter()
