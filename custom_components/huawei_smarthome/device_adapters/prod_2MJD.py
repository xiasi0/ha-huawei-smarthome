"""User-contributed protocol for Huawei product 2MJD (红外万能遥控中心).

产品: 红外万能遥控中心
厂商: 深圳遥看科技有限公司
型号: YKK-H1025 / deviceTypeId 007 (万能遥控器)

═══════════════════════════════════════════════════════════════════
为什么需要单独适配
═══════════════════════════════════════════════════════════════════

本机 nodeType 为 GATEWAY，但它不是家居网关，而是**红外码库中枢**：自身没有
可控制的继电器，靠红外遥控空调/电视/风扇等。空调是它的「虚拟子设备」，
列在 ``rcList`` 里，真正的控制状态在 ``airKey``。

同类产品 115J（遥控大师空调伴侣）虽然也用 ``airKey``，但**字段名完全不同**：

    | 语义   | 115J    | 2MJD      |
    |--------|---------|-----------|
    | 开关   | power   | on        |
    | 模式   | mode    | mode      |
    | 温度   | temp    | target    |
    | 风速   | wind    | gear      |
    | 扫风   | up      | airSwing  |

所以不能靠 115J 的适配器覆盖，必须单独写一份。

═══════════════════════════════════════════════════════════════════
实体清单
═══════════════════════════════════════════════════════════════════

    air    climate  空调 (开关 / 模式 / 温度 / 风速 / 扫风)

说明：``rcList`` 会列出多台已学习的红外设备（本机为「空调」+ 3 个自定义键），
但 ``airKey`` 只有一份状态，即**当前受控的那台**。因此只建一个空调实体，
名称优先取 ``rcList`` 里识别的空调条目名，取不到时回落为「空调」。

未暴露（宁可不出）：
- ``TVKey`` / ``STBKey`` / ``purifierKey`` / ``speakerKey`` / ``projectorKey``：
  只上报 ``on``，无法区分「红外没能确认」与「真的关着」，语义不可靠。
- ``mediaKey1..3`` / ``customKey`` / ``fanMode`` / ``indicatorSwitch``：
  当前上报为空对象，没有可用值。
- ``update`` / ``netInfo`` / ``diagnose`` / ``backup`` / ``timer`` / ``delay`` /
  ``batchCmd`` / ``matchedCap`` / ``ctlCapability``：系统服务。

═══════════════════════════════════════════════════════════════════
控制帧
═══════════════════════════════════════════════════════════════════

**只下发要改的字段**，形如 ``{"target": 26}`` / ``{"on": 1}`` / ``{"mode": 4}``；
切换模式时先发 ``mode`` 再发 ``on=1``。

**不要带 ``id``**：2MJD 的 ``airKey`` 特征表里没有这个字段，多带会被云端直接
拒绝（实测 ``errcode=16001``）。

早期版本照 115J 的做法拼成 ``{id: 0, mode, gear, target, airSwing, on}`` 整帧重发，
云端一律拒绝；改为逐字段下发后正常。同厂商的 2MFE 也是这个写法。

关于 ``airSwing``：厂商枚举为 0 上下左右关 / 1 上下左右开 / 2 上下开左右关 /
3 上下关左右开。本适配器只暴露**开与关**两档（非 0 = 开），不做四档细分。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_AIR_SID = "airKey"
_RC_LIST_SID = "rcList"

_AIR_ON = 1
_AIR_OFF = 0

_TEMP_MIN = 16
_TEMP_MAX = 30

# airKey.mode 与 115J 同源：0自动 1除湿 2送风 3制热 4制冷
_DEV_TO_HVAC = {0: "auto", 1: "dry", 2: "fan_only", 3: "heat", 4: "cool"}
_HVAC_TO_DEV = {value: key for key, value in _DEV_TO_HVAC.items()}

# airKey.gear：沿用 115J 的 wind 口径（0自动 1低 2中 3高）
_DEV_TO_FAN = {0: "auto", 1: "low", 2: "medium", 3: "high"}
_FAN_TO_DEV = {value: key for key, value in _DEV_TO_FAN.items()}

# airSwing 取值未公开，只做两档
_SWING_MODES = ("off", "on")

# 除湿必须低风（与厂商 H5 一致）
_MODE_FORCED_FAN = {"dry": 1}


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None if value is None else int(value)
    if isinstance(value, str):
        try:
            return int(round(float(value.strip())))
        except (TypeError, ValueError):
            return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _air_name(context: DeviceContext) -> str:
    """从 rcList 里找出空调那一项的名称，找不到就用「空调」。"""

    entries = context.value(_RC_LIST_SID, "list")
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            label = str(entry.get("deviceName") or "")
            if "空调" in label or "冷气" in label:
                return label
    return "空调"


# 写帧规则（照同厂商的 2MFE 实现，两者 airKey 字段名完全一致）：
#   1. **只发要改的字段**，不做整帧重发；
#   2. **不发 `id`**——2MJD 的 airKey 特征表里没有这个字段，
#      多带会被云端直接判为参数错误（实测 errcode=16001）；
#   3. 切换模式分两步下发：先 `mode`，再 `on=1`。
# 早期照 115J 的 `{id: 0, ...}` 整帧形态被云端拒绝，已按 2MFE 改正。


async def _turn_on(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(_AIR_SID, {"on": _AIR_ON})


async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(_AIR_SID, {"on": _AIR_OFF})


async def _set_hvac_mode(context: DeviceContext, data: Mapping[str, Any]) -> None:
    hvac_mode = str(data.get("hvac_mode"))
    if hvac_mode == "off":
        await _turn_off(context, data)
        return
    dev_mode = _HVAC_TO_DEV.get(hvac_mode)
    if dev_mode is None:
        raise ValueError(f"2MJD unsupported hvac_mode: {hvac_mode!r}")

    # 与 2MFE 一致：模式与开机分两步下发
    await context.async_send_service(_AIR_SID, {"mode": dev_mode})
    if hvac_mode in _MODE_FORCED_FAN:
        await context.async_send_service(
            _AIR_SID, {"gear": _MODE_FORCED_FAN[hvac_mode]}
        )
    await context.async_send_service(_AIR_SID, {"on": _AIR_ON})


async def _set_temperature(context: DeviceContext, data: Mapping[str, Any]) -> None:
    temperature = _as_float(data.get("temperature"))
    if temperature is None:
        return
    target = max(_TEMP_MIN, min(_TEMP_MAX, int(round(temperature))))
    await context.async_send_service(_AIR_SID, {"target": target})


async def _set_fan_mode(context: DeviceContext, data: Mapping[str, Any]) -> None:
    fan_mode = str(data.get("fan_mode"))
    gear = _FAN_TO_DEV.get(fan_mode)
    if gear is None:
        raise ValueError(f"2MJD unsupported fan_mode: {fan_mode!r}")
    await context.async_send_service(_AIR_SID, {"gear": gear})


async def _set_swing_mode(context: DeviceContext, data: Mapping[str, Any]) -> None:
    swing_mode = str(data.get("swing_mode"))
    if swing_mode not in _SWING_MODES:
        raise ValueError(f"2MJD unsupported swing_mode: {swing_mode!r}")
    await context.async_send_service(
        _AIR_SID, {"airSwing": 1 if swing_mode == "on" else 0}
    )


class Product2MJDAdapter:
    """2MJD 红外万能遥控中心适配器（暴露空调）。"""

    prod_id = "2MJD"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not context.has_service(_AIR_SID):
            return ()

        def climate_state(device: DeviceContext) -> Mapping[str, Any]:
            state = device.service_state(_AIR_SID)
            power = _as_int(state.get("on"))
            mode = _as_int(state.get("mode"))
            if power == _AIR_OFF:
                hvac_mode = "off"
            elif power is None:
                hvac_mode = None
            else:
                hvac_mode = _DEV_TO_HVAC.get(mode)
            swing = _as_int(state.get("airSwing"))
            return {
                "hvac_mode": hvac_mode,
                "target_temperature": _as_float(state.get("target")),
                "fan_mode": _DEV_TO_FAN.get(_as_int(state.get("gear"))),
                "swing_mode": None if swing is None else ("on" if swing else "off"),
            }

        return (
            EntitySpec(
                platform="climate",
                key="air",
                name=_air_name(context),
                state=climate_state,
                metadata={
                    "hvac_modes": list(_DEV_TO_HVAC.values()) + ["off"],
                    "fan_modes": list(_DEV_TO_FAN.values()),
                    "swing_modes": list(_SWING_MODES),
                    "min_temp": _TEMP_MIN,
                    "max_temp": _TEMP_MAX,
                },
                actions={
                    "turn_on": _turn_on,
                    "turn_off": _turn_off,
                    "set_hvac_mode": _set_hvac_mode,
                    "set_temperature": _set_temperature,
                    "set_fan_mode": _set_fan_mode,
                    "set_swing_mode": _set_swing_mode,
                },
            ),
        )


ADAPTER = Product2MJDAdapter()
