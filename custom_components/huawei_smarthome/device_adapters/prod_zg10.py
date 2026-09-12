"""Product adapter for the OSLO-SS2 two-key smart switch (ZG10, 智能开关 2键).

Vendor H5 bundle (``ZG10/h5_001``; ``app.js`` holds all logic, ``chunk_1.js``
is the vendor lib) serves the OSLO switch family.  Unlike the EBOLON switch
(2MH8) this H5 dispatches with the ``{sid, cid, value}`` helper, whose vuex
action serialises to exactly the wire form ``{[sid]: {[cid]: value}}``:

.. code-block:: js

    setDevInfo({},{sid:e,cid:t,value:i,callback:n}){
      window.hilink.setDeviceInfo("0", JSON.stringify({[e]:{[t]:i}}), ...)

* ``switch1.on`` / ``switch2.on`` — the two relay outputs.  The home card's
  ``onClickButton1``/``onClickButton2`` dispatch ``{switch1:{on: 0|1}}``
  (``valueExchange`` inverts the current value) when the key mode is 1.
* ``mode1.mode`` / ``mode2.mode`` (1 开关模式 / 2 场景模式) — the 按键管理
  page's ``onRadioChange`` writes ``{mode1:{mode:N}}``.  The H5 i18n dict
  names the values 开关模式/场景模式 ("按下按键执行场景，不再控制连接设备");
  the Profile descCh says 联动模式 for 2 — the H5 label is used.
* ``childLockSwitch.on`` — 按键锁定 toggle (i18n ``childLock`` = 按键锁定).
* ``backlight.on`` — 指示灯 toggle (i18n ``backLight`` = 指示灯, same
  reading as the OSLO-SP6 panel adapter ZG0E).
* ``brightness.brightness`` — 指示灯亮度 slider, H5 ``range:[1,100]`` with
  unit ``%``.  The Profile declares min 0 / max 20, which contradicts the
  actual slider; the H5 range is used for the command clamp (values the
  device reports outside 1-100 stay raw, only non-numerics become unknown).
* ``memorySwitch.on`` — 断电记忆 toggle (bool 0/1, unlike the EBOLON
  three-state ``memorySwitch.status``).
* ``faultDetection.code`` — fault bitmask.  The H5 keeps the raw ``code``
  as a bitmask and maps set-bit positions through ``faults[]``:
  ``faults:[过温保护, 继电器故障]``, rendering unknown positions as
  未知故障.  (Its banner additionally masks with ``2&code`` to only surface
  the relay fault, which confirms the bitwise reading.)  ``code`` = 0 with
  ``status`` = 0 means 正常.

Deliberately NOT exposed:

* ``scene`` — ``num``/``DoubleClick``/``LongClick`` are *event counters*
  (the H5 reads them as click history records with values 1/2 = which key,
  via ``getDevHistory``; ``DoubleClick`` is never referenced anywhere in
  the bundle).  Scene binding itself is managed by the app's
  ScenarioManager / gateway commands, not by a device write.
* ``button1`` / ``button2`` — only ``name`` (rename, belongs to HA) and
  ``num`` (internal key-count bookkeeping).
* ``switch1.name`` / ``switch2.name`` — renaming belongs to HA.
* ``reboot`` — the H5 writes ``{reboot:{action:2, devList:[{sn}]}}``
  (gateway-attached batch reboot); the descriptor has no ``sn`` and
  degrading to ``action:0`` would reboot the whole gateway.  Same ruling
  as the ZG1Y / ZG0E adapters.
* ``update`` — OTA (check/launch upgrade), app-managed.
* ``switchN.inversion`` — never referenced in the bundle.
* ``backlightMode`` — the H5 updateState knows this sid but the Profile has
  no such service (internal relay/indicator wiring state).
"""

from __future__ import annotations

from typing import Any, Mapping

from .api import EntitySpec
from .context import DeviceContext

_SWITCH_SIDS = ("switch1", "switch2")
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
_BRIGHTNESS_RANGE = (1.0, 100.0)  # H5 slider range:[1,100] unit %
_BRIGHTNESS_UNIT = "%"

_FAULT_SID = "faultDetection"
_FAULT_CODE_FIELD = "code"
# H5 faults[] indexed by bit position of the code bitmask.
_FAULT_BITS = ((1, "过温保护"), (2, "继电器故障"))


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


class ProductZG10Adapter:
    """OSLO-SS2 two-key smart switch (ZG10)."""

    prod_id = "ZG10"

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
                    name=f"开关{'一二'[index - 1]}",
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
        for index, sid in enumerate(("mode1", "mode2"), start=1):
            if not context.has_service(sid) or _field(
                profile, sid, _MODE_FIELD
            ) is None:
                continue
            entities.append(
                _enum_select(
                    f"key_{index}_mode",
                    f"按键{'一二'[index - 1]}模式",
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
            entities.append(
                EntitySpec(
                    platform="switch",
                    key="key_lock",
                    name="按键锁定",
                    state=lambda ctx: {
                        "is_on": _flag_value(ctx.value(_LOCK_SID, _FLAG_FIELD))
                    },
                    metadata={},
                    actions={
                        "turn_on": _flag_action(_LOCK_SID, 1),
                        "turn_off": _flag_action(_LOCK_SID, 0),
                    },
                )
            )

        # --- indicator light ------------------------------------------------
        if context.has_service(_BACKLIGHT_SID) and _field(
            profile, _BACKLIGHT_SID, _FLAG_FIELD
        ) is not None:
            entities.append(
                EntitySpec(
                    platform="switch",
                    key="indicator_light",
                    name="指示灯",
                    state=lambda ctx: {
                        "is_on": _flag_value(ctx.value(_BACKLIGHT_SID, _FLAG_FIELD))
                    },
                    metadata={},
                    actions={
                        "turn_on": _flag_action(_BACKLIGHT_SID, 1),
                        "turn_off": _flag_action(_BACKLIGHT_SID, 0),
                    },
                )
            )

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
            entities.append(
                EntitySpec(
                    platform="switch",
                    key="power_loss_memory",
                    name="断电记忆",
                    state=lambda ctx: {
                        "is_on": _flag_value(ctx.value(_MEMORY_SID, _FLAG_FIELD))
                    },
                    metadata={},
                    actions={
                        "turn_on": _flag_action(_MEMORY_SID, 1),
                        "turn_off": _flag_action(_MEMORY_SID, 0),
                    },
                )
            )

        # --- fault state ------------------------------------------------------
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

        return tuple(entities)


ADAPTER = ProductZG10Adapter()
