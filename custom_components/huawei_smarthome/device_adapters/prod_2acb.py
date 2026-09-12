"""User-contributed protocol for Huawei product 2ACB (领普科技 门铃).

设备类型: 门铃 (Door Bell), 型号 G4L-HW
核心服务:
   selectmusic.selectmusic enum RW  0-36 铃声选择
   volume.volume           int  RW  0-100 音量(step25)
   bellstatus.status       enum R    门铃状态(1-15 表示对应按钮被按下)

本适配器暴露:
   1. select  铃声选择
   2. number  音量
   3. binary_sensor 门铃响 (bellstatus 1-15 时 on)
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_BELL_OPTIONS = [
    "静音", "叮咚2声（缓）", "叮咚2声（快）", "叮咚1声", "西敏寺钟声",
    "致爱丽丝", "雨中旋律", "回忆", "喀秋莎", "土耳其进行曲",
    "小天鹅", "爱的罗曼史", "午夜睡眠", "匈牙利舞曲", "抒情曲",
    "幻想舞曲", "铃儿叮当响", "桂河大桥", "命运舞曲", "恭喜恭喜",
    "莫斯科郊外的晚上", "干簧管波尔", "老黑奴", "绿柚子", "勃拉姆斯摇篮曲",
    "警报6秒", "苏珊娜", "威廉泰尔序曲", "摇篮曲", "红河谷",
    "泰坦尼克号", "华尔兹舞曲", "圆舞曲", "警犬叔叔", "小美人鱼",
    "小企鹅", "罗密欧与朱丽叶",
]
_OPTION_TO_VAL = {name: i for i, name in enumerate(_BELL_OPTIONS)}


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


async def _select_music(context: DeviceContext, data: Mapping[str, Any]) -> None:
    val = _OPTION_TO_VAL.get(str(data.get("option")))
    if val is None:
        raise ValueError(f"unsupported option: {data.get('option')}")
    await context.async_send_service("selectmusic", {"selectmusic": val})


async def _set_volume(context: DeviceContext, data: Mapping[str, Any]) -> None:
    volume = data.get("value")
    if volume is None:
        return
    await context.async_send_service(
        "volume", {"volume": max(0, min(100, int(round(float(volume)))))}
    )


class Product2ACBAdapter:
    """2ACB 领普门铃适配器。"""

    prod_id = "2ACB"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service("selectmusic"):
            return ()

        def music_state(device: DeviceContext) -> Mapping[str, Any]:
            val = _as_int(device.value("selectmusic", "selectmusic"))
            return {
                "current_option": _BELL_OPTIONS[val]
                if val is not None and 0 <= val < len(_BELL_OPTIONS)
                else _BELL_OPTIONS[0]
            }

        def volume_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"native_value": _as_int(device.value("volume", "volume"))}

        def bell_state(device: DeviceContext) -> Mapping[str, Any]:
            status = _as_int(device.value("bellstatus", "status"))
            return {"is_on": bool(status) and 1 <= status <= 15}

        return (
            EntitySpec(
                platform="select",
                key="music",
                name="铃声",
                state=music_state,
                metadata={"options": _BELL_OPTIONS},
                actions={"select_option": _select_music},
            ),
            EntitySpec(
                platform="number",
                key="volume",
                name="音量",
                state=volume_state,
                metadata={"min": 0, "max": 100, "step": 25, "unit": "%"},
                actions={"set_value": _set_volume},
            ),
            EntitySpec(
                platform="binary_sensor",
                key="bell",
                name="门铃响",
                state=bell_state,
                metadata={"device_class": "sound"},
            ),
        )


ADAPTER = Product2ACBAdapter()


