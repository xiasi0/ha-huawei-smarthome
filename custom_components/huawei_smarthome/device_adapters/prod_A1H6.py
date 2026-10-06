"""九阳智能养生壶 A1H6 (K15D-WY520(HM)) 适配文件 - 恢复全部实时状态读取"""
from __future__ import annotations
from collections.abc import Mapping
from typing import Any
from .api import EntitySpec
from .context import DeviceContext

# 工作状态简化映射：关机/待机/工作中
WORK_STATUS_MAP = {
    0: "关机",
    1: "待机",
    3: "工作中",
    4: "工作中",
    5: "工作中",
    6: "工作中",
    7: "工作中",
    8: "工作中",
}

# 食谱功能码映射（用户实测校准后的真实值，空闲时显示无）
MODE_NAME_MAP = {
    0: "无",
    1: "烧水",
    2: "保温",
    4: "花茶",
    5: "银耳",
    6: "雪梨",
    7: "煲汤",
    8: "药膳",
    9: "粥品",
    10: "冲奶",
}

# 可手动选择的模式选项及对应功能码
MODE_SELECT_OPTIONS = (
    "无", "烧水", "保温", "花茶", "银耳", "雪梨", "煲汤", "药膳", "粥品", "冲奶"
)
MODE_START_CODE = {
    "烧水": 1,
    "保温": 2,
    "花茶": 4,
    "银耳": 5,
    "雪梨": 6,
    "煲汤": 7,
    "药膳": 8,
    "粥品": 9,
    "冲奶": 10,
}

# 故障码映射
ERROR_CODE_MAP = {
    0: "正常",
    1: "提壶或器件故障",
    2: "传感器短路",
    3: "干烧保护(>120℃)",
    4: "长时间煮水超30分钟",
    5: "过零丢失",
    6: "电压异常",
    7: "通信错误",
}


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


class ProductA1H6Adapter:
    """九阳养生壶A1H6实体适配器"""
    prod_id = "A1H6"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None:
            return ()

        entities: list[EntitySpec] = []

        if context.has_service("devStatus"):
            # 电源状态（根据devStatus里的workStatus判断，和水温同服务，实时同步）
            entities.append(
                EntitySpec(
                    platform="binary_sensor",
                    key="power_state",
                    name="电源状态",
                    state=lambda device: {
                        "is_on": _number(device.value("devStatus", "workStatus")) != 0
                    },
                )
            )

            # 工作状态传感器
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="work_status",
                    name="工作状态",
                    state=lambda device: {
                        "native_value": WORK_STATUS_MAP.get(
                            _number(device.value("devStatus", "workStatus")),
                            "未知"
                        )
                    },
                )
            )

            # 工作模式（已校准真实功能码映射，未识别的大码统一显示自选）
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="current_mode",
                    name="工作模式",
                    state=lambda device: {
                        "native_value": MODE_NAME_MAP.get(
                            _number(device.value("devStatus", "funcCode")),
                            "自选"
                        )
                    },
                )
            )

            # 当前水温传感器
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="current_temp",
                    name="当前水温",
                    state=lambda device: {
                        "native_value": _number(device.value("devStatus", "temperature")),
                        "unit_of_measurement": "℃",
                    },
                )
            )

            # 保温温度调节滑块
            async def set_warm_temp(device: DeviceContext, data: Mapping[str, Any]) -> None:
                value = _number(data.get("value"))
                if value is None:
                    raise ValueError("温度参数错误")
                await device.async_send_service(
                    "resetHoldingTemperature",
                    {"warmTemp": int(value)}
                )
            entities.append(
                EntitySpec(
                    platform="number",
                    key="warm_temp",
                    name="保温温度",
                    state=lambda device: {
                        "native_value": _number(device.value("devStatus", "warmTemp")) or 65
                    },
                    metadata={"min": 40, "max": 90, "step": 5, "unit": "℃"},
                    actions={"set_value": set_warm_temp},
                )
            )

            # 电源开关：关机直接调用stop服务，参数格式已校准
            async def turn_off(device: DeviceContext, _data: Mapping[str, Any]) -> None:
                await device.async_send_service("stop", {"funcCode": 0})
            entities.append(
                EntitySpec(
                    platform="switch",
                    key="power",
                    name="电源开关",
                    state=lambda device: {
                        "is_on": _number(device.value("devStatus", "workStatus")) != 0
                    },
                    actions={
                        "turn_off": turn_off,
                    },
                )
            )

            # 手动选择模式直接启动（已校准整数功能码，原生直连）
            async def select_mode(device: DeviceContext, data: Mapping[str, Any]) -> None:
                option = str(data.get("option"))
                if option not in MODE_START_CODE:
                    raise ValueError(f"未知模式: {option}")
                await device.async_send_service(
                    "start",
                    {"funcCode": MODE_START_CODE[option]}
                )
            entities.append(
                EntitySpec(
                    platform="select",
                    key="cook_mode",
                    name="选择模式启动",
                    state=lambda device: {
                        "current_option": next(
                            (
                                label for label, code in MODE_START_CODE.items()
                                if _number(device.value("devStatus", "funcCode")) == code
                            ),
                            "无"
                        )
                    },
                    metadata={"options": MODE_SELECT_OPTIONS},
                    actions={"select_option": select_mode},
                )
            )

            # 保温时长显示
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="warm_time",
                    name="保温时长",
                    state=lambda device: {
                        "native_value": _number(device.value("devStatus", "warmTime")),
                        "unit_of_measurement": "分钟",
                    },
                )
            )

            # 剩余熬煮时间
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="left_cook_time",
                    name="剩余熬煮时间",
                    state=lambda device: {
                        "native_value": _number(device.value("devStatus", "leftCookTime")),
                        "unit_of_measurement": "分钟",
                    },
                )
            )

        # 故障状态传感器
        if context.has_service("faultDetection"):
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="fault_status",
                    name="故障状态",
                    state=lambda device: {
                        "native_value": ERROR_CODE_MAP.get(
                            _number(device.value("faultDetection", "code")),
                            "正常"
                        )
                    },
                )
            )

        return tuple(entities)


ADAPTER = ProductA1H6Adapter()
#（注：内容由AI生成）
