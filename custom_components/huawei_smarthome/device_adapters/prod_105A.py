"""User-contributed protocol for Huawei product 105A (杜亚电动窗帘 DH3).

设备类型: 窗帘 (Curtain), 型号 DH3
制造商: 杜亚 (DOOYA)

核心服务:
   motor.mode                  int  W   电机命令
                                         1=开, 2=关, 3=停止
                                         4=清除行程, 5=运行到最佳行程点
                                         6=设置最佳行程点
                                         7=设置当前位置为上行程点
                                         8=设置当前位置为下行程点
                                         9=设置目标行程百分比
                                         10=设置电机反向
                                         11=设置百叶角度
                                         12=设置角度修正值
   motor.direction             int  RW  电机方向(1=正向顺时针, 2=反向逆时针)
   openLevel.targetLevel       int  RW  目标开合度 0-100 (%)
   openLevel.currentLevel      int  R   当前开合度 0-100 (%)

本适配器暴露:
   1. cover   窗帘 (开 / 关 / 停止 / 设置位置)
   2. select  电机方向
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext


# ---- 枚举映射 ------------------------------------------------------------

_DIRECTION_OPTIONS = ["正向(顺时针)", "反向(逆时针)"]
_DIRECTION_NAME_TO_VAL = {
    "正向(顺时针)": 1,
    "反向(逆时针)": 2,
}
_DIRECTION_VAL_TO_NAME = {
    1: "正向(顺时针)",
    2: "反向(逆时针)",
}

# motor.mode 常量
_MODE_OPEN = 1
_MODE_CLOSE = 2
_MODE_STOP = 3


# ---- 工具函数 ------------------------------------------------------------

def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, str):
        try:
            return int(round(float(value.strip())))
        except (TypeError, ValueError):
            return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


# ---- 动作函数 ------------------------------------------------------------

async def _open_cover(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("motor", {"mode": _MODE_OPEN})


async def _close_cover(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("motor", {"mode": _MODE_CLOSE})


async def _stop_cover(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("motor", {"mode": _MODE_STOP})


async def _set_position(context: DeviceContext, data: Mapping[str, Any]) -> None:
    position = _as_int(data.get("position"))
    if position is None:
        return
    position = max(0, min(100, position))
    await context.async_send_service("openLevel", {"targetLevel": position})


async def _select_direction(context: DeviceContext, data: Mapping[str, Any]) -> None:
    val = _DIRECTION_NAME_TO_VAL.get(str(data.get("option")))
    if val is None:
        raise ValueError(f"unsupported direction: {data.get('option')}")
    await context.async_send_service("motor", {"direction": val})


# ---- 适配器 --------------------------------------------------------------

class Product105AAdapter:
    """105A 杜亚电动窗帘 DH3 适配器。"""

    prod_id = "105A"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service("openLevel"):
            return ()

        # ---- 状态读取 ----------------------------------------------------

        def curtain_state(device: DeviceContext) -> Mapping[str, Any]:
            current = _as_int(device.value("openLevel", "currentLevel"))
            target = _as_int(device.value("openLevel", "targetLevel"))
            return {
                "current_position": current,
                "target_position": target,
                "is_closed": current == 0,
            }

        def direction_state(device: DeviceContext) -> Mapping[str, Any]:
            val = _as_int(device.value("motor", "direction"))
            return {
                "current_option": _DIRECTION_VAL_TO_NAME.get(
                    val, _DIRECTION_OPTIONS[0]
                )
            }

        # ---- 实体列表 ----------------------------------------------------

        return (
            EntitySpec(
                platform="cover",
                key="curtain",
                name="窗帘",
                state=curtain_state,
                metadata={"device_class": "curtain"},
                actions={
                    "open_cover": _open_cover,
                    "close_cover": _close_cover,
                    "stop_cover": _stop_cover,
                    "set_position": _set_position,
                },
            ),
            EntitySpec(
                platform="select",
                key="direction",
                name="电机方向",
                state=direction_state,
                metadata={"options": _DIRECTION_OPTIONS},
                actions={"select_option": _select_direction},
            ),
        )


ADAPTER = Product105AAdapter()