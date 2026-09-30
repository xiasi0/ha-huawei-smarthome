"""User-contributed protocol for Huawei product 2QQ4.

设备: IAM 智能消毒空气净化器 X5 Ultra（免换芯）
厂商: 艾恩科技集团
类型: 空气净化器 (deviceTypeId 013 / Air Cleaner)
Profile: https://smarthome-drcn.dbankcdn.com/device/guide/2QQ4/2QQ4.json

实体映射：
  fan        <- switch.on(电源) + fan.gear(风速1~5档 -> 20~100%) + mode.mode(模式)
  switch     <- 童锁/按键音/氛围灯/待机监测/屏幕/自动风速
  select     <- 氛围灯亮度(低/中/高) + 节能设置(自动待机阈值/自动运行阈值)
  button     <- 复位滤网 (初效/除醛/净味/消杀电场)
  sensor     <- 空气质量/过敏原/甲醛/温湿度/PM2.5/PM10/户外PM/TVOC/净化量/滤芯剩余/故障码/节能状态
  binary_sensor <- 故障(status)
  sensor(诊断) <- 定时任务（只读，见下）

说明：
  - 定时(timer)是「定时计划列表」，结构为云端托管的不透明 ``array[object]``，
    HA 没有对应平台，故只做只读展示（任务数 + 原始列表属性），
    新增/修改/删除定时仍在「智慧生活」App 内完成；这也与本仓库其它适配器
    (prod_105m/prod_100z) 对 timer 的处理惯例一致。
  - 未映射: netInfo、update(OTA)、outdoorPM25.cityCode（无 text 平台）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _bool(value: Any) -> bool | None:
    """容忍 bool / 数字 / 字符串 形式的开关状态。"""
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


def _num(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _norm_key(value: Any) -> str | None:
    """把 enumVal 规范成字符串，便于查表。"""
    number = _num(value)
    if number is not None:
        return str(int(number))
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _service(profile: Mapping[str, Any], sid: str) -> Mapping[str, Any] | None:
    for service in (profile or {}).get("services", ()):
        if isinstance(service, Mapping) and service.get("serviceId") == sid:
            return service
    return None


def _field(
    profile: Mapping[str, Any], sid: str, name: str
) -> Mapping[str, Any] | None:
    service = _service(profile, sid)
    if service is None:
        return None
    for field in service.get("characteristics", ()):
        if isinstance(field, Mapping) and field.get("characteristicName") == name:
            return field
    return None


def _enum_map(profile: Mapping[str, Any], sid: str, name: str) -> dict[str, str]:
    """enumVal(字符串) -> 中文描述。"""
    field = _field(profile, sid, name) or {}
    result: dict[str, str] = {}
    for option in field.get("enumList", ()):
        if not isinstance(option, Mapping):
            continue
        key = _norm_key(option.get("enumVal"))
        if key is not None:
            result[key] = str(option.get("descCh") or option.get("enumVal"))
    return result


# ---------------------------------------------------------------------------
# 电源 / 风速 / 模式
# ---------------------------------------------------------------------------

# mode.mode 枚举
_MODE_LABEL = {"0": "手动", "1": "自动", "2": "睡眠", "3": "节能", "4": "强力"}
_MODE_VALUE = {label: raw for raw, label in _MODE_LABEL.items()}

# fan.gear 1~5 档 -> 百分比
_GEAR_MIN, _GEAR_MAX = 1, 5
_PERCENT_STEP = 100 // _GEAR_MAX  # 20


def _gear_to_percentage(gear: Any) -> int | None:
    number = _num(gear)
    if number is None or not (_GEAR_MIN <= number <= _GEAR_MAX):
        return None
    return int(number) * _PERCENT_STEP


def _percentage_to_gear(percentage: Any) -> int | None:
    number = _num(percentage)
    if number is None:
        return None
    gear = int(round(float(number) / _PERCENT_STEP))
    return min(_GEAR_MAX, max(_GEAR_MIN, gear))


async def _fan_turn_on(context: DeviceContext, data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 1})
    if data.get("preset_mode") is not None:
        await _set_mode(context, data["preset_mode"])
    if data.get("percentage") is not None:
        await _set_gear(context, data["percentage"])


async def _fan_turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 0})


async def _set_gear(context: DeviceContext, percentage: Any) -> None:
    gear = _percentage_to_gear(percentage)
    if gear is None:
        return
    await context.async_send_service("fan", {"gear": gear})


async def _fan_set_percentage(context: DeviceContext, data: Mapping[str, Any]) -> None:
    await _set_gear(context, data.get("percentage"))


async def _set_mode(context: DeviceContext, label: Any) -> None:
    raw = _MODE_VALUE.get(str(label))
    if raw is None:
        raise ValueError(f"2QQ4 未知模式: {label}")
    await context.async_send_service("mode", {"mode": int(raw)})


async def _fan_set_preset_mode(context: DeviceContext, data: Mapping[str, Any]) -> None:
    await _set_mode(context, data.get("preset_mode"))


# ---------------------------------------------------------------------------
# 开关（各 service 的 on 字段）
# ---------------------------------------------------------------------------

# (sid, 字段名, 显示名, key)
_SWITCHES = (
    ("childLockSwitch", "on", "童锁", "child_lock"),
    ("keyToneSwitch", "on", "按键音", "key_tone"),
    ("lightSwitch", "lightSwitch", "氛围灯", "ambient_light"),
    ("monitoringSwitch", "on", "待机监测", "monitoring"),
    ("screenSwitch", "on", "屏幕", "screen"),
    ("fan", "autoFanSwitch", "自动风速", "auto_fan"),
)


def _make_switch(sid: str, field: str, name: str, key: str) -> EntitySpec:
    async def _on(context: DeviceContext, _data: Mapping[str, Any]) -> None:
        await context.async_send_service(sid, {field: 1})

    async def _off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
        await context.async_send_service(sid, {field: 0})

    def _state(device: DeviceContext) -> Mapping[str, Any]:
        return {"is_on": _bool(device.value(sid, field))}

    return EntitySpec(
        platform="switch",
        key=key,
        name=name,
        state=_state,
        actions={"turn_on": _on, "turn_off": _off},
    )


# ---------------------------------------------------------------------------
# 复位滤网按钮
# ---------------------------------------------------------------------------

# (sid, 显示名, key)
_RESET_BUTTONS = (
    ("filterElement7", "复位初效滤网", "reset_prefilter"),
    ("filterElement6", "复位除醛滤层", "reset_aldehyde_filter"),
    ("filterElement4", "复位净味滤层", "reset_odor_filter"),
    ("filterElement8", "复位消杀电场", "reset_sterilize_filter"),
)


def _make_reset_button(sid: str, name: str, key: str) -> EntitySpec:
    async def _press(context: DeviceContext, _data: Mapping[str, Any]) -> None:
        await context.async_send_service(sid, {"reset": 1})

    return EntitySpec(
        platform="button",
        key=key,
        name=name,
        state=lambda _device: {},
        actions={"press": _press},
    )


# ---------------------------------------------------------------------------
# 传感器
# ---------------------------------------------------------------------------

# 枚举型传感器: (sid, 字段, 显示名, key)
_ENUM_SENSORS = (
    ("airQuality", "level", "空气质量", "air_quality"),
    ("allergen", "level", "过敏原", "allergen"),
    ("hcho", "level", "甲醛等级", "hcho_level"),
    ("pm25", "level", "PM2.5等级", "pm25_level"),
    ("pm10", "level", "PM10等级", "pm10_level"),
    ("tvoc", "level", "TVOC", "tvoc"),
    ("commonFaultDetection", "code", "故障码", "fault_code"),
    ("ecoSetting", "workStatus", "节能运行状态", "eco_work_status"),
)

# 数值型传感器: (sid, 字段, 显示名, key, 单位, device_class, state_class, entity_category)
_NUM_SENSORS = (
    ("hcho", "currentFloat", "甲醛", "hcho", "mg/m³", None, "measurement", None),
    ("humidity", "current", "湿度", "humidity", "%", "humidity", "measurement", None),
    ("temperature", "current", "温度", "temperature", "°C", "temperature", "measurement", None),
    ("pm25", "currentFloat", "PM2.5", "pm25", "mg/m³", None, "measurement", None),
    ("pm10", "currentFloat", "PM10", "pm10", "mg/m³", None, "measurement", None),
    ("outdoorPM25", "currentFloat", "户外PM2.5", "outdoor_pm25", "mg/m³", None, "measurement", None),
    ("outdoorPM10", "currentFloat", "户外PM10", "outdoor_pm10", "mg/m³", None, "measurement", None),
    ("cav", "current", "累计净化空气量", "cav", "m³", None, "total_increasing", None),
    ("dailyPurifiedAir", "cav", "日净化空气体积", "daily_air", "m³", None, "measurement", None),
    ("dailyPurifiedAir", "weight", "日净化空气重量", "daily_weight", "mg", None, "measurement", None),
    ("weight", "weightFloat", "洁净颗粒物重量", "dust_weight", "mg/m³", None, "measurement", None),
    ("filterElement7", "leftPer", "初效滤网剩余", "filter_pre", "%", None, "measurement", "diagnostic"),
    ("filterElement6", "leftPer", "除醛滤层剩余", "filter_aldehyde", "%", None, "measurement", "diagnostic"),
    ("filterElement4", "leftPercentage", "净味滤层剩余", "filter_odor", "%", None, "measurement", "diagnostic"),
    ("filterElement8", "leftPer", "消杀电场剩余", "filter_sterilize", "%", None, "measurement", "diagnostic"),
)


def _make_enum_sensor(
    profile: Mapping[str, Any], sid: str, field: str, name: str, key: str
) -> EntitySpec:
    mapping = _enum_map(profile, sid, field)

    def _state(device: DeviceContext) -> Mapping[str, Any]:
        raw = _norm_key(device.value(sid, field))
        if raw is None:
            return {"native_value": None}
        return {"native_value": mapping.get(raw, raw)}

    metadata: dict[str, Any] = {}
    if key == "fault_code":
        metadata["entity_category"] = "diagnostic"

    return EntitySpec(
        platform="sensor", key=key, name=name, state=_state, metadata=metadata
    )


def _make_enum_select(
    profile: Mapping[str, Any],
    sid: str,
    field: str,
    name: str,
    key: str,
    entity_category: str | None = None,
) -> EntitySpec:
    """用 Profile 的 enumList 生成一个 select 实体。"""
    mapping = _enum_map(profile, sid, field)
    options = tuple(mapping.values())
    raw_by_label = {label: raw for raw, label in mapping.items()}

    def _state(device: DeviceContext) -> Mapping[str, Any]:
        raw = _norm_key(device.value(sid, field))
        if raw is None:
            return {"current_option": None}
        return {"current_option": mapping.get(raw, raw)}

    async def _select(device: DeviceContext, data: Mapping[str, Any]) -> None:
        raw = raw_by_label.get(str(data.get("option")))
        if raw is None:
            raise ValueError(f"2QQ4 未知选项 {sid}.{field}: {data.get('option')}")
        await device.async_send_service(
            sid, {field: int(raw) if raw.lstrip("-").isdigit() else raw}
        )

    metadata: dict[str, Any] = {"options": options}
    if entity_category:
        metadata["entity_category"] = entity_category

    return EntitySpec(
        platform="select",
        key=key,
        name=name,
        state=_state,
        metadata=metadata,
        actions={"select_option": _select},
    )


def _make_num_sensor(
    sid: str,
    field: str,
    name: str,
    key: str,
    unit: str | None,
    device_class: str | None,
    state_class: str | None,
    entity_category: str | None,
) -> EntitySpec:
    metadata: dict[str, Any] = {}
    if unit:
        metadata["unit"] = unit
    if device_class:
        metadata["device_class"] = device_class
    if state_class:
        metadata["state_class"] = state_class
    if entity_category:
        metadata["entity_category"] = entity_category

    def _state(device: DeviceContext) -> Mapping[str, Any]:
        return {"native_value": _num(device.value(sid, field))}

    return EntitySpec(
        platform="sensor", key=key, name=name, state=_state, metadata=metadata
    )


# ---------------------------------------------------------------------------
# 适配器
# ---------------------------------------------------------------------------

class Product2QQ4Adapter:
    """2QQ4 IAM X5 Ultra 空气净化器适配器。"""

    prod_id = "2QQ4"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        entities: list[EntitySpec] = []

        # ---- fan: 电源 + 风速 + 模式 ----
        if context.has_service("switch") and context.has_service("fan"):
            def fan_state(device: DeviceContext) -> Mapping[str, Any]:
                mode_key = _norm_key(device.value("mode", "mode"))
                return {
                    "is_on": _bool(device.value("switch", "on")),
                    "percentage": _gear_to_percentage(device.value("fan", "gear")),
                    "preset_mode": _MODE_LABEL.get(mode_key) if mode_key else None,
                }

            entities.append(
                EntitySpec(
                    platform="fan",
                    key="purifier",
                    name=None,
                    state=fan_state,
                    metadata={
                        "preset_modes": tuple(_MODE_LABEL.values()),
                        "supports_percentage": True,
                        "percentage_step": _PERCENT_STEP,
                    },
                    actions={
                        "turn_on": _fan_turn_on,
                        "turn_off": _fan_turn_off,
                        "set_percentage": _fan_set_percentage,
                        "set_preset_mode": _fan_set_preset_mode,
                    },
                )
            )

        # ---- switch 开关 ----
        for sid, field, name, key in _SWITCHES:
            if context.has_service(sid):
                entities.append(_make_switch(sid, field, name, key))

        # ---- select: 氛围灯亮度 / 节能设置阈值 ----
        for sid, field, name, key, category in (
            ("ambientLight", "level", "氛围灯亮度", "ambient_light_level", None),
            ("ecoSetting", "standbySet", "自动待机阈值", "eco_standby", "config"),
            ("ecoSetting", "autoSet", "自动运行阈值", "eco_auto", "config"),
        ):
            if context.has_service(sid):
                entities.append(
                    _make_enum_select(profile, sid, field, name, key, category)
                )

        # ---- button: 复位滤网 ----
        for sid, name, key in _RESET_BUTTONS:
            if context.has_service(sid):
                entities.append(_make_reset_button(sid, name, key))

        # ---- sensor ----
        for sid, field, name, key in _ENUM_SENSORS:
            if context.has_service(sid):
                entities.append(_make_enum_sensor(profile, sid, field, name, key))
        for sid, field, name, key, unit, device_class, state_class, category in _NUM_SENSORS:
            if context.has_service(sid):
                entities.append(
                    _make_num_sensor(
                        sid, field, name, key, unit, device_class, state_class, category
                    )
                )

        # ---- sensor(诊断): 定时任务（只读） ----
        if context.has_service("timer"):
            def timer_state(device: DeviceContext) -> Mapping[str, Any]:
                raw = device.value("timer", "timer")
                schedules = [item for item in raw if isinstance(item, Mapping)] \
                    if isinstance(raw, list) else []
                enabled = sum(
                    1 for item in schedules if _bool(item.get("enable")) is True
                )
                return {
                    "native_value": enabled,
                    "extra_state_attributes": {
                        "total": len(schedules),
                        "schedules": schedules,
                    },
                }

            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="timer_schedules",
                    name="定时任务",
                    state=timer_state,
                    metadata={"entity_category": "diagnostic"},
                )
            )

        # ---- binary_sensor: 故障 ----
        if context.has_service("commonFaultDetection"):
            def fault_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "is_on": _bool(device.value("commonFaultDetection", "status"))
                }

            entities.append(
                EntitySpec(
                    platform="binary_sensor",
                    key="fault",
                    name="故障",
                    state=fault_state,
                    metadata={"device_class": "problem"},
                )
            )

        return tuple(entities)


ADAPTER = Product2QQ4Adapter()
