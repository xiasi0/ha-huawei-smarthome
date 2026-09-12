"""User-contributed protocol for Huawei product X0A2 (华为 AI 音箱 2e).

设备类型: 华为 AI 音箱 2e (HUAWEI AI Speaker 2e)
制造商: 华为, 型号 SKLK-00
核心服务(播放控制):
   smartspeaker : playControl enum RW (0=停止播放, 1=启动播放, 2=上一首/下一首)
   audioplayer  : playState enum RW (0=暂停, 1=播放中, 2=停止)
   speakerState : State enum R (0=待机中, 1=拾音中, 2=等待响应, 3=语音播报)

本适配器暴露一个 Home Assistant ``media_player`` 实体, 提供 播放/暂停/停止 控制.
注: playControl=2 在设备资料中上一首与下一首共用同一值, 无法可靠区分,
    故不暴露 上一首/下一首 动作, 避免误操作.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_STATE_PLAYING = "playing"
_STATE_PAUSED = "paused"
_STATE_IDLE = "idle"


def _as_int(value: Any) -> int | None:
    """容忍 int / 数字字符串 / bool。"""
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


async def _play(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("smartspeaker", {"playControl": 1})


async def _pause(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("audioplayer", {"playState": 0})


async def _stop(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("smartspeaker", {"playControl": 0})


class ProductX0A2Adapter:
    """X0A2 华为 AI 音箱 2e 适配器：一个 media_player 实体。"""

    prod_id = "X0A2"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service("audioplayer"):
            return ()

        def player_state(device: DeviceContext) -> Mapping[str, Any]:
            state_code = _as_int(device.value("audioplayer", "playState"))
            if state_code == 1:
                state = _STATE_PLAYING
            elif state_code == 0:
                state = _STATE_PAUSED
            else:
                state = _STATE_IDLE
            return {"state": state}

        return (
            EntitySpec(
                platform="media_player",
                key="speaker",
                name=None,
                state=player_state,
                actions={
                    "play": _play,
                    "pause": _pause,
                    "stop": _stop,
                },
            ),
        )


ADAPTER = ProductX0A2Adapter()


