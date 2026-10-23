"""User-contributed protocol for Huawei product M00D (HUAWEI Scale 3, HEM-B19).

设备: 华为智能体脂秤 3（HUAWEI Scale 3，型号 ``HEM-B19``，deviceTypeName=体重秤）
prod_id: ``M00D``
Profile: 公开 Profile **只有元数据**（``uiType=H5``，
``uriInfo.uri=M00D/h5_001/index.html``），没有 ``services`` /
``characteristics``。因此本适配器完全依据运行时 ``devMeasureData`` 状态建模，
不依赖 Profile 字段声明；字段名、缩放和语义均来自真机脱敏快照与公开资料。

本适配器是只读的，不提供任何写入动作（无 switch/select/number/button），
也不读取或输出原始 ``uid`` / ``id``。只导入 ``.api``、``.context`` 和标准库，
不导入 Home Assistant。

暴露的 22 个实体
================
13 个身体成分测量 sensor + 1 个测量时间戳 sensor + 4 个档案/用户 diagnostic
sensor + 2 个固件 diagnostic sensor + 2 个 diagnostic binary_sensor：

    weight                 体重                 kg       device_class=weight
    body_fat               体脂率               %
    bmi                    BMI                  kg/m²
    body_water             体水分率             %
    visceral_fat           内脏脂肪等级         无单位
    muscle_mass            肌肉量（瘦体重）      kg       对应 slm
    skeletal_muscle_mass   骨骼肌量             kg       对应 smm
    protein_mass           蛋白质质量           kg       对应 pm
    bone_salt              骨盐量               kg       对应 msw
    basal_metabolism       基础代谢             kcal     对应 kcal（假设见下）
    body_age               身体年龄             岁       对应 bodyAge
    body_score             身体得分             无单位   对应 BodyScore
    heart_rate             心率                 bpm      对应 hr
    measurement_time       测量时间             timestamp（dateTime，回退上报时间）
    height                 身高                 cm       diagnostic
    profile_age            测量档案年龄         岁       diagnostic
    measurement_gender     测量用户性别         无单位    diagnostic
    measurement_user       测量用户             sha256(uid)[:8]，diagnostic
    firmware_version       固件版本             无单位    diagnostic
    firmware_latest        最新固件版本         无单位    diagnostic
    firmware_update_available  固件更新可用     binary_sensor / update
    connection_state       连接状态             binary_sensor / connectivity

字段换算（依据与置信度）
========================
真机快照 ``state_M00D.json``（2026-10-18）: ``weight=9740``、
``unit=1``、``weight_division=2``、``bmi=264``、``height=192``，
其余字段见下。所有原始值在真机 state 中都是字符串，解析层统一容忍
str/int/float，并拒绝 bool / NaN / Inf。

    字段            原始值    换算          结果           置信度 / 依据
    weight          9740      /100          97.40 kg       高：97.40 / 1.92² = 26.42，
                                                           与 bmi=264（26.4）互证
    fat             254       /10           25.4 %         高：与 FFM 推算 25.3% 相差 0.1pp
    bmi             264       /10           26.4           高：与 weight/height 互证
    water           492       /10           49.2 %         高：水分+蛋白质 ≈ slm 闭合
    vfr             120       /10           12.0 级        中高：典型范围 1~30，无 App 对照
    slm             6893      /100          68.93 kg       高：slm + msw = 72.76 kg FFM，
                                                           反推体脂率 25.3%
    smm             3987      /100          39.87 kg       中高：数值范围合理，无独立互证
    pm              2088      /100          20.88 kg       中高：脂肪+水分+蛋白质+骨盐
                                                           = 97.37 ≈ 97.40 kg；按百分比
                                                           解释则不闭合
    msw             383       /100          3.83 kg        中高：成分求和闭合；
                                                           Health Kit boneSalt 公开范围 0.5~5 kg
    kcal            2111      原值          2111 kcal      中：推断为基础代谢；也可能是
                                                           每日建议摄入（实体属性标注假设）
    bodyAge         27        原值          27 岁          中高：与档案 age 相同，可能巧合
    BodyScore       72        原值          72 分          高：0~100 语义明确（大写 B/S）
    hr              88        原值          88 bpm         高：量纲合理
    height          192       原值          192 cm         高：与 BMI 互证
    age             27        原值          27 岁          高：档案年龄，与 bodyAge 区分
    gender          1         查表          男             中高：Health Kit 编码
                                                           0=女,1=男,2=保密,-1=未设置
    dateTime        1792302363000  毫秒 epoch  2026-10-18T05:46:03Z
                                                           高：13 位毫秒，限制在 2000~2100 年

未暴露且语义未证实: ``res``（疑似阻抗，单位未知）、``pole``、``conflictFlag``、
``uid`` / ``id`` 原值（隐私）。多账户、单位切换、OTA 触发等写能力全部未验证，
因此不实现。

离线可用性（关键设计）
======================
体脂秤绝大多数时间处于云端离线状态（``context.available=False``），但
``devMeasureData`` 保留了最后一次测量。若沿用默认可用性，所有实体在两次称重
之间都会变成 unavailable，最后一次测量不可见。因此：

- 测量类和档案类实体使用 ``device.available or has_measurement(device)``：
  在线时可用（即使尚无数据，显示 unknown）；离线但已有测量时保持可用，
  显示最后一次测量；离线且从未测量时 unavailable。
- 每个测量实体附带 ``measurement_time`` 属性；另有独立的 timestamp 实体，
  优先解析 ``devMeasureData.dateTime``，缺失时回退服务上报时间。
- 固件实体使用“在线或字段已缓存”可用性。
- ``connection_state`` 始终可用，否则离线时它自己也会变成 unavailable，
  无法显示 off。

注意：离线期间实体显示的是历史测量值，不会自动刷新。自动化应同时检查
``measurement_time`` 的新鲜度，避免把旧测量当成新测量。
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_PROD_ID = "M00D"

_MEASURE_SID = "devMeasureData"
_OTA_SID = "devOtaInfo"

# Huawei Health Kit 个人资料性别编码：0=女, 1=男, 2=保密, -1=未设置。
# 仅作为中等置信度映射；设备协议本身未公开该枚举。
_GENDER_LABELS = {0: "女", 1: "男", 2: "保密", -1: "未设置"}

_MIN_EPOCH_SECONDS = 946684800  # 2000-01-01T00:00:00Z
_MAX_EPOCH_SECONDS = 4102444800  # 2100-01-01T00:00:00Z


# ---------------------------------------------------------------------------
# 基础解析
# ---------------------------------------------------------------------------


def _number(value: Any) -> int | float | None:
    """容忍 str/int/float 的数值解析；拒绝 bool/NaN/Inf。"""

    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return int(number) if number.is_integer() else number


def _scaled(value: Any, divisor: float, decimals: int) -> float | int | None:
    number = _number(value)
    if number is None:
        return None
    result = round(number / divisor, decimals)
    if decimals == 0:
        return int(result) if float(result).is_integer() else result
    return result


def _epoch_datetime(value: Any) -> datetime | None:
    """解析秒或毫秒 epoch；13 位值按毫秒处理，超出 2000~2100 视为无效。"""

    number = _number(value)
    if number is None:
        return None
    seconds = float(number)
    if seconds >= 100_000_000_000:  # 12~13 位毫秒
        seconds /= 1000.0
    if not (_MIN_EPOCH_SECONDS <= seconds <= _MAX_EPOCH_SECONDS):
        return None
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def _measurement_time(device: DeviceContext) -> datetime | None:
    """优先使用 devMeasureData.dateTime，缺失时回退到服务上报时间。"""

    moment = _epoch_datetime(device.value(_MEASURE_SID, "dateTime"))
    if moment is not None:
        return moment
    return device.service_updated_at(_MEASURE_SID)


def _measurement_time_iso(device: DeviceContext) -> str | None:
    moment = _measurement_time(device)
    return moment.isoformat() if moment is not None else None


def _has_measurement(device: DeviceContext) -> bool:
    return (
        _number(device.value(_MEASURE_SID, "weight")) is not None
        or _number(device.value(_MEASURE_SID, "dateTime")) is not None
    )


# ---------------------------------------------------------------------------
# 可用性策略
# ---------------------------------------------------------------------------


def _measurement_available(device: DeviceContext) -> bool:
    """在线，或虽离线但已有最后一次测量 -> 实体可用。"""

    return device.available or _has_measurement(device)


def _always_available(_device: DeviceContext) -> bool:
    """连接状态实体必须始终可用，否则离线时无法显示 off。"""

    return True


def _service_data_available(sid: str, *fields: str) -> Callable[[DeviceContext], bool]:
    """静态信息：在线，或对应服务字段已经缓存 -> 可用。"""

    def available(device: DeviceContext) -> bool:
        if device.available:
            return True
        return any(device.value(sid, field) is not None for field in fields)

    return available


# ---------------------------------------------------------------------------
# 实体构造
# ---------------------------------------------------------------------------


def _measurement_attributes(device: DeviceContext, field: str) -> dict[str, Any]:
    return {
        "raw_value": device.value(_MEASURE_SID, field),
        "measurement_time": _measurement_time_iso(device),
    }


def _make_measurement_sensor(
    *,
    key: str,
    name: str,
    field: str,
    divisor: float,
    decimals: int,
    unit: str | None = None,
    device_class: str | None = None,
    state_class: str | None = "measurement",
    entity_category: str | None = None,
    extra_attributes: Callable[[DeviceContext], Mapping[str, Any]] | None = None,
) -> EntitySpec:
    def state(device: DeviceContext) -> Mapping[str, Any]:
        attributes = _measurement_attributes(device, field)
        if extra_attributes is not None:
            attributes.update(extra_attributes(device))
        return {
            "native_value": _scaled(
                device.value(_MEASURE_SID, field), divisor, decimals
            ),
            "extra_state_attributes": attributes,
        }

    metadata: dict[str, Any] = {}
    if unit is not None:
        metadata["unit"] = unit
    if device_class is not None:
        metadata["device_class"] = device_class
    if state_class is not None:
        metadata["state_class"] = state_class
    if entity_category is not None:
        metadata["entity_category"] = entity_category

    return EntitySpec(
        platform="sensor",
        key=key,
        name=name,
        state=state,
        metadata=metadata,
        availability=_measurement_available,
    )


def _make_string_sensor(
    *,
    key: str,
    name: str,
    state_fn: Callable[[DeviceContext], Mapping[str, Any]],
    entity_category: str = "diagnostic",
    availability: Callable[[DeviceContext], bool] = _measurement_available,
) -> EntitySpec:
    return EntitySpec(
        platform="sensor",
        key=key,
        name=name,
        state=state_fn,
        metadata={"entity_category": entity_category},
        availability=availability,
    )


# ---------------------------------------------------------------------------
# 各实体的附加属性
# ---------------------------------------------------------------------------


def _weight_extra(device: DeviceContext) -> Mapping[str, Any]:
    return {
        "unit_code": _number(device.value(_MEASURE_SID, "unit")),
        "weight_division": _number(
            device.value(_MEASURE_SID, "weight_division")
        ),
    }


def _visceral_fat_extra(_device: DeviceContext) -> Mapping[str, Any]:
    return {"level": True, "scale": "1-30 typical"}


def _muscle_extra(_device: DeviceContext) -> Mapping[str, Any]:
    return {
        "metric": "soft_lean_mass",
        "note": "slm = fat-free mass - bone salt",
    }


def _protein_extra(device: DeviceContext) -> Mapping[str, Any]:
    protein_raw = _number(device.value(_MEASURE_SID, "pm"))
    weight_raw = _number(device.value(_MEASURE_SID, "weight"))
    rate = None
    if protein_raw is not None and weight_raw not in (None, 0):
        # 两个原始值同为 0.01 kg 单位，比例与缩放无关。
        rate = round(protein_raw / weight_raw * 100, 2)
    return {
        "protein_rate_percent": rate,
        "assumption": "pm treated as protein mass in 0.01 kg",
    }


def _basal_metabolism_extra(_device: DeviceContext) -> Mapping[str, Any]:
    return {
        "assumption": "kcal treated as a daily basal-metabolism estimate",
    }


def _body_age_extra(device: DeviceContext) -> Mapping[str, Any]:
    return {"profile_age": _number(device.value(_MEASURE_SID, "age"))}


# ---------------------------------------------------------------------------
# 特殊状态函数
# ---------------------------------------------------------------------------


def _measurement_time_state(device: DeviceContext) -> Mapping[str, Any]:
    raw = device.value(_MEASURE_SID, "dateTime")
    moment = _epoch_datetime(raw)
    source = "devMeasureData.dateTime"
    if moment is None:
        moment = device.service_updated_at(_MEASURE_SID)
        source = "service_reported_timestamp" if moment is not None else None
    return {
        "native_value": moment,
        "extra_state_attributes": {
            "raw_date_time": raw,
            "source": source,
        },
    }


def _gender_state(device: DeviceContext) -> Mapping[str, Any]:
    raw = _number(device.value(_MEASURE_SID, "gender"))
    code = int(raw) if raw is not None else None
    label = _GENDER_LABELS.get(code) if code is not None else None
    if code is not None and label is None:
        label = "未知"
    return {
        "native_value": label,
        "extra_state_attributes": {
            "raw_value": device.value(_MEASURE_SID, "gender"),
            "measurement_time": _measurement_time_iso(device),
            "mapping_confidence": "medium (Huawei Health Kit: 0=female,1=male,2=secret)",
        },
    }


def _user_state(device: DeviceContext) -> Mapping[str, Any]:
    """仅暴露 uid 的 SHA-256 前 8 位，绝不输出原始 uid/id。"""

    raw = device.value(_MEASURE_SID, "uid")
    token = None
    if isinstance(raw, (str, int, float)) and str(raw).strip():
        token = hashlib.sha256(str(raw).strip().encode("utf-8")).hexdigest()[:8]
    return {
        "native_value": token,
        "extra_state_attributes": {
            "fingerprint": "sha256(uid)[:8]",
            "raw_identifier_exposed": False,
            "measurement_time": _measurement_time_iso(device),
            "identifier_confidence": "low: uid vs id semantics unverified",
        },
    }


def _firmware_state(field: str) -> Callable[[DeviceContext], Mapping[str, Any]]:
    def state(device: DeviceContext) -> Mapping[str, Any]:
        raw = device.value(_OTA_SID, field)
        text = str(raw) if raw is not None and str(raw).strip() else None
        return {
            "native_value": text,
            "extra_state_attributes": {"raw_value": raw},
        }

    return state


def _ota_update_state(device: DeviceContext) -> Mapping[str, Any]:
    current = device.value(_OTA_SID, "fwCurVer")
    latest = device.value(_OTA_SID, "fwNewVer")
    if current is None or latest is None or not str(current).strip() or not str(
        latest
    ).strip():
        return {"is_on": None}
    return {"is_on": str(latest) != str(current)}


def _connectivity_state(device: DeviceContext) -> Mapping[str, Any]:
    return {"is_on": device.available}


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class ProductM00DAdapter:
    """M00D 华为智能体脂秤 3：只读测量实体。"""

    prod_id = _PROD_ID

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None:
            return ()

        # 注意：这里**不**用 context.has_service("devMeasureData") 做门控。
        # 实体平台只在 config entry setup 时枚举一次；若开机时设备离线且
        # 尚未收到测量数据，按服务门控会导致实体永远不出现。所有实体
        # 无条件声明，由 availability 与 state(None) 处理“尚无数据”。
        return (
            # ---- 核心身体成分（正常实体） ----
            _make_measurement_sensor(
                key="weight",
                name="体重",
                field="weight",
                divisor=100.0,
                decimals=2,
                unit="kg",
                device_class="weight",
                extra_attributes=_weight_extra,
            ),
            _make_measurement_sensor(
                key="body_fat",
                name="体脂率",
                field="fat",
                divisor=10.0,
                decimals=1,
                unit="%",
            ),
            _make_measurement_sensor(
                key="bmi",
                name="BMI",
                field="bmi",
                divisor=10.0,
                decimals=1,
                unit="kg/m²",
            ),
            _make_measurement_sensor(
                key="body_water",
                name="体水分率",
                field="water",
                divisor=10.0,
                decimals=1,
                unit="%",
            ),
            _make_measurement_sensor(
                key="visceral_fat",
                name="内脏脂肪等级",
                field="vfr",
                divisor=10.0,
                decimals=1,
                extra_attributes=_visceral_fat_extra,
            ),
            _make_measurement_sensor(
                key="muscle_mass",
                name="肌肉量（瘦体重）",
                field="slm",
                divisor=100.0,
                decimals=2,
                unit="kg",
                extra_attributes=_muscle_extra,
            ),
            _make_measurement_sensor(
                key="skeletal_muscle_mass",
                name="骨骼肌量",
                field="smm",
                divisor=100.0,
                decimals=2,
                unit="kg",
            ),
            _make_measurement_sensor(
                key="protein_mass",
                name="蛋白质质量",
                field="pm",
                divisor=100.0,
                decimals=2,
                unit="kg",
                extra_attributes=_protein_extra,
            ),
            _make_measurement_sensor(
                key="bone_salt",
                name="骨盐量",
                field="msw",
                divisor=100.0,
                decimals=2,
                unit="kg",
            ),
            _make_measurement_sensor(
                key="basal_metabolism",
                name="基础代谢",
                field="kcal",
                divisor=1.0,
                decimals=0,
                unit="kcal",
                extra_attributes=_basal_metabolism_extra,
            ),
            _make_measurement_sensor(
                key="body_age",
                name="身体年龄",
                field="bodyAge",
                divisor=1.0,
                decimals=0,
                unit="岁",
                extra_attributes=_body_age_extra,
            ),
            _make_measurement_sensor(
                key="body_score",
                name="身体得分",
                field="BodyScore",
                divisor=1.0,
                decimals=0,
            ),
            _make_measurement_sensor(
                key="heart_rate",
                name="心率",
                field="hr",
                divisor=1.0,
                decimals=0,
                unit="bpm",
            ),
            EntitySpec(
                platform="sensor",
                key="measurement_time",
                name="测量时间",
                state=_measurement_time_state,
                metadata={"device_class": "timestamp"},
                availability=_measurement_available,
            ),
            # ---- 档案 / 诊断（诊断实体） ----
            _make_measurement_sensor(
                key="height",
                name="身高",
                field="height",
                divisor=1.0,
                decimals=0,
                unit="cm",
                device_class="distance",
                state_class=None,
                entity_category="diagnostic",
            ),
            _make_measurement_sensor(
                key="profile_age",
                name="测量档案年龄",
                field="age",
                divisor=1.0,
                decimals=0,
                unit="岁",
                state_class=None,
                entity_category="diagnostic",
            ),
            _make_string_sensor(
                key="measurement_gender",
                name="测量用户性别",
                state_fn=_gender_state,
            ),
            _make_string_sensor(
                key="measurement_user",
                name="测量用户",
                state_fn=_user_state,
            ),
            _make_string_sensor(
                key="firmware_version",
                name="固件版本",
                state_fn=_firmware_state("fwCurVer"),
                availability=_service_data_available(_OTA_SID, "fwCurVer"),
            ),
            _make_string_sensor(
                key="firmware_latest",
                name="最新固件版本",
                state_fn=_firmware_state("fwNewVer"),
                availability=_service_data_available(_OTA_SID, "fwNewVer"),
            ),
            EntitySpec(
                platform="binary_sensor",
                key="firmware_update_available",
                name="固件更新可用",
                state=_ota_update_state,
                metadata={
                    "device_class": "update",
                    "entity_category": "diagnostic",
                },
                availability=_service_data_available(
                    _OTA_SID, "fwCurVer", "fwNewVer"
                ),
            ),
            EntitySpec(
                platform="binary_sensor",
                key="connection_state",
                name="连接状态",
                state=_connectivity_state,
                metadata={
                    "device_class": "connectivity",
                    "entity_category": "diagnostic",
                },
                availability=_always_available,
            ),
        )


ADAPTER = ProductM00DAdapter()
