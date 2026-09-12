"""User-contributed protocol for Huawei product 208B (叶绿体 门铃 / 顺德智勤).

设备类型: 门铃 (Door Bell), 型号 CDB-Q30I
核心服务:
   switch1..switch8.on  bool RW (1=开, 0=关)  8 路无线开关
   volume.value         int  RW (0-100 step25) 音量
   bellServ.value       enum RW (0-33) 铃声选择
   muteOpServ.value     bool RW 静音开关

本适配器暴露:
   1. 8 个 switch (switch1..switch8)
   2. number 音量
   3. select 铃声
   4. switch 静音开关
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_SWITCH_SERVICES = [f"switch{i}" for i in range(1, 9)]

_BELL_OPTIONS = [
    "暂无", "叮咚两声", "和弦音", "意大利波尔卡", "卡门序曲",
    "老式铃声", "钢琴音135i", "拉德斯基进行曲", "哆唻咪", "回家",
    "西班牙女郎", "茶花女", "土耳其进行曲", "啊朋友", "金婚氏",
    "圣诞快乐", "孤独的牧羊人", "胡桃夹子", "爱丽丝", "回忆",
    "威尔逊进行曲", "生日快乐", "铃儿响叮当", "苏三娜", "小步舞曲",
    "欢快铃声", "倒计时1", "倒计时2", "你好欢迎光临", "愉快韵律",
    "时钟滴答", "滴滴滴", "报警声", "警报声",
]
_OPTION_TO_VAL = {name: i for i, name in enumerate(_BELL_OPTIONS)}


def _as_bool(value: Any) -> bool | None:
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


class Product208BAdapter:
    """208B 叶绿体门铃适配器。"""

    prod_id = "208B"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service("switch1"):
            return ()

        def _switch_spec(sid: str, index: int) -> EntitySpec:
            def state(device: DeviceContext) -> Mapping[str, Any]:
                return {"is_on": _as_bool(device.value(sid, "on"))}

            async def turn_on(device: DeviceContext, _data: Mapping[str, Any]) -> None:
                await device.async_send_service(sid, {"on": 1})

            async def turn_off(device: DeviceContext, _data: Mapping[str, Any]) -> None:
                await device.async_send_service(sid, {"on": 0})

            return EntitySpec(
                platform="switch",
                key=sid,
                name=f"开关{index}",
                state=state,
                actions={"turn_on": turn_on, "turn_off": turn_off},
            )

        def volume_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"native_value": _as_int(device.value("volume", "value"))}

        async def set_volume(device: DeviceContext, data: Mapping[str, Any]) -> None:
            value = data.get("value")
            if value is None:
                return
            await device.async_send_service(
                "volume", {"value": max(0, min(100, int(round(float(value)))))}
            )

        def bell_state(device: DeviceContext) -> Mapping[str, Any]:
            val = _as_int(device.value("bellServ", "value"))
            return {
                "current_option": _BELL_OPTIONS[val]
                if val is not None and 0 <= val < len(_BELL_OPTIONS)
                else _BELL_OPTIONS[0]
            }

        async def select_bell(device: DeviceContext, data: Mapping[str, Any]) -> None:
            val = _OPTION_TO_VAL.get(str(data.get("option")))
            if val is None:
                raise ValueError(f"unsupported option: {data.get('option')}")
            await device.async_send_service("bellServ", {"value": val})

        def mute_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"is_on": _as_bool(device.value("muteOpServ", "value"))}

        async def mute_on(device: DeviceContext, _data: Mapping[str, Any]) -> None:
            await device.async_send_service("muteOpServ", {"value": 1})

        async def mute_off(device: DeviceContext, _data: Mapping[str, Any]) -> None:
            await device.async_send_service("muteOpServ", {"value": 0})

        specs = [_switch_spec(sid, i) for i, sid in enumerate(_SWITCH_SERVICES, start=1)]
        specs.append(
            EntitySpec(
                platform="number",
                key="volume",
                name="音量",
                state=volume_state,
                metadata={"min": 0, "max": 100, "step": 25, "unit": "%"},
                actions={"set_value": set_volume},
            )
        )
        specs.append(
            EntitySpec(
                platform="select",
                key="bell",
                name="铃声",
                state=bell_state,
                metadata={"options": _BELL_OPTIONS},
                actions={"select_option": select_bell},
            )
        )
        specs.append(
            EntitySpec(
                platform="switch",
                key="mute",
                name="静音",
                state=mute_state,
                actions={"turn_on": mute_on, "turn_off": mute_off},
            )
        )
        return tuple(specs)


ADAPTER = Product208BAdapter()


