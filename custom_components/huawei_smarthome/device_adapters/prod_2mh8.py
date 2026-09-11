"""Product adapter for the Ebelong one-key smart switch (2MH8, EWS51-HM).

Vendor H5 bundle (``2MH8/h5_001``, webpack, all logic in ``main.js``) serves
the whole Ebelong switch family (1/4/6-key; the mock entry is EWS56-HM
prodId 2K81) and branches on the key count reported by a ``NumKey``-suffixed
service.  For the one-key 2MH8 the important evidence:

* The relay output is ``switch1.on`` (1 开 / 0 关).  The multi-key home card
  toggles it via ``handlePowerSwitch`` → ``{switch1:{on:0|1, name}}``; the
  ``name`` is only echoed there because the same card hosts the rename
  entry, and the single-field form is what every other payload on this
  device uses (``mode1``/``led``/``memorySwitch`` are all single-field), so
  the adapter sends ``{switch1:{on:N}}`` only.
* ``mode1.mode`` (1 开关模式 / 2 联动模式) — the linkage page's per-key
  ``SwitchBtn`` dispatches ``{mode1:{mode: on ? 2 : 1}}``.  In 联动模式 the
  physical key fires cloud scenes instead of driving the relay.
* ``sceneButton1.mode`` (1 单击 / 2 双击 / 3 长按) — the 场景按键1 dialog
  (``sceneKeysSave``) writes ``{sceneButton1:{mode:N, name}}``: it selects
  which gesture of the key triggers the bound scene.
* ``memorySwitch.status`` (0 关 / 1 开 / 2 保持上次状态) — the 断电记忆
  dialog (``outageSave``) writes ``{memorySwitch:{status:N}}``.
* ``led.led`` (0-100) — the 背光亮度 slider writes ``{led:{led:N}}``.
* ``Pair.Pair`` / ``CleanPair.CleanPair`` — the 配对 / 清除配对 dialogs
  write ``{Pair:{Pair:0}}`` / ``{CleanPair:{CleanPair:0}}`` (value 0 =
  配对按键1, the only key on this product).

Deliberately NOT exposed:

* ``timer`` — the H5 timing page manages entries itself with a complex
  array payload (``{timer:{timer:[{id,start,end,week,para,enable,...}],
  action:0|1|2}}``: UTC times + week bitmask + per-entry ids).  Home
  Assistant scheduling belongs in HA automations; mirroring this payload
  without the vendor UI round-trip is guesswork.
* ``update`` — OTA (check/launch upgrade), app-managed.
* ``netInfo`` — diagnostics, consistent with the other adapters.
* ``name`` / ``room`` characteristics — renaming belongs to HA; the H5
  only sends them alongside the value it changes.
"""

from __future__ import annotations

from typing import Any, Mapping

from .api import EntitySpec
from .context import DeviceContext

_SWITCH_SID = "switch1"
_SWITCH_FIELD = "on"

_MODE_SID = "mode1"
_MODE_FIELD = "mode"
_MODE_OPTIONS = ("开关模式", "联动模式")
_MODE_VALUES = (1, 2)  # Profile/H5 schema range [1,2]

_SCENE_SID = "sceneButton1"
_SCENE_FIELD = "mode"
_SCENE_OPTIONS = ("单击", "双击", "长按")
_SCENE_VALUES = (1, 2, 3)

_MEMORY_SID = "memorySwitch"
_MEMORY_FIELD = "status"
_MEMORY_OPTIONS = ("关闭", "开启", "保持上次状态")
_MEMORY_VALUES = (0, 1, 2)

_LED_SID = "led"
_LED_FIELD = "led"
_LED_RANGE = (0.0, 100.0)

_PAIR_SID = "Pair"
_PAIR_FIELD = "Pair"
_PAIR_VALUE = 0  # 配对按键1 — the only key on this product

_CLEAN_SID = "CleanPair"
_CLEAN_FIELD = "CleanPair"
_CLEAN_VALUE = 0  # 清除按键1


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


def _switch_action(on: int):
    async def action(ctx: DeviceContext, data: Mapping[str, Any]) -> None:
        await ctx.async_send_service(_SWITCH_SID, {_SWITCH_FIELD: on})

    return action


def _enum_state(
    context: DeviceContext,
    sid: str,
    field: str,
    options: tuple[str, ...],
    values: tuple[int, ...],
) -> str | None:
    """Map a reported enum value onto its label; unknown values stay unknown.

    The device may report the Profile's string form ("1") or an int.
    """

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


class Product2MH8Adapter:
    """Ebelong one-key smart switch (2MH8)."""

    prod_id = "2MH8"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        entities: list[EntitySpec] = []

        # --- relay output -------------------------------------------------
        if context.has_service(_SWITCH_SID) and _field(
            profile, _SWITCH_SID, _SWITCH_FIELD
        ) is not None:
            entities.append(
                EntitySpec(
                    platform="switch",
                    key="power_switch",
                    name="电源开关",
                    state=lambda ctx: {
                        "is_on": _flag_value(ctx.value(_SWITCH_SID, _SWITCH_FIELD))
                    },
                    metadata={},
                    actions={
                        "turn_on": _switch_action(1),
                        "turn_off": _switch_action(0),
                    },
                )
            )

        # --- key mode: relay vs linkage -----------------------------------
        if context.has_service(_MODE_SID) and _field(
            profile, _MODE_SID, _MODE_FIELD
        ) is not None:
            entities.append(
                self._enum_select(
                    "key_mode",
                    "按键模式",
                    _MODE_SID,
                    _MODE_FIELD,
                    _MODE_OPTIONS,
                    _MODE_VALUES,
                )
            )

        # --- scene key trigger gesture ------------------------------------
        if context.has_service(_SCENE_SID) and _field(
            profile, _SCENE_SID, _SCENE_FIELD
        ) is not None:
            entities.append(
                self._enum_select(
                    "scene_key_trigger",
                    "场景按键触发方式",
                    _SCENE_SID,
                    _SCENE_FIELD,
                    _SCENE_OPTIONS,
                    _SCENE_VALUES,
                )
            )

        # --- power-loss memory --------------------------------------------
        if context.has_service(_MEMORY_SID) and _field(
            profile, _MEMORY_SID, _MEMORY_FIELD
        ) is not None:
            entities.append(
                self._enum_select(
                    "power_loss_memory",
                    "断电记忆",
                    _MEMORY_SID,
                    _MEMORY_FIELD,
                    _MEMORY_OPTIONS,
                    _MEMORY_VALUES,
                )
            )

        # --- backlight brightness ------------------------------------------
        if context.has_service(_LED_SID) and _field(
            profile, _LED_SID, _LED_FIELD
        ) is not None:
            async def _led_action(ctx: DeviceContext, data: Mapping[str, Any]) -> None:
                value = _number(data.get("value"))
                if value is None:
                    return
                low, high = _LED_RANGE
                await ctx.async_send_service(
                    _LED_SID, {_LED_FIELD: int(_clamp(value, low, high))}
                )

            entities.append(
                EntitySpec(
                    platform="number",
                    key="backlight_brightness",
                    name="背光亮度",
                    state=lambda ctx: {"value": _number(
                        ctx.value(_LED_SID, _LED_FIELD)
                    )},
                    metadata={"min": _LED_RANGE[0], "max": _LED_RANGE[1], "step": 1.0},
                    actions={"set_value": _led_action},
                )
            )

        # --- pair / clear pair ---------------------------------------------
        if context.has_service(_PAIR_SID) and _field(
            profile, _PAIR_SID, _PAIR_FIELD
        ) is not None:
            async def _pair_action(ctx: DeviceContext, data: Mapping[str, Any]) -> None:
                await ctx.async_send_service(_PAIR_SID, {_PAIR_FIELD: _PAIR_VALUE})

            entities.append(
                EntitySpec(
                    platform="button",
                    key="pair",
                    name="配对",
                    state=lambda ctx: {},
                    metadata={},
                    actions={"press": _pair_action},
                )
            )

        if context.has_service(_CLEAN_SID) and _field(
            profile, _CLEAN_SID, _CLEAN_FIELD
        ) is not None:
            async def _clean_action(ctx: DeviceContext, data: Mapping[str, Any]) -> None:
                await ctx.async_send_service(_CLEAN_SID, {_CLEAN_FIELD: _CLEAN_VALUE})

            entities.append(
                EntitySpec(
                    platform="button",
                    key="clear_pair",
                    name="清除配对",
                    state=lambda ctx: {},
                    metadata={},
                    actions={"press": _clean_action},
                )
            )

        return tuple(entities)

    def _enum_select(
        self,
        key: str,
        name: str,
        sid: str,
        field: str,
        options: tuple[str, ...],
        values: tuple[int, ...],
    ) -> EntitySpec:
        async def action(ctx: DeviceContext, data: Mapping[str, Any]) -> None:
            option = data.get("option")
            value = _enum_payload(option, options, values)
            if value is None:
                return
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


ADAPTER = Product2MH8Adapter()
