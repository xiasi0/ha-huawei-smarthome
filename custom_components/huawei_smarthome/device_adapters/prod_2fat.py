"""User-contributed protocol for Huawei product 2FAT (协议空调 MC3-Ac).

Profile: switch.on / mode.mode (21 enums) / temperature.{target 16..35℃
step1, targetFloat 16..35℃ step0.5, current/currentFloat float,
targetStep ±} / fan.{gear 12 enums, speed 0..100%, verticalDirection 6,
horizontalDirection 6} / humidity.{levelTarget 4 enums, target 0..100%,
current R} / lightSwitch.on / controlStrategy.mode (0 内部/1 外部) /
panelLocation.panelLocation (3 enums) / filterElement.{reset, alarm,
leftPer %, leftTime h, filterType} / faultDetection.{code 0..32+127,
status} / netInfo diagnostics.

H5 evidence (h5_001 webpack bundle, store action setDeviceInfo -> hilink.
setDeviceInfo("0", JSON.stringify(data)), all dispatch sites in app.js):
- toggleSwitch -> {switch:{on:N}} 空调开关 (turns off delay countdown too).
- setAcMode -> {mode:{mode:t}}; acModeFullList = 21 modes, labels are the
  Profile descCh set (auto/cooling/heating/.../dehumidificationWithReheating).
- setFanGear -> {fan:{gear:t}} (fanGearFullList, 12 gears, Profile labels);
  shown only when numericalFanSpeedSwitch != "1", otherwise the speed
  slider is used -> setFanSpeed -> {fan:{speed:e}} 0..100%. Both exposed.
- setVerticalDirection -> {fan:{verticalDirection:t}}, 6 options
  (0=上下扫风/1..5 定向); setHorizontalDirection likewise.
- temperatureOn/Off (±targetStep, 500ms debounce): sends
  {temperature:{targetFloat:v}} when temperatureShowFloat (targetStep 0.5)
  else {temperature:{target:v}}; both mapped, H5 clamps display to
  -20..50 and target to 16..35.
- setHumidity -> {humidity:{target:e}} (gated by numericalHumiditySwitch);
  setHumidityLevel -> {humidity:{levelTarget:t}} 4 levels; report side:
  humidity.current is treated as plain % (values <1 or >100 discarded,
  no scaling despite the Profile max=1000).
- lightSwitchChange -> {lightSwitch:{on:N}} 照明开关.
- checkControlStrategy -> {controlStrategy:{mode:N}} 内部/外部控制.
- setPaMode -> {panelLocation:{panelLocation:t}} 3 options.
- filter page sure() -> {filterElement:{reset:1}} 滤芯复位.

Not exposed (宁可不出):
- capabilityset (lightSwitch/systemModeSetConfig/gearSetConfig/
  filterResetSet/filterUsageAlarmSet/fan*DirectionSet strings): App-side
  display configuration; the H5 dispatches use sid "capability" while the
  Profile declares "capabilityset", a wire mismatch we will not guess at.
- delay/preTime: countdown is a full-object CRUD with UTC timestamps
  ("YYYYMMDDTHHMMSSZ", {delay:{action:1,num:1,delay:[{id:1,enable:1,end,
  sid:"switch",para:"on",paraValue:0}]}}); HA automations cover this and
  a guessed clock format risks bogus timers. preTime.preEndTime is only
  bookkeeping of the last countdown.
- update: no dispatch site in the bundle (OTA via App only).
- windSpeedEx / temperature.level: zero occurrences in the bundle.
- temperature.showOneStep/showZeroFiveStep/showFloat/targetStep: App
  display-step configuration, not device control.
- airChangeSwitch / airChangeGear: dispatched by the bundle but absent
  from the 2FAT Profile (shared-bundle leftovers), not device contract.
- queryAction: read-only poll ({queryAction:{action:3}}), no HA mapping.
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


def _make_enum_select(
    context: DeviceContext,
    profile: Mapping[str, Any],
    sid: str,
    field_name: str,
    key: str,
    name: str,
) -> EntitySpec | None:
    """Shared builder for enum-value selects backed by one characteristic."""
    if not context.has_service(sid):
        return None
    field = _field(profile, sid, field_name)
    if field is None:
        return None
    labels = _enum_labels(field)
    # Keep Profile order, de-duplicate display labels (e.g. mode 4 送风 vs
    # 9 换气 differ in Chinese; guard anyway for other fields).
    options: list[str] = []
    for raw in (option.get("enumVal") for option in field.get("enumList", ()) or ()):
        if raw is None:
            continue
        label = labels.get(str(raw))
        if label is None:
            continue
        if label in options:
            label = f"{label} (rawValue)"
        options.append(label)

    def state(device: DeviceContext) -> Mapping[str, Any]:
        value = device.value(sid, field_name)
        if value is None or isinstance(value, bool):
            return {"current_option": None}
        return {"current_option": labels.get(_enum_key(value) or "")}

    async def select_option(
        context: DeviceContext,
        data: Mapping[str, Any],
        field: Mapping[str, Any] = field,
        field_name: str = field_name,
    ) -> None:
        value = _enum_payload(data.get("option") or "", field)
        if value is None:
            raise ValueError(f"2FAT unknown {field_name} option: {data.get('option')!r}")
        await context.async_send_service(sid, {field_name: value})

    return EntitySpec(
        platform="select",
        key=key,
        name=name,
        state=state,
        metadata={"options": tuple(options)},
        actions={"select_option": select_option},
    )


def _make_number(
    context: DeviceContext,
    profile: Mapping[str, Any],
    sid: str,
    field_name: str,
    key: str,
    name: str,
    unit: str,
) -> EntitySpec | None:
    """Shared builder for one-clamp number entities."""
    if not context.has_service(sid):
        return None
    field = _field(profile, sid, field_name)
    value_range = _profile_range(field or {})
    if field is None or value_range is None:
        return None
    minimum, maximum = value_range
    step = _number(field.get("step")) or 1.0

    def state(device: DeviceContext, name: str = field_name) -> Mapping[str, Any]:
        return {"native_value": _number(device.value(sid, name))}

    async def set_value(
        context: DeviceContext,
        data: Mapping[str, Any],
        field: Mapping[str, Any] = field,
        field_name: str = field_name,
    ) -> None:
        clamped = _clamp_to_profile(data.get("value"), field)
        if clamped is None:
            raise ValueError(f"2FAT invalid {field_name} value: {data.get('value')!r}")
        await context.async_send_service(sid, {field_name: clamped})

    return EntitySpec(
        platform="number",
        key=key,
        name=name,
        state=state,
        metadata={"min": minimum, "max": maximum, "step": step, "unit": unit},
        actions={"set_value": set_value},
    )


def _make_sensor(
    context: DeviceContext,
    profile: Mapping[str, Any],
    sid: str,
    field_name: str,
    key: str,
    name: str,
    unit: str | None = None,
    device_class: str | None = None,
    state_class: str | None = None,
) -> EntitySpec | None:
    if not context.has_service(sid):
        return None
    if _field(profile, sid, field_name) is None:
        return None

    def state(device: DeviceContext, name: str = field_name) -> Mapping[str, Any]:
        return {"native_value": _number(device.value(sid, name))}

    metadata: dict[str, Any] = {}
    if unit:
        metadata["unit"] = unit
    if state_class:
        metadata["state_class"] = state_class
    if device_class:
        metadata["device_class"] = device_class
    return EntitySpec(
        platform="sensor",
        key=key,
        name=name,
        state=state,
        metadata=metadata,
    )


class Product2FATAdapter:
    prod_id = "2FAT"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()
        entities: list[EntitySpec] = []
        entities.extend(self._switch_entities(context, profile))
        entities.extend(self._mode_entities(context, profile))
        entities.extend(self._temperature_entities(context, profile))
        entities.extend(self._fan_entities(context, profile))
        entities.extend(self._humidity_entities(context, profile))
        entities.extend(self._config_selects(context, profile))
        entities.extend(self._filter_entities(context, profile))
        entities.extend(self._fault_entities(context, profile))
        entities.extend(self._net_info_entities(context, profile))
        return tuple(entities)

    def _switch_entities(
        self,
        context: DeviceContext,
        profile: Mapping[str, Any],
    ) -> tuple[EntitySpec, ...]:
        entities: list[EntitySpec] = []
        # H5 toggleSwitch: {switch:{on:N}} is the AC master switch (name falls
        # back to the device name); lightSwitchChange: {lightSwitch:{on:N}}.
        for sid, field_name, key, name in (
            ("switch", "on", "ac_switch", None),
            ("lightSwitch", "on", "light_switch", "照明开关"),
        ):
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

    def _mode_entities(
        self,
        context: DeviceContext,
        profile: Mapping[str, Any],
    ) -> tuple[EntitySpec, ...]:
        spec = _make_enum_select(
            context, profile, "mode", "mode", "mode", "模式"
        )
        return () if spec is None else (spec,)

    def _temperature_entities(
        self,
        context: DeviceContext,
        profile: Mapping[str, Any],
    ) -> tuple[EntitySpec, ...]:
        entities: list[EntitySpec] = []
        # H5 sends {temperature:{target}} normally and
        # {temperature:{targetFloat}} when the 0.5℃ step is configured;
        # both are real dispatch payloads, so both are exposed.
        target = _make_number(
            context, profile, "temperature", "target",
            "target_temperature", "目标温度", "℃",
        )
        if target is not None:
            entities.append(target)
        target_float = _make_number(
            context, profile, "temperature", "targetFloat",
            "target_temperature_float", "目标温度(0.5℃步进)", "℃",
        )
        if target_float is not None:
            entities.append(target_float)

        if context.has_service("temperature") and (
            _field(profile, "temperature", "current") is not None
            or _field(profile, "temperature", "currentFloat") is not None
        ):

            def current_state(device: DeviceContext) -> Mapping[str, Any]:
                # Prefer the float variant when the device reports one.
                raw = device.value("temperature", "currentFloat")
                if raw is None:
                    raw = device.value("temperature", "current")
                return {"native_value": _number(raw)}

            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="current_temperature",
                    name="当前温度",
                    state=current_state,
                    metadata={
                        "unit": "℃",
                        "device_class": "temperature",
                        "state_class": "measurement",
                    },
                )
            )
        return tuple(entities)

    def _fan_entities(
        self,
        context: DeviceContext,
        profile: Mapping[str, Any],
    ) -> tuple[EntitySpec, ...]:
        entities: list[EntitySpec] = []
        gear = _make_enum_select(
            context, profile, "fan", "gear", "fan_gear", "风速档位"
        )
        if gear is not None:
            entities.append(gear)
        speed = _make_number(
            context, profile, "fan", "speed", "fan_speed", "风速", "%"
        )
        if speed is not None:
            entities.append(speed)
        vertical = _make_enum_select(
            context, profile, "fan", "verticalDirection",
            "fan_vertical_direction", "上下扫风",
        )
        if vertical is not None:
            entities.append(vertical)
        horizontal = _make_enum_select(
            context, profile, "fan", "horizontalDirection",
            "fan_horizontal_direction", "左右扫风",
        )
        if horizontal is not None:
            entities.append(horizontal)
        return tuple(entities)

    def _humidity_entities(
        self,
        context: DeviceContext,
        profile: Mapping[str, Any],
    ) -> tuple[EntitySpec, ...]:
        entities: list[EntitySpec] = []
        level_target = _make_enum_select(
            context, profile, "humidity", "levelTarget",
            "humidity_level_target", "目标湿度等级",
        )
        if level_target is not None:
            entities.append(level_target)
        target = _make_number(
            context, profile, "humidity", "target",
            "humidity_target", "目标湿度", "%",
        )
        if target is not None:
            entities.append(target)

        if context.has_service("humidity") and (
            _field(profile, "humidity", "current") is not None
        ):

            def current_state(device: DeviceContext) -> Mapping[str, Any]:
                # H5 treats humidity.current as plain %: values <1 or >100
                # are discarded (no /10 scaling despite Profile max=1000).
                number = _number(device.value("humidity", "current"))
                if number is None or number < 1 or number > 100:
                    return {"native_value": None}
                return {"native_value": number}

            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="current_humidity",
                    name="当前湿度",
                    state=current_state,
                    metadata={
                        "unit": "%",
                        "device_class": "humidity",
                        "state_class": "measurement",
                    },
                )
            )
        return tuple(entities)

    def _config_selects(
        self,
        context: DeviceContext,
        profile: Mapping[str, Any],
    ) -> tuple[EntitySpec, ...]:
        entities: list[EntitySpec] = []
        strategy = _make_enum_select(
            context, profile, "controlStrategy", "mode",
            "control_strategy", "控制策略",
        )
        if strategy is not None:
            entities.append(strategy)
        panel = _make_enum_select(
            context, profile, "panelLocation", "panelLocation",
            "panel_location", "面板安装位置",
        )
        if panel is not None:
            entities.append(panel)
        return tuple(entities)

    def _filter_entities(
        self,
        context: DeviceContext,
        profile: Mapping[str, Any],
    ) -> tuple[EntitySpec, ...]:
        entities: list[EntitySpec] = []
        # H5 filter page sure(): {filterElement:{reset:1}} 滤芯复位.
        if context.has_service("filterElement") and (
            _field(profile, "filterElement", "reset") is not None
        ):

            async def reset(context: DeviceContext, data: Mapping[str, Any]) -> None:
                await context.async_send_service("filterElement", {"reset": 1})

            entities.append(
                EntitySpec(
                    platform="button",
                    key="filter_reset",
                    name="滤芯复位",
                    state=lambda device: {},
                    metadata={},
                    actions={"press": reset},
                )
            )

        if context.has_service("filterElement") and (
            _field(profile, "filterElement", "alarm") is not None
        ):

            def alarm_state(device: DeviceContext) -> Mapping[str, Any]:
                # Profile enum: 1=有告警, 0=无告警
                value = _number(device.value("filterElement", "alarm"))
                return {"is_on": None if value is None else value == 1}

            entities.append(
                EntitySpec(
                    platform="binary_sensor",
                    key="filter_alarm",
                    name="滤芯告警",
                    state=alarm_state,
                    metadata={"device_class": "problem"},
                )
            )

        left_per = _make_sensor(
            context, profile, "filterElement", "leftPer",
            "filter_life", "滤芯剩余寿命", unit="%",
            state_class="measurement",
        )
        if left_per is not None:
            entities.append(left_per)
        left_time = _make_sensor(
            context, profile, "filterElement", "leftTime",
            "filter_remaining_time", "滤芯剩余时长", unit="h",
        )
        if left_time is not None:
            entities.append(left_time)

        filter_type_field = _field(profile, "filterElement", "filterType")
        if context.has_service("filterElement") and filter_type_field is not None:

            def type_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "native_value": _enum_text(
                        filter_type_field,
                        device.value("filterElement", "filterType"),
                    )
                }

            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="filter_type",
                    name="滤芯类型",
                    state=type_state,
                    metadata={},
                )
            )
        return tuple(entities)

    def _fault_entities(
        self,
        context: DeviceContext,
        profile: Mapping[str, Any],
    ) -> tuple[EntitySpec, ...]:
        entities: list[EntitySpec] = []
        code_field = _field(profile, "faultDetection", "code")
        if context.has_service("faultDetection") and code_field is not None:

            def fault_state(device: DeviceContext) -> Mapping[str, Any]:
                # 32 fault codes + 127 (正在等待环境参数同步); unknown -> None
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
        if context.has_service("faultDetection") and status_field is not None:

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
            # Profile unit is empty; plain numeric sensor (2OJQ convention).
            rssi = _make_sensor(
                context, profile, "netInfo", "RSSI",
                "wifi_rssi", "信号强度", state_class="measurement",
            )
            if rssi is not None:
                entities.append(rssi)

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


ADAPTER = Product2FATAdapter()
