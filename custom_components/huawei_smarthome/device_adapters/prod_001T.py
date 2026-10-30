"""User-contributed protocol for Huawei product 001T (华为AI音箱 / Myna).

Mapping is based on profile huawei_smarthome/profiles/001T.json:

- audioplayer/playState (RW): 0=暂停, 1=播放中, 2=停止
- smartspeaker/playControl (RW): 0=停止, 1=播放, 2=上一首, 下一首发送 3
  (profile 中"下一首"枚举值与"上一首"重复为 2，按音箱插件惯例命令值用 3，
   如实机不符请抓包修正 _CMD_NEXT)
- speakerState/State (R): 0=待机中, 1=拾音中, 2=等待响应, 3=语音播报
"""

from __future__ import annotations

from typing import Any, Mapping

from homeassistant.components.media_player import MediaPlayerState

from .api import EntitySpec
from .context import DeviceContext

_CMD_STOP = 0
_CMD_PLAY = 1
_CMD_PREVIOUS = 2
_CMD_NEXT = 3  # profile 枚举中与"上一首"重复，按音箱插件惯例取 3，需实机验证

_PLAY_STATE_TO_HA = {
    0: MediaPlayerState.PAUSED,
    1: MediaPlayerState.PLAYING,
    2: MediaPlayerState.IDLE,
}

_SPEAKER_STATE_LABELS = {
    0: "待机中",
    1: "拾音中",
    2: "等待响应",
    3: "语音播报",
}


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


async def _play_control(context: DeviceContext, command: int) -> None:
    await context.async_send_service("smartspeaker", {"playControl": command})


async def _play(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await _play_control(context, _CMD_PLAY)


async def _pause(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await _play_control(context, _CMD_STOP)


async def _stop(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await _play_control(context, _CMD_STOP)


async def _next(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await _play_control(context, _CMD_NEXT)


async def _previous(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await _play_control(context, _CMD_PREVIOUS)


def _media_state(device: DeviceContext) -> Mapping[str, Any]:
    play_state = _number(device.value("audioplayer", "playState"))
    speaker_state = _number(device.value("speakerState", "State"))
    state = _PLAY_STATE_TO_HA.get(int(play_state)) if play_state is not None else None
    if state is None:
        # 没有播放状态上报时，语音播报中视为播放
        if int(speaker_state or -1) == 3:
            state = MediaPlayerState.PLAYING
        else:
            state = MediaPlayerState.UNKNOWN
    return {"state": state}


class Product001TAdapter:
    """华为AI音箱 (prodId 001T, deviceModel BSZHWFA001)."""

    prod_id = "001T"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        # hwaccount/activeState == 0 表示账号在线可用（来自 profile quickmenu 条件）
        account_state = _number(context.value("hwaccount", "activeState"))
        if account_state is not None and int(account_state) != 0:
            return ()
        if not context.has_service("audioplayer") or not context.has_service(
            "smartspeaker"
        ):
            return ()
        return (
            EntitySpec(
                platform="media_player",
                key="speaker",
                name=None,
                state=_media_state,
                actions={
                    "play": _play,
                    "pause": _pause,
                    "stop": _stop,
                    "next": _next,
                    "previous": _previous,
                },
            ),
        )


ADAPTER = Product001TAdapter()
