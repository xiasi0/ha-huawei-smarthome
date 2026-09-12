"""Product adapter for the PHP-W3-P1 three-key smart switch (ZG1V, 智能开关 3键).

Sibling of the OSLO-SS3 three-key switch (ZG11) — served by the exact same
vendor H5 bundle (``app.896cb7190c2c9fe4345b.js`` on both ``ZG11/h5_001`` and
``ZG1V/h5_001``).  In that bundle ZG1V sits in the same branch as ZG11 for
key naming (LeftClick/MiddleClick/RightClick) and is listed in
``supportBackLightDevList`` / ``new2024StyleDevList``.

All decisions mirror the ZG11 adapter (same family, same bundle, same
evidence types):

* ``switch1/2/3.on`` — the three relay outputs; HA sends the explicit
  target value (the home card toggles via ``valueExchange`` 0/1 flip).
* ``mode1/2/3.mode`` (1 开关模式 / 2 场景模式) — the 按键管理 page's
  ``onRadioChange`` writes ``{modeN:{mode:N}}``; H5 i18n labels are used
  (the Profile descCh says 联动模式 for 2).
* ``childLockSwitch.on`` — 按键锁定 toggle.
* ``backlight.on`` + ``brightness.brightness`` — 指示灯 toggle and 亮度
  slider, H5 ``range:[1,100]`` unit ``%``.  All four sibling Profiles
  (ZG11/ZG1V/ZG1W/ZG2K) declare 0..20 with no unit, contradicting the
  shipped slider; the H5 range is used for the command clamp, reported
  values pass through untouched.
* ``memorySwitch.on`` — 断电记忆 toggle.
* ``faultDetection.code`` — fault bitmask (过温保护 bit0, 继电器故障
  bit1; the shared store masks ``2 & code`` for the relay fault banner).
  ZG1V's Profile enum only names 0=正常/1=过温保护 — the bundle is the
  authority and it decomposes the full bitmask.
* ``faultDetection.status`` (0=正常, 1=异常) — 故障告警 binary_sensor.

Deliberately NOT exposed (same rulings as ZG11):

* ``scene`` — event counters + native ScenarioManager/gateway commands.
* ``button1/2/3`` — only ``name`` (per-key rename, belongs to HA) and
  ``num`` (internal key bookkeeping).
* ``switchN.name`` / ``switchN.inversion`` — rename belongs to HA;
  ``inversion`` never appears in the bundle.
* ``reboot`` — the only reset path in this bundle is
  ``{reboot:{action:2, devList:[{sn}]}}`` to the gateway; the descriptor
  has no ``sn`` and the Profile's ``action`` 0/1 values (重启单设备/全量
  设备) come without a per-device path, so degrading to them would risk
  rebooting the whole gateway.
* ``update`` — OTA, app-managed.
"""

from __future__ import annotations

from typing import Any, Mapping

from .api import EntitySpec
from .context import DeviceContext

_SWITCH_SIDS = ("switch1", "switch2", "switch3")
_SWITCH_FIELD = "on"

_MODE_FIELD = "mode"
_MODE_VALUES = (1, 2)
_MODE_OPTIONS = ("开关模式", "场景模式")  # H5 i18n; Profile descCh: 联动模式

_LOCK_SID = "childLockSwitch"
_BACKLIGHT_SID = "backlight"
_MEMORY_SID = "memorySwitch"
_FLAG_FIELD = "on"

_BRIGHTNESS_SID = "brightness"
_BRIGHTNESS_FIELD = "brightness"
_BRIGHTNESS_RANGE = (1.0, 100.0)  # H5 slider range:[1,100] unit % (Profile says 0..20)
_BRIGHTNESS_UNIT = "%"

_FAULT_SID = "faultDetection"
_FAULT_CODE_FIELD = "code"
_FAULT_STATUS_FIELD = "status"
# H5 faults[] indexed by bit position of the code bitmask.
_FAULT_BITS = ((1, "过温保护"), (2, "继电器故障"))

_KEY_DIGITS = "一二三"


def _service(profile: Any, sid: str) -> Any:
    if profile is None:
        return None
    for service in profile.get("services", ()):
        if service.get("serviceId") == sid:
            return service
    return None


def _field(profile: Any, sid: str, name: str) -> Mapping[str, Any] | None:
    service = _service(profile, sid)
    if service is None:
        return None
    for characteristic in service.get("characteristics", ()):
        if characteristic.get("characteristicName") == name:
            return characteristic
    return None


def _flag_value(raw: Any) -> bool | None:
    """Reported switch value → bool; anything outside 0/1 stays unknown."""

    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    try:
        number = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if number == 1:
        return True
    if number == 0:
        return False
    return None


def _flag_action(sid: str, value: int):
    async def action(ctx: DeviceContext, data: Mapping[str, Any]) -> None:
        del data
        await ctx.async_send_service(sid, {_FLAG_FIELD: value})

    return action


def _enum_state(
    context: DeviceContext,
    sid: str,
    field: str,
    options: tuple[str, ...],
    values: tuple[int, ...],
) -> str | None:
    """Map a reported enum value onto its label; unknown values stay unknown."""

    raw = context.value(sid, field)
    if raw is None:
        return None
    try:
        number = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if number not in values:
        return None
    return dict(zip(values, options)).get(number)


def _enum_payload(
    option: str, options: tuple[str, ...], values: tuple[int, ...]
) -> int | None:
    try:
        return values[options.index(option)]
    except ValueError:
        return None


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _fault_state(context: DeviceContext) -> str | None:
    """Decompose the fault bitmask exactly like the H5's ``faultInfoList``."""

    raw = context.value(_FAULT_SID, _FAULT_CODE_FIELD)
    if raw is None:
        return None
    try:
        code = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if code == 0:
        return "正常"
    labels: list[str] = []
    known = 0
    for bit, label in _FAULT_BITS:
        if code & bit:
            labels.append(label)
            known |= bit
    unknown = code & ~known
    if unknown:
        highest = unknown.bit_length()
        labels.append(f"未知({highest - 1})")
    return "、".join(labels)


def _enum_select(
    key: str,
    name: str,
    sid: str,
    field: str,
    options: tuple[str, ...],
    values: tuple[int, ...],
) -> EntitySpec:
    async def action(ctx: DeviceContext, data: Mapping[str, Any]) -> None:
        option = data.get("option")
        if not isinstance(option, str):
            return
        value = _enum_payload(option, options, values)
        if value is not None:
            await ctx.async_send_service(sid, {field: value})

    return EntitySpec(
        platform="select",
        key=key,
        name=name,
        state=lambda ctx, _sid=sid, _f=field, _o=options, _v=values: {
            "current_option": _enum_state(ctx, _sid, _f, _o, _v)
        },
        metadata={"options": list(options)},
        actions={"select_option": action},
    )


def _flag_switch(key: str, name: str, sid: str) -> EntitySpec:
    return EntitySpec(
        platform="switch",
        key=key,
        name=name,
        state=lambda ctx, _sid=sid: {
            "is_on": _flag_value(ctx.value(_sid, _FLAG_FIELD))
        },
        metadata={},
        actions={
            "turn_on": _flag_action(sid, 1),
            "turn_off": _flag_action(sid, 0),
        },
    )


class ProductZG1VAdapter:
    """PHP-W3-P1 three-key smart switch (ZG1V)."""

    prod_id = "ZG1V"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        entities: list[EntitySpec] = []

        # --- relay outputs --------------------------------------------------
        for index, sid in enumerate(_SWITCH_SIDS, start=1):
            if not context.has_service(sid) or _field(
                profile, sid, _SWITCH_FIELD
            ) is None:
                continue
            entities.append(
                EntitySpec(
                    platform="switch",
                    key=f"switch_{index}",
                    name=f"开关{_KEY_DIGITS[index - 1]}",
                    state=lambda ctx, _sid=sid: {
                        "is_on": _flag_value(ctx.value(_sid, _SWITCH_FIELD))
                    },
                    metadata={},
                    actions={
                        "turn_on": _flag_action(sid, 1),
                        "turn_off": _flag_action(sid, 0),
                    },
                )
            )

        # --- per-key mode ---------------------------------------------------
        for index in (1, 2, 3):
            sid = f"mode{index}"
            if not context.has_service(sid) or _field(
                profile, sid, _MODE_FIELD
            ) is None:
                continue
            entities.append(
                _enum_select(
                    f"key_{index}_mode",
                    f"按键{_KEY_DIGITS[index - 1]}模式",
                    sid,
                    _MODE_FIELD,
                    _MODE_OPTIONS,
                    _MODE_VALUES,
                )
            )

        # --- key lock -------------------------------------------------------
        if context.has_service(_LOCK_SID) and _field(
            profile, _LOCK_SID, _FLAG_FIELD
        ) is not None:
            entities.append(_flag_switch("key_lock", "按键锁定", _LOCK_SID))

        # --- indicator light ------------------------------------------------
        if context.has_service(_BACKLIGHT_SID) and _field(
            profile, _BACKLIGHT_SID, _FLAG_FIELD
        ) is not None:
            entities.append(_flag_switch("indicator_light", "指示灯", _BACKLIGHT_SID))

        # --- indicator brightness -------------------------------------------
        if context.has_service(_BRIGHTNESS_SID) and _field(
            profile, _BRIGHTNESS_SID, _BRIGHTNESS_FIELD
        ) is not None:
            async def _brightness_action(ctx: DeviceContext, data: Mapping[str, Any]) -> None:
                value = _number(data.get("value"))
                if value is not None:
                    clamped = int(_clamp(value, *_BRIGHTNESS_RANGE))
                    await ctx.async_send_service(
                        _BRIGHTNESS_SID, {_BRIGHTNESS_FIELD: clamped}
                    )

            entities.append(
                EntitySpec(
                    platform="number",
                    key="indicator_brightness",
                    name="指示灯亮度",
                    state=lambda ctx: {
                        "native_value": _number(
                            ctx.value(_BRIGHTNESS_SID, _BRIGHTNESS_FIELD)
                        )
                    },
                    metadata={
                        "min": _BRIGHTNESS_RANGE[0],
                        "max": _BRIGHTNESS_RANGE[1],
                        "step": 1.0,
                        "unit": _BRIGHTNESS_UNIT,
                    },
                    actions={"set_value": _brightness_action},
                )
            )

        # --- power-loss memory ----------------------------------------------
        if context.has_service(_MEMORY_SID) and _field(
            profile, _MEMORY_SID, _FLAG_FIELD
        ) is not None:
            entities.append(_flag_switch("power_loss_memory", "断电记忆", _MEMORY_SID))

        # --- fault state (bitmask) ------------------------------------------
        if context.has_service(_FAULT_SID) and _field(
            profile, _FAULT_SID, _FAULT_CODE_FIELD
        ) is not None:
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="fault_state",
                    name="故障状态",
                    state=lambda ctx: {"native_value": _fault_state(ctx)},
                    metadata={},
                    actions={},
                )
            )

        # --- fault alarm ------------------------------------------------------
        if context.has_service(_FAULT_SID) and _field(
            profile, _FAULT_SID, _FAULT_STATUS_FIELD
        ) is not None:
            entities.append(
                EntitySpec(
                    platform="binary_sensor",
                    key="fault_problem",
                    name="故障告警",
                    # Profile enum: 1=异常, 0=正常
                    state=lambda ctx: {
                        "is_on": (
                            None
                            if _flag_value(ctx.value(_FAULT_SID, _FAULT_STATUS_FIELD)) is None
                            else bool(_flag_value(ctx.value(_FAULT_SID, _FAULT_STATUS_FIELD)))
                        )
                    },
                    metadata={"device_class": "problem"},
                    actions={},
                )
            )

        return tuple(entities)


ADAPTER = ProductZG1VAdapter()
