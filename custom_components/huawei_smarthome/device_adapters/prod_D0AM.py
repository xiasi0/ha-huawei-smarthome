"""User-contributed protocol for Huawei product D0AM (HUAWEI PixLab V1 打印机).

产品: 打印机（HUAWEI PixLab V1）
厂商: 华为
型号: BiSheng-WNM / deviceTypeId A09 / platform HuaweiEco (protocolType WiFi)

═══════════════════════════════════════════════════════════════════
数据来源与验证状态
═══════════════════════════════════════════════════════════════════

字段名、取值范围与枚举含义全部取自该产品的物模型 (profile)：

    services: printerStatus / tonerStatus / printJobStatus / copyJobStatus /
              scanJobStatus / faultDetection / update / netStatus / netInfo

显示用的中文一律读物模型里的 ``descCh``，适配器不硬编码枚举文案，物模型改
文案时界面跟着变。

已在真机上核对的实时字段：``printerStatus``（mode / jobType）、
``copyJobStatus.status``、``faultDetection``（status / errorCode）、
``update.version``、``netStatus.status``、``tonerStatus``（四色 + combined）。

本适配器只声明只读实体。该产品物模型里可写字段很少，且都不适合在无实际
需求时下发，故未建控制实体：

  - ``update.action``（0检查新版本 / 1启动升级）：检查动作在设备上无可见
    效果，无法在真机上验证是否生效，因此不提供按钮。
  - ``cancelPrintJob``：取消打印任务需要任务 id，物模型未说明取值来源。
  - ``autoUpgradeTime.time`` / ``timeWindow.startTime``：写入型字段，物模型
    未给出取值格式（真机上报为 ``"10001200"`` 这类字符串，含义未确认）。

**未经真机验证的部分**：

  - ``tonerStatus`` 四个颜色的语义按物模型声明为「0=无, 1=有」，含义是否等价
    于「墨水余量告警」未实测，因此只作为打印机状态的属性展示，不单独建实体。
  - ``scanJobStatus`` 的扫描任务状态、``printJobStatus.pageIndex/pageCount``
    在无任务时设备上报的是占位值（如 ``{000:0,...}``），已按「无任务」处理；
    固件版本、扫描任务在设备休眠时不上报，此时实体状态为未知。

═══════════════════════════════════════════════════════════════════
核心服务（取自真机物模型）
═══════════════════════════════════════════════════════════════════

    printerStatus.mode      enum R  (0待机 1初始化 2工作中 3取消 4升级中 5休眠)
    printerStatus.jobType   enum R  (0无任务 1复印 2打印 3扫描 4清洁 5校准 6打印测试页)
    tonerStatus.*           bool R  (黑/红/蓝/黄 0无 1有, combined 0-15)
    printJobStatus.*        R       (pageIndex 1-999, pageCount 1-999, status string)
    copyJobStatus.status    enum R  (1队列中 … 7格式解析完成)
    scanJobStatus.status    enum R  (1队列中 … 8超时)
    faultDetection.*        R       (status 0正常 1异常, 以及 toner/drum/paper/cover 等明细)
    update.action           enum P  (0检查新版本 1启动升级)
    update.version          string R
    netStatus.status        bool R  (0未连云 1已连云)

═══════════════════════════════════════════════════════════════════
实体清单
═══════════════════════════════════════════════════════════════════

    sensor         printer_status    打印机状态（属性：任务类型、墨水明细）
    sensor         print_job         打印任务（属性：当前页/总页数）
    sensor         copy_job          复印任务
    sensor         scan_job          扫描任务
    sensor         firmware_version  固件版本
    binary_sensor  problem           故障汇总（属性：卡纸/缺墨/盖子等明细）
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_STATUS_SID = "printerStatus"


def _field(context: DeviceContext, sid: str, key: str) -> Mapping[str, Any]:
    """取物模型里某个字段的声明；没有就返回空表。"""

    for service in (context.profile or {}).get("services") or ():
        if not isinstance(service, Mapping) or service.get("serviceId") != sid:
            continue
        for item in service.get("characteristics") or ():
            if isinstance(item, Mapping) and item.get("characteristicName") == key:
                return item
    return {}


def _writable(context: DeviceContext, sid: str, key: str) -> bool:
    return "P" in str(_field(context, sid, key).get("permission") or "")


def _enum_values(context: DeviceContext, sid: str, key: str) -> set[str]:
    values = _field(context, sid, key).get("enumList") or ()
    return {
        str(item.get("enumVal"))
        for item in values
        if isinstance(item, Mapping) and item.get("enumVal") is not None
    }


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            return int(round(float(value.strip())))
        except (TypeError, ValueError):
            return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.strip() in {"1", "true", "True"}:
            return True
        if value.strip() in {"0", "false", "False"}:
            return False
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _enum_text(context: DeviceContext, sid: str, key: str, value: Any) -> str | None:
    """按物模型 ``descCh`` 把枚举值翻成中文；查不到就原样返回。"""

    if value is None:
        return None
    for item in _field(context, sid, key).get("enumList") or ():
        if isinstance(item, Mapping) and str(item.get("enumVal")) == str(value):
            return str(item.get("descCh") or item.get("descEn") or value)
    text = str(value).strip()
    return text or None


def _bool_text(value: Any) -> str | None:
    flag = _as_bool(value)
    return None if flag is None else ("是" if flag else "否")


def _ink_attributes(context: DeviceContext) -> dict[str, Any]:
    """四色墨水明细；语义按物模型声明（0=无, 1=有），只作属性展示。"""

    names = {
        "blackTonerStatus": "黑色墨水",
        "redTonerStatus": "红色墨水",
        "blueTonerStatus": "蓝色墨水",
        "yellowTonerStatus": "黄色墨水",
    }
    result: dict[str, Any] = {}
    for key, label in names.items():
        value = _as_int(context.value("tonerStatus", key))
        if value is not None:
            result[label] = "有" if value else "无"
    combined = _as_int(context.value("tonerStatus", "combinedTonerStatus"))
    if combined is not None:
        result["墨水组合状态"] = combined
    return result


def _fault_attributes(context: DeviceContext) -> dict[str, Any]:
    """故障明细：枚举型按物模型文案，布尔型翻成「是/否」。"""

    items = {
        "toner": "碳粉余量",
        "drum": "鼓盒寿命",
        "paper": "纸张",
        "cover": "机身盖子",
        "memory": "内存",
        "overheat": "机器过热",
        "fan": "风扇",
        "network": "无线网络",
        "temperature": "高温",
        "dsp": "DSP计算单元",
        "printData": "打印数据",
    }
    result: dict[str, Any] = {}
    for key, label in items.items():
        raw = context.value("faultDetection", key)
        if raw is None:
            continue
        text = _enum_text(context, "faultDetection", key, raw)
        if text is None:
            text = _bool_text(raw)
        if text is not None:
            result[label] = text
    for key, label in (("errorCode", "错误码"), ("warningCode", "警告码")):
        code = _as_int(context.value("faultDetection", key))
        if code is not None:
            result[label] = code
    return result


class ProductD0AMAdapter:
    """D0AM HUAWEI PixLab V1 打印机适配器。"""

    prod_id = "D0AM"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service(_STATUS_SID):
            return ()

        def printer_status(device: DeviceContext) -> Mapping[str, Any]:
            attributes: dict[str, Any] = {
                "任务类型": _enum_text(
                    device, _STATUS_SID, "jobType", device.value(_STATUS_SID, "jobType")
                ),
                "状态码": _as_int(device.value(_STATUS_SID, "mode")),
            }
            attributes.update(_ink_attributes(device))
            return {
                "native_value": _enum_text(
                    device, _STATUS_SID, "mode", device.value(_STATUS_SID, "mode")
                ),
                "extra_state_attributes": attributes,
            }

        def print_job(device: DeviceContext) -> Mapping[str, Any]:
            status = device.value("printJobStatus", "status")
            index = _as_int(device.value("printJobStatus", "pageIndex"))
            total = _as_int(device.value("printJobStatus", "pageCount"))
            text = str(status).strip() if status else ""
            if not text or text.startswith("{"):
                text = "无任务"  # 无任务时设备上报 {000:0,...} 这类占位串
            return {
                "native_value": text,
                "extra_state_attributes": {
                    "当前页": index,
                    "总页数": total,
                },
            }

        def job_status(device: DeviceContext, sid: str) -> Mapping[str, Any]:
            raw = device.value(sid, "status")
            return {
                "native_value": _enum_text(device, sid, "status", raw),
                "extra_state_attributes": {"状态码": _as_int(raw)},
            }

        def firmware_version(device: DeviceContext) -> Mapping[str, Any]:
            version = device.value("update", "version")
            text = str(version).strip() if version is not None else ""
            return {"native_value": text or None}

        def problem(device: DeviceContext) -> Mapping[str, Any]:
            return {
                "is_on": _as_bool(device.value("faultDetection", "status")),
                "extra_state_attributes": _fault_attributes(device),
            }

        entities: list[EntitySpec] = [
            EntitySpec(
                platform="sensor",
                key="printer_status",
                name="打印机状态",
                state=printer_status,
                metadata={"icon": "mdi:printer"},
            ),
            EntitySpec(
                platform="sensor",
                key="print_job",
                name="打印任务",
                state=print_job,
                metadata={"icon": "mdi:file-document-outline"},
            ),
            EntitySpec(
                platform="sensor",
                key="copy_job",
                name="复印任务",
                state=lambda device: job_status(device, "copyJobStatus"),
                metadata={"icon": "mdi:content-copy"},
            ),
            EntitySpec(
                platform="sensor",
                key="scan_job",
                name="扫描任务",
                state=lambda device: job_status(device, "scanJobStatus"),
                metadata={"icon": "mdi:scanner"},
            ),
            EntitySpec(
                platform="sensor",
                key="firmware_version",
                name="固件版本",
                state=firmware_version,
                metadata={"icon": "mdi:chip"},
            ),
            EntitySpec(
                platform="binary_sensor",
                key="problem",
                name="故障",
                state=problem,
                metadata={"device_class": "problem"},
            ),
        ]

        return tuple(entities)


ADAPTER = ProductD0AMAdapter()
