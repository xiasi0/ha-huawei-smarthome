"""Product adapter for the LH-335WF air quality monitor (2QBO, 豪恩, WiFi).

Profile: co2.current 0..10000 ppm + level / hcho.currentFloat 0.01..10
mg/m³ + level / heat.currentFloat / temperature.currentFloat -20..60 ℃ /
humidity.currentFloat + level + target / moisture.current / battery.{level,
alarm, charging} / indicator.on(告警灯) / sleepMode.on(睡眠模式) /
screenMode.delayTime(智能熄屏 0..6) / timer CRUD / checkSum /
commonFaultDetection.{status, code} / netInfo / update.

H5 evidence (h5_001 webpack bundle, vuex store "Ag"):

- generic dispatch ``sendCommond(sid, cid, value)`` builds
  ``{[sid]: {[cid]: value}}`` and calls ``hilink.setDeviceInfo("0", ...)``;
- indicator: ``{indicator:{on:0|1}}`` (saveAlarmSwitchSetting);
- sleepMode: ``{sleepMode:{on:0|1}}`` (saveSleepModeOff / on toggle);
- screenMode: ``sendCommond("screenMode","delayTime", N)`` with the picker
  value 0=不启用 / 1=30秒 / 2=1分钟 / 3=2分钟 / 4=3分钟 / 5=4分钟 / 6=5分钟;
- store getters read hcho.currentFloat, temperature.currentFloat,
  humidity.currentFloat, co2.current, battery.level/alarm/charging — the
  float characteristics are the ones the page displays;
- **moisture never appears in the bundle** (zero occurrences) — it is a
  legacy duplicate of humidity on this product, not exposed;
- co2AlarmSwitch / hchoAlarmSwitch appear in the bundle's mock defaults but
  NOT in the 2QBO Profile — family leftovers, not exposed.

Not exposed (宁可不出): timer (full CRUD protocol, sleep-mode timer payloads
are app-internal), checkSum, update (OTA, app-managed), battery.charging is
exposed, the level comfort enums are device-derived duplicates.
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


_SCREEN_MODE_OPTIONS = (
    (0, "不启用"),
    (1, "30秒"),
    (2, "1分钟"),
    (3, "2分钟"),
    (4, "3分钟"),
    (5, "4分钟"),
    (6, "5分钟"),
)


class Product2QBOAdapter:
    """LH-335WF air quality monitor (2QBO)."""

    prod_id = "2QBO"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        entities: list[EntitySpec] = []

        if context.has_service("co2") and _field(profile, "co2", "current") is not None:
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="co2",
                    name="CO2 浓度",
                    state=lambda ctx: {"native_value": _number(ctx.value("co2", "current"))},
                    metadata={
                        "device_class": "carbon_dioxide",
                        "state_class": "measurement",
                        "unit": "ppm",
                    },
                )
            )

        if context.has_service("hcho") and _field(
            profile, "hcho", "currentFloat"
        ) is not None:
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="hcho",
                    name="甲醛浓度",
                    state=lambda ctx: {"native_value": _number(ctx.value("hcho", "currentFloat"))},
                    metadata={"state_class": "measurement", "unit": "mg/m³"},
                )
            )

        if context.has_service("temperature") and _field(
            profile, "temperature", "currentFloat"
        ) is not None:
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="temperature",
                    name="温度",
                    state=lambda ctx: {
                        "native_value": _number(ctx.value("temperature", "currentFloat"))
                    },
                    metadata={"device_class": "temperature", "state_class": "measurement", "unit": "℃"},
                )
            )

        if context.has_service("humidity") and _field(
            profile, "humidity", "currentFloat"
        ) is not None:
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="humidity",
                    name="湿度",
                    state=lambda ctx: {
                        "native_value": _number(ctx.value("humidity", "currentFloat"))
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
            if _field(profile, "battery", "charging") is not None:
                entities.append(
                    EntitySpec(
                        platform="sensor",
                        key="battery_charging",
                        name="充电状态",
                        state=lambda ctx: {
                            "native_value": _enum_text(ctx, "battery", "charging")
                        },
                        metadata={},
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

        # --- controls ---------------------------------------------------------
        if context.has_service("indicator") and _field(profile, "indicator", "on") is not None:
            entities.append(
                EntitySpec(
                    platform="switch",
                    key="alarm_light",
                    name="告警灯",
                    state=lambda ctx: {"is_on": _flag_value(ctx.value("indicator", "on"))},
                    metadata={},
                    actions={
                        "turn_on": self._flag_action("indicator", 1),
                        "turn_off": self._flag_action("indicator", 0),
                    },
                )
            )

        if context.has_service("sleepMode") and _field(profile, "sleepMode", "on") is not None:
            entities.append(
                EntitySpec(
                    platform="switch",
                    key="sleep_mode",
                    name="睡眠模式",
                    state=lambda ctx: {"is_on": _flag_value(ctx.value("sleepMode", "on"))},
                    metadata={},
                    actions={
                        "turn_on": self._flag_action("sleepMode", 1),
                        "turn_off": self._flag_action("sleepMode", 0),
                    },
                )
            )

        if context.has_service("screenMode") and _field(
            profile, "screenMode", "delayTime"
        ) is not None:
            options = tuple(label for _v, label in _SCREEN_MODE_OPTIONS)
            values = tuple(value for value, _label in _SCREEN_MODE_OPTIONS)

            def screen_state(ctx: DeviceContext) -> Mapping[str, Any]:
                raw = ctx.value("screenMode", "delayTime")
                if raw is None or isinstance(raw, bool):
                    return {"current_option": None}
                try:
                    number = int(str(raw).strip())
                except (TypeError, ValueError):
                    return {"current_option": None}
                return {
                    "current_option": dict(zip(values, options)).get(number)
                }

            async def select_screen(ctx: DeviceContext, data: Mapping[str, Any]) -> None:
                option = data.get("option")
                if option not in options:
                    raise ValueError(f"2QBO unknown screen mode: {option!r}")
                value = values[options.index(option)]
                await ctx.async_send_service("screenMode", {"delayTime": value})

            entities.append(
                EntitySpec(
                    platform="select",
                    key="screen_mode",
                    name="智能熄屏",
                    state=screen_state,
                    metadata={"options": list(options)},
                    actions={"select_option": select_screen},
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

    @staticmethod
    def _flag_action(sid: str, value: int):
        async def action(ctx: DeviceContext, data: Mapping[str, Any]) -> None:
            del data
            await ctx.async_send_service(sid, {"on": value})

        return action


ADAPTER = Product2QBOAdapter()
