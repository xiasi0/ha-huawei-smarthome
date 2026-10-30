"""User-contributed protocol for Huawei product 113E (豪恩多功能网关 / iHORN T2 Multi-function Gateway).

Profile: https://smarthome-drcn.dbankcdn.com/device/guide/113E/113E.json
厂商: 豪恩 (iHORN) | deviceName: 豪恩多功能网关 | deviceTypeName: 中控主机 (Bridge) | protocolType: WiFi

注意：本设备是网关/中控主机，不是摄像头，因此没有"无实时画面"限制——它本就没有监控画面能力。
本适配器只暴露网关设备自身的真实可读/可写能力。

服务与特征（未列出者为不暴露项）：
  alertor.alertorEnable     enum RW  警戒布防开关 (0/1)            → switch 警戒布防
  alertor.alarmEvent        enum W   开始/停止报警 (0/1)           → button 触发报警 (有副作用：会响警报)
  alertor.volume            int  RW  报警音量 1-100 (%)            → number 报警音量
  alertor.duration          int  RW  报警时长 1-1800 (秒)          → number 报警时长
  alertor.delayWork         int  RW  延时进入警戒 0-60 (秒)        → number 延时布防
  alertor.alarmVoiceSeq     int  RW  报警声编号 0-2                → number 报警声编号
  alertor.leftDelayTime     int  R   延时剩余 0-60 (秒)            → sensor 布防延时剩余
  bell.playEvent            enum W   播放/停止门铃 (0/1)          → button 播放门铃
  bell.seq                  int  RW  门铃铃声 0-2                  → number 门铃铃声
  bell.playTimes            int  RW  门铃响铃次数 0-4              → number 门铃响铃次数
  bell.volume               int  RW  门铃音量 0-100 (%)            → number 门铃音量
  light.lightEnable         enum RW  夜灯开关 (0/1)                → light 夜灯 (含亮度)
  light.brightness          int  RW  夜灯亮度 0-100                → light.brightness (HA 0-255 换算)
  light.inductionEnable     enum RW  感应夜灯开关 (0/1)            → switch 感应夜灯
  light.delayOff            int  RW  延时灭灯 0-30 (分钟)          → number 夜灯延时灭灯
  light.lightLux            enum R   光照强度 0-3                  → sensor 光照强度 (文本档位)
  prompt.volume             int  RW  提示音音量 0-100 (%)          → number 提示音音量
  netInfo.RSSI              int  R   -100..0 dB                   → sensor 信号强度 RSSI

刻意不暴露的服务（原因）：
  discovery   子设备配对（需 productid/sn 组合，与 HA 实体模型不符，且属敏感配对操作）
  alertorEvent/lightEvent/previewAlertor/previewBell/continue IFTTT/预览类瞬时命令（已被上面的实体覆盖或无需实体）
  voiceMessage 语音留言（数组/分包数据，HF 专用，无对应 HA 实体）
  timer        本地定时器（数组结构；HA 自有自动化/定时，不应重复实现）
  devOta       固件升级（危险/只读为主）
  netInfo.SSID/BSSID/IP/intensity  隐私或 RSSI 派生量
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable

from .api import EntitySpec
from .context import DeviceContext


def _bool(value: Any) -> bool | None:
    """把设备上报值 (bool / 1,0 / "1","0","true","false") 规整为 bool，失败返回 None。"""

    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.casefold()
        if lowered in {"1", "true", "on"}:
            return True
        if lowered in {"0", "false", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _to_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _make_switch_spec(sid: str, char: str, name: str) -> EntitySpec:
    """为某个 0/1 可写特征 (警戒布防 / 感应夜灯) 生成一个 HA switch 实体。"""

    def state(context: DeviceContext) -> Mapping[str, Any]:
        return {"is_on": _bool(context.value(sid, char))}

    async def turn_on(context: DeviceContext, _data: Mapping[str, Any]) -> None:
        await context.async_send_service(sid, {char: 1})

    async def turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
        await context.async_send_service(sid, {char: 0})

    return EntitySpec(
        platform="switch",
        key=f"{sid}_{char}",
        name=name,
        state=state,
        actions={"turn_on": turn_on, "turn_off": turn_off},
    )


def _make_button_spec(sid: str, char: str, name: str, value: Any = 1) -> EntitySpec:
    """为某个瞬时动作 (触发报警 / 播放门铃) 生成一个 HA button 实体。"""

    async def press(context: DeviceContext, _data: Mapping[str, Any]) -> None:
        await context.async_send_service(sid, {char: value})

    return EntitySpec(
        platform="button",
        key=f"{sid}_{char}",
        name=name,
        state=lambda _context: {},
        actions={"press": press},
    )


def _make_number_spec(
    sid: str,
    char: str,
    name: str,
    *,
    min_v: int,
    max_v: int,
    step: int = 1,
    unit: str | None = None,
) -> EntitySpec:
    """为某个 int RW 配置项 (音量/时长/次数/编号) 生成一个 HA number 实体。

    number.py 要求 metadata 必含 min/max（缺则构造时 KeyError），action key 为 set_value，
    调用 action(context, {"value": <float>})。
    """

    def state(context: DeviceContext) -> Mapping[str, Any]:
        return {"native_value": _to_int(context.value(sid, char))}

    async def set_value(context: DeviceContext, data: Mapping[str, Any]) -> None:
        await context.async_send_service(sid, {char: int(data["value"])})

    metadata: dict[str, Any] = {"min": min_v, "max": max_v, "step": step}
    if unit is not None:
        metadata["unit"] = unit
    return EntitySpec(
        platform="number",
        key=f"{sid}_{char}",
        name=name,
        state=state,
        metadata=metadata,
        actions={"set_value": set_value},
    )


def _make_sensor_spec(
    sid: str,
    char: str,
    name: str,
    *,
    unit: str | None = None,
    device_class: str | None = None,
    state_class: str | None = "measurement",
    mapper: Callable[[Any], Any] | None = None,
) -> EntitySpec:
    """为某个只读数值/枚举特征生成一个 HA sensor 实体。

    mapper 用于把原始值转成友好展示 (如光照强度档位文本)；非数值场景应置 state_class=None。
    """

    def state(context: DeviceContext) -> Mapping[str, Any]:
        raw = context.value(sid, char)
        return {"native_value": mapper(raw) if mapper is not None else _to_int(raw)}

    metadata: dict[str, Any] = {}
    if state_class is not None:
        metadata["state_class"] = state_class
    if unit is not None:
        metadata["unit"] = unit
    if device_class is not None:
        metadata["device_class"] = device_class
    return EntitySpec(
        platform="sensor",
        key=char if sid == "netInfo" else f"{sid}_{char}",
        name=name,
        state=state,
        metadata=metadata,
    )


# 光照强度枚举：0=白天弱光 / 1=夜晚弱光 / 2=白天强光 / 3=夜晚强光
_LUX_TEXT = {0: "白天弱光", 1: "夜晚弱光", 2: "白天强光", 3: "夜晚强光"}


def _make_light_spec() -> EntitySpec:
    """夜灯：lightEnable 控制开关，brightness 0-100 需换算为 HA 的 0-255。"""

    def state(context: DeviceContext) -> Mapping[str, Any]:
        dev_bri = _to_int(context.value("light", "brightness")) or 0
        return {
            "is_on": _bool(context.value("light", "lightEnable")),
            "brightness": round(dev_bri * 255 / 100),
            "color_mode": "brightness",
        }

    async def turn_on(context: DeviceContext, data: Mapping[str, Any]) -> None:
        payload: dict[str, Any] = {"lightEnable": 1}
        bri = data.get("brightness")
        if bri is not None:
            payload["brightness"] = round(int(bri) * 100 / 255)
        await context.async_send_service("light", payload)

    async def turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
        await context.async_send_service("light", {"lightEnable": 0})

    return EntitySpec(
        platform="light",
        key="light",
        name="夜灯",
        state=state,
        metadata={"supported_color_modes": ["brightness"]},
        actions={"turn_on": turn_on, "turn_off": turn_off},
    )


class Product113EAdapter:
    """豪恩多功能网关 T2：警戒/夜灯控制 + 报警/门铃动作 + 9 个可调参数 + 信号/光照传感器。"""

    prod_id = "113E"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None:
            return ()

        specs: list[EntitySpec] = []

        # ---- 警戒控制 ----
        if context.has_service("alertor"):
            specs.append(_make_switch_spec("alertor", "alertorEnable", "警戒布防"))
            specs.append(_make_button_spec("alertor", "alarmEvent", "触发报警"))
            specs.append(_make_number_spec("alertor", "volume", "报警音量", min_v=1, max_v=100, step=1, unit="%"))
            specs.append(_make_number_spec("alertor", "duration", "报警时长", min_v=1, max_v=1800, step=1, unit="s"))
            specs.append(_make_number_spec("alertor", "delayWork", "延时布防", min_v=0, max_v=60, step=1, unit="s"))
            specs.append(_make_number_spec("alertor", "alarmVoiceSeq", "报警声编号", min_v=0, max_v=2, step=1))
            specs.append(
                _make_sensor_spec("alertor", "leftDelayTime", "布防延时剩余", unit="s")
            )

        # ---- 门铃 ----
        if context.has_service("bell"):
            specs.append(_make_button_spec("bell", "playEvent", "播放门铃"))
            specs.append(_make_number_spec("bell", "seq", "门铃铃声", min_v=0, max_v=2, step=1))
            specs.append(_make_number_spec("bell", "playTimes", "门铃响铃次数", min_v=0, max_v=4, step=1))
            specs.append(_make_number_spec("bell", "volume", "门铃音量", min_v=0, max_v=100, step=1, unit="%"))

        # ---- 夜灯（含亮度）----
        if context.has_service("light"):
            specs.append(_make_light_spec())
            specs.append(_make_switch_spec("light", "inductionEnable", "感应夜灯"))
            specs.append(_make_number_spec("light", "delayOff", "夜灯延时灭灯", min_v=0, max_v=30, step=1, unit="min"))
            specs.append(
                _make_sensor_spec(
                    "light", "lightLux", "光照强度",
                    state_class=None, mapper=lambda v: _LUX_TEXT.get(_to_int(v), str(v)),
                )
            )

        # ---- 提示音音量 ----
        if context.has_service("prompt"):
            specs.append(_make_number_spec("prompt", "volume", "提示音音量", min_v=0, max_v=100, step=1, unit="%"))

        # ---- 网络信号 ----
        if context.has_service("netInfo"):
            specs.append(
                _make_sensor_spec("netInfo", "RSSI", "信号强度 RSSI", unit="dBm", device_class="signal_strength")
            )

        return tuple(specs)


ADAPTER = Product113EAdapter()
