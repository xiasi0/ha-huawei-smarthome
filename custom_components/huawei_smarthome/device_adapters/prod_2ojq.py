"""User-contributed protocol for Huawei product 2OJQ (电小酷智能转换插座 CP1-HW-A).

Profile: switch.on / indicator.on / childLockSwitch.on /
ProtectionSwitch.ProtectionSwitch / memorySwitch.status (enum 0关/1开/2保持) /
ChargingProtection.{ProtectionPower 0..200W step2, ProtectDuration 0..300min step5} /
power.current (W) / electric.{voltage V, current mA, totalElectricity kWh} /
commonFaultDetection.{code 0/100/102, status} / netInfo diagnostics.

H5 evidence (h5_001 template-style unminified bundle, socket theme):
- CommonStatusbar1.onclick -> setDeviceInfo({switch: {on: N}}); its labelObj
  names switch_on "电源开关", the outlet master switch.
- GeneralBoolSwitchCard--c4 (指示灯开关) -> setDeviceInfo({indicator: {on: N}}).
- GeneralBoolIconCard--e2 (童锁开关) -> setDeviceInfo({childLockSwitch: {on: N}}).
- GeneralBoolSwitchCard--b3 (充电保护) -> setDeviceInfo({ProtectionSwitch:
  {ProtectionSwitch: N}}) (getoptions obj mirrors the nested shape).
- GeneralEnumDroplistCard1 (断电记忆) -> setDeviceInfo({memorySwitch:
  {status: v}}), droplist 0关/1开/2保持上次状态 (same labels as Profile).
- GeneralIntCircular--c1 (保护功率) -> setDeviceInfo({ChargingProtection:
  {ProtectionPower: N}}), H5 slider 0..200 step 2 unit W.
- GeneralIntCircular--b2 (保护时间) -> setDeviceInfo({ChargingProtection:
  {ProtectDuration: N}}), H5 slider 0..300 step 5 unit min.
- Statusbar fullsdata confirms power.current 当前功率 W, electric.voltage 电压 V,
  electric.current 电流 mA; TotalChart1 renders 总用电量 (totalElectricity kWh).
- GeneralWarn1 maps commonFaultDetection.code 100=过载保护 / 102=过压保护.

Not exposed (宁可不出):
- timer / delay: list-management protocols ({timer|delay: {action: 0/1/2,
  timer|delay: [...]}}) confirmed in sdk.js ({delay:{delay:[{para:"on",...,
  sid:"switch"}],action:1}} create / action:0 update / action:2 delete), but
  they are schedule-record CRUD, not simple device controls; HA automations
  cover this better and a guessed time format risks bogus timers.
- update service: no UI/handler anywhere in this bundle (index.js handlers
  only cover the cards above; sdk.js setDeviceInfo sites are timer/delay/
  statusbar leftovers).
- ruleData hides the ChargingProtection sliders when ProtectionSwitch=0:
  that is a pure UI gate, not replicated here (persistent HA entities cannot
  be hidden dynamically, and gating writes would break usable features).
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


def _profile_range(field: Mapping[str, Any]) -> tuple[float, float] | None:
    minimum = _number(field.get("min"))
    maximum = _number(field.get("max"))
    if minimum is None or maximum is None or maximum <= minimum:
        return None
    return float(minimum), float(maximum)


def _clamp_to_profile(value: Any, field: Mapping[str, Any]) -> int | float | None:
    number = _number(value)
    value_range = _profile_range(field)
    if number is None or value_range is None:
        return number
    minimum, maximum = value_range
    number = min(max(float(number), minimum), maximum)
    return int(number) if number.is_integer() else number


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


def _enum_payload(value: str, field: Mapping[str, Any]) -> Any:
    """Convert a selected label back to the wire value.

    Numeric enum values are sent as ints, non-numeric ones verbatim.
    """
    labels = _enum_labels(field)
    for key, label in labels.items():
        if label == value:
            try:
                return int(float(key))
            except (TypeError, ValueError):
                return key
    return None


def _flag_state(sid: str, field_name: str):
    def state(device: DeviceContext) -> Mapping[str, Any]:
        return {"is_on": _bool(device.value(sid, field_name))}

    return state


def _flag_action(sid: str, field_name: str, on_value: Any):
    """Pre-bind the written value: switch platforms invoke actions with data={}."""

    async def action(context: DeviceContext, data: Mapping[str, Any]) -> None:
        await context.async_send_service(sid, {field_name: on_value})

    return action


class Product2OJQAdapter:
    prod_id = "2OJQ"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()
        entities: list[EntitySpec] = []
        entities.extend(self._switch_entities(context, profile))
        entities.extend(self._memory_entity(context, profile))
        entities.extend(self._charging_protection_entities(context, profile))
        entities.extend(self._metering_entities(context, profile))
        entities.extend(self._fault_entities(context, profile))
        entities.extend(self._net_info_entities(context, profile))
        return tuple(entities)

    def _switch_entities(
        self,
        context: DeviceContext,
        profile: Mapping[str, Any],
    ) -> tuple[EntitySpec, ...]:
        entities: list[EntitySpec] = []
        # (sid, field, key, name or None). H5 labelObj: switch_on=电源开关,
        # indicator_on=指示灯开关, childLockSwitch_on=童锁开关,
        # ProtectionSwitch_ProtectionSwitch=充电保护. Names drop the redundant
        # platform word ("开关") per naming conventions.
        specs = (
            ("switch", "on", "outlet", None),
            ("indicator", "on", "indicator", "指示灯"),
            ("childLockSwitch", "on", "child_lock", "童锁"),
            ("ProtectionSwitch", "ProtectionSwitch", "charging_protection", "充电保护"),
        )
        for sid, field_name, key, name in specs:
            if not context.has_service(sid):
                continue
            if _field(profile, sid, field_name) is None:
                continue
            entities.append(
                EntitySpec(
                    platform="switch",
                    key=key,
                    name=name,
                    state=_flag_state(sid, field_name),
                    metadata={},
                    actions={
                        "turn_on": _flag_action(sid, field_name, 1),
                        "turn_off": _flag_action(sid, field_name, 0),
                    },
                )
            )
        return tuple(entities)

    def _memory_entity(
        self,
        context: DeviceContext,
        profile: Mapping[str, Any],
    ) -> tuple[EntitySpec, ...]:
        if not context.has_service("memorySwitch"):
            return ()
        status_field = _field(profile, "memorySwitch", "status")
        if status_field is None:
            return ()
        labels = _enum_labels(status_field)
        # Keep Profile order (0关/1开/2保持上次状态), de-duplicate display labels.
        options: list[str] = []
        for raw in (option.get("enumVal") for option in status_field.get("enumList", ()) or ()):
            if raw is None:
                continue
            label = labels.get(str(raw))
            if label is None:
                continue
            if label in options:
                label = f"{label} (rawValue)"
            options.append(label)

        def state(device: DeviceContext) -> Mapping[str, Any]:
            value = device.value("memorySwitch", "status")
            if value is None or isinstance(value, bool):
                return {"current_option": None}
            label = labels.get(_enum_key(value) or "")
            return {"current_option": label}

        async def select_option(context: DeviceContext, data: Mapping[str, Any]) -> None:
            value = _enum_payload(data.get("option") or "", status_field)
            if value is None:
                raise ValueError(f"2OJQ unknown memorySwitch option: {data.get('option')!r}")
            await context.async_send_service("memorySwitch", {"status": value})

        return (
            EntitySpec(
                platform="select",
                key="memory_switch",
                name="断电记忆",
                state=state,
                metadata={"options": tuple(options)},
                actions={"select_option": select_option},
            ),
        )

    def _charging_protection_entities(
        self,
        context: DeviceContext,
        profile: Mapping[str, Any],
    ) -> tuple[EntitySpec, ...]:
        if not context.has_service("ChargingProtection"):
            return ()
        entities: list[EntitySpec] = []
        # H5 GeneralIntCircular sliders: 保护功率 0..200 step 2 W, 保护时间
        # 0..300 step 5 min. Ranges/steps follow the Profile (identical values).
        for field_name, key, name, unit in (
            ("ProtectionPower", "protection_power", "保护功率", "W"),
            ("ProtectDuration", "protection_duration", "保护时间", "min"),
        ):
            field = _field(profile, "ChargingProtection", field_name)
            value_range = _profile_range(field or {})
            if field is None or value_range is None:
                continue
            minimum, maximum = value_range
            step = _number(field.get("step")) or 1.0

            def state(device: DeviceContext, name: str = field_name) -> Mapping[str, Any]:
                return {
                    "native_value": _number(device.value("ChargingProtection", name))
                }

            async def set_value(
                context: DeviceContext,
                data: Mapping[str, Any],
                field: Mapping[str, Any] = field,
                field_name: str = field_name,
            ) -> None:
                clamped = _clamp_to_profile(data.get("value"), field)
                if clamped is None:
                    raise ValueError(f"2OJQ invalid {field_name} value: {data.get('value')!r}")
                await context.async_send_service("ChargingProtection", {field_name: clamped})

            entities.append(
                EntitySpec(
                    platform="number",
                    key=key,
                    name=name,
                    state=state,
                    metadata={
                        "min": minimum,
                        "max": maximum,
                        "step": step,
                        "unit": unit,
                    },
                    actions={"set_value": set_value},
                )
            )
        return tuple(entities)

    def _metering_entities(
        self,
        context: DeviceContext,
        profile: Mapping[str, Any],
    ) -> tuple[EntitySpec, ...]:
        entities: list[EntitySpec] = []
        # H5 statusbar fullsdata: power.current 当前功率 W, electric.voltage 电压 V,
        # electric.current 电流 mA; TotalChart1 总用电量 (totalElectricity kWh).
        # current stays a plain sensor: HA's current device class expects A,
        # not the mA this device reports.
        specs = (
            ("power", "current", "power", "当前功率", "W", "power", "measurement"),
            ("electric", "voltage", "voltage", "电压", "V", "voltage", "measurement"),
            ("electric", "current", "current", "电流", "mA", None, "measurement"),
            (
                "electric",
                "totalElectricity",
                "total_energy",
                "总用电量",
                "kWh",
                "energy",
                "total_increasing",
            ),
        )
        for sid, field_name, key, name, unit, device_class, state_class in specs:
            if not context.has_service(sid):
                continue
            if _field(profile, sid, field_name) is None:
                continue

            def state(device: DeviceContext, name: str = sid, field: str = field_name) -> Mapping[str, Any]:
                return {"native_value": _number(device.value(name, field))}

            metadata: dict[str, Any] = {"unit": unit, "state_class": state_class}
            if device_class:
                metadata["device_class"] = device_class
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key=key,
                    name=name,
                    state=state,
                    metadata=metadata,
                )
            )
        return tuple(entities)

    def _fault_entities(
        self,
        context: DeviceContext,
        profile: Mapping[str, Any],
    ) -> tuple[EntitySpec, ...]:
        entities: list[EntitySpec] = []
        if context.has_service("commonFaultDetection"):
            code_field = _field(profile, "commonFaultDetection", "code")
            if code_field is not None:

                def fault_state(device: DeviceContext) -> Mapping[str, Any]:
                    return {
                        "native_value": _enum_text(
                            code_field,
                            device.value("commonFaultDetection", "code"),
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

            status_field = _field(profile, "commonFaultDetection", "status")
            if status_field is not None:

                def problem_state(device: DeviceContext) -> Mapping[str, Any]:
                    # Profile enum: 1=设备运行异常, 0=运行正常，无错误
                    status = _number(device.value("commonFaultDetection", "status"))
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

            unit = _text(rssi_field.get("unit"))
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="wifi_rssi",
                    name="信号强度",
                    state=rssi_state,
                    metadata={
                        "unit": unit,
                        "state_class": "measurement",
                    },
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


ADAPTER = Product2OJQAdapter()
