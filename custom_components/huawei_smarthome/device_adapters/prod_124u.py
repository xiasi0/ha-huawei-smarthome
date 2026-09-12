"""User-contributed protocol for Huawei product 124U (正泰智能插座).

Profile: switch.on / power.current (0..6000 W) / consumption.consumption
(0..1000) / faultDetection.{status bool, code enum 0无故障/1过载警告} /
netInfo diagnostics / memorySwitch.status enum / timer+timerInfo+delay /
update.

H5 evidence (h5_001 webpack bundle dedicated to this product, store state
literally contains proId:"124U"):
- Main switch: setDeviceInfo({switch: {on: Number(!this.switchOn)}})
  (home banner toggle; quickmenu switchInfo path is switch/on too).
- UPDATE_DATA mutation maps reported services: case "switch" -> switchOn,
  case "power" -> power (raw current, shown as 当前功率 with unit 瓦/W),
  case "consumption" -> statistics report, case "faultDetection" ->
  faultCode, case "backlight" -> backlight.
- Consumption unit: the statistics page queries sid:"consumption",
  character:"consumption" daily sums and divides by 1e3 to display kWh
  (i18n kWh:"度", usedToday:"今日用电量") -> the raw characteristic is
  reported in Wh. color thresholds (red>2000, green<1000 on raw sums)
  are consistent with Wh per day.
- faultDetection: i18n fault page "负载过大导致设备断电" /
  "过载保护已开启" matches Profile enum 1=过载警告.
- netInfo intensity: Profile int with enumList 20/40/60/80/100 -> 0..4 格.

Not exposed (宁可不出):
- memorySwitch (断电记忆): Profile declares it RW, but this product's H5
  bundle never references it (0 occurrences) — no UI, no payload evidence
  for this device; skipped per the two-source rule.
- backlight: the H5 renders a backlight toggle ({backlight:{on:N}}), but
  the Profile has NO backlight service at all — template leftover, the
  integration's has_service() gate would never pass; not implemented.
- timer / timerInfo / delay: schedule-record CRUD ({timer:{action:0/1/2,
  timer:[...]}} / {delay:{action, delay:[{sid:"switch", para:"on", ...}]}})
  confirmed in app.js, but they are list management, not simple controls;
  HA automations cover this better.
- update: zero references in the whole bundle -> no button.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext


def _service(profile: Mapping[str, Any], sid: str) -> Mapping[str, Any] | None:
    for service in profile.get("services", ()):
        if isinstance(service, Mapping) and service.get("serviceId") == sid:
            return service
    return None


def _field(
    profile: Mapping[str, Any],
    sid: str,
    name: str,
) -> Mapping[str, Any] | None:
    service = _service(profile, sid)
    if service is None:
        return None
    for field in service.get("characteristics", ()):
        if isinstance(field, Mapping) and field.get("characteristicName") == name:
            return field
    return None


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _bool(value: Any) -> bool | None:
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


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        return value or None
    return str(value)


def _enum_labels(field: Mapping[str, Any]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for option in field.get("enumList", ()) or ():
        if not isinstance(option, Mapping):
            continue
        key = option.get("enumVal")
        if key is None:
            continue
        labels[str(key)] = str(option.get("descCh") or option.get("enumVal"))
    return labels


def _enum_key(value: Any) -> str | None:
    number = _number(value)
    return str(int(number)) if number is not None else _text(value)


def _enum_text(field: Mapping[str, Any], value: Any) -> str | None:
    """Map a raw characteristic value to its Profile enum label.

    Unknown values return None (unknown) instead of guessing a label.
    """
    if value is None or isinstance(value, bool):
        return None
    return _enum_labels(field).get(_enum_key(value) or "")


async def _turn_on(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 1})


async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 0})


class Product124UAdapter:
    prod_id = "124U"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()
        entities: list[EntitySpec] = []
        entities.extend(self._switch_entity(context, profile))
        entities.extend(self._metering_entities(context, profile))
        entities.extend(self._fault_entities(context, profile))
        entities.extend(self._net_info_entities(context, profile))
        return tuple(entities)

    def _switch_entity(
        self,
        context: DeviceContext,
        profile: Mapping[str, Any],
    ) -> tuple[EntitySpec, ...]:
        if not context.has_service("switch"):
            return ()
        if _field(profile, "switch", "on") is None:
            return ()
        return (
            EntitySpec(
                platform="switch",
                key="outlet",
                name=None,
                state=lambda device: {"is_on": _bool(device.value("switch", "on"))},
                metadata={},
                actions={"turn_on": _turn_on, "turn_off": _turn_off},
            ),
        )

    def _metering_entities(
        self,
        context: DeviceContext,
        profile: Mapping[str, Any],
    ) -> tuple[EntitySpec, ...]:
        entities: list[EntitySpec] = []
        # H5 UPDATE_DATA: power.current -> 当前功率 (i18n 瓦/W, 0..6000).
        if context.has_service("power") and _field(profile, "power", "current") is not None:

            def power_state(device: DeviceContext) -> Mapping[str, Any]:
                return {"native_value": _number(device.value("power", "current"))}

            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="power",
                    name="当前功率",
                    state=power_state,
                    metadata={
                        "unit": "W",
                        "device_class": "power",
                        "state_class": "measurement",
                    },
                )
            )
        # H5 statistics page divides consumption sums by 1e3 for kWh, so the
        # raw characteristic is Wh; total_increasing also handles a daily
        # reset (a decrease is treated as a meter reset by HA).
        if (
            context.has_service("consumption")
            and _field(profile, "consumption", "consumption") is not None
        ):

            def energy_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "native_value": _number(device.value("consumption", "consumption"))
                }

            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="energy",
                    name="用电量",
                    state=energy_state,
                    metadata={
                        "unit": "Wh",
                        "device_class": "energy",
                        "state_class": "total_increasing",
                    },
                )
            )
        return tuple(entities)

    def _fault_entities(
        self,
        context: DeviceContext,
        profile: Mapping[str, Any],
    ) -> tuple[EntitySpec, ...]:
        entities: list[EntitySpec] = []
        if context.has_service("faultDetection"):
            code_field = _field(profile, "faultDetection", "code")
            if code_field is not None:

                def fault_state(device: DeviceContext) -> Mapping[str, Any]:
                    return {
                        "native_value": _enum_text(
                            code_field,
                            device.value("faultDetection", "code"),
                        )
                    }

                entities.append(
                    EntitySpec(
                        platform="sensor",
                        key="fault_status",
                        name="故障状态",
                        state=fault_state,
                        metadata={},
                    )
                )

            status_field = _field(profile, "faultDetection", "status")
            if status_field is not None:

                def problem_state(device: DeviceContext) -> Mapping[str, Any]:
                    # Profile enum: 1=设备运行异常, 0=运行正常，无错误
                    status = _number(device.value("faultDetection", "status"))
                    return {"is_on": None if status is None else status == 1}

                entities.append(
                    EntitySpec(
                        platform="binary_sensor",
                        key="fault_problem",
                        name="故障告警",
                        state=problem_state,
                        metadata={"device_class": "problem"},
                    )
                )
        return tuple(entities)

    def _net_info_entities(
        self,
        context: DeviceContext,
        profile: Mapping[str, Any],
    ) -> tuple[EntitySpec, ...]:
        if not context.has_service("netInfo"):
            return ()

        entities: list[EntitySpec] = []

        rssi_field = _field(profile, "netInfo", "RSSI")
        if rssi_field is not None:

            def rssi_state(device: DeviceContext) -> Mapping[str, Any]:
                return {"native_value": _number(device.value("netInfo", "RSSI"))}

            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="wifi_rssi",
                    name="信号强度",
                    state=rssi_state,
                    metadata={"state_class": "measurement"},
                )
            )

        intensity_field = _field(profile, "netInfo", "intensity")
        if intensity_field is not None:

            def intensity_state(device: DeviceContext) -> Mapping[str, Any]:
                # Profile enum: 20/40/60/80/100 -> 0..4 格信号
                return {
                    "native_value": _enum_text(
                        intensity_field,
                        device.value("netInfo", "intensity"),
                    )
                }

            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="wifi_level",
                    name="信号等级",
                    state=intensity_state,
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

            def text_state(device: DeviceContext, name: str = char_name) -> Mapping[str, Any]:
                return {"native_value": _text(device.value("netInfo", name))}

            entities.append(
                EntitySpec(
                    platform="sensor",
                    key=key,
                    name=label,
                    state=text_state,
                    metadata={},
                )
            )

        return tuple(entities)


ADAPTER = Product124UAdapter()
