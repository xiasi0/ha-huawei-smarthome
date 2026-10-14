"""OP-CBX-6O2I-PLC: execute existing dry-contact functions and read inputs.

The controller stores up to 20 functions combining six outputs and delays.
Only already-configured functions are exposed as momentary buttons. Executing
one sends on=1 without rewriting port masks, delays, defaults or names.
Input ports 7/8 report electrical contact state, not door/cover position.
Changes to the configured function list/names require an integration reload.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TYPE_CHECKING

from .api import EntitySpec

if TYPE_CHECKING:
    from .context import DeviceContext


def _field(context: DeviceContext, sid: str, name: str) -> Mapping[str, Any]:
    profile = context.profile
    if not isinstance(profile, Mapping):
        return {}
    for service in profile.get("services", ()):
        if not isinstance(service, Mapping) or service.get("serviceId") != sid:
            continue
        for field in service.get("characteristics", ()):
            if isinstance(field, Mapping) and field.get("characteristicName") == name:
                return field
    return {}


def _configured(context: DeviceContext, sid: str) -> bool:
    raw = context.value(sid, "dryContactCfg")
    if isinstance(raw, bool):
        return False
    if isinstance(raw, str):
        try:
            raw = int(raw)
        except ValueError:
            return False
    # Firmware may report undocumented high bits. Do not reconstruct or write
    # this value: only inspect the six documented output-selection bits.
    return isinstance(raw, int) and 0 < raw <= 0xFFFFFFFF and bool(raw & 0x3F)


def _can_execute(context: DeviceContext, sid: str) -> bool:
    field = _field(context, sid, "on")
    return (
        "W" in str(field.get("method", ""))
        and field.get("characteristicType") == "bool"
        and any(
            isinstance(item, Mapping) and str(item.get("enumVal")) == "1"
            for item in field.get("enumList", ())
        )
        and _configured(context, sid)
    )


def _empty_state(context: DeviceContext) -> Mapping[str, Any]:
    return {}


def _function(context: DeviceContext, sid: str, index: int) -> EntitySpec:
    raw_name = context.value(sid, "name")
    name = raw_name.strip() if isinstance(raw_name, str) else ""

    def available(device: DeviceContext) -> bool:
        return device.available and _can_execute(device, sid)

    async def press(device: DeviceContext, data: Mapping[str, Any]) -> None:
        if not available(device):
            raise ValueError("dry-contact function is offline, unconfigured or not writable")
        await device.async_send_service(sid, {"on": 1})

    return EntitySpec(
        platform="button", key=sid, name=name or f"干接点功能 {index}",
        state=_empty_state, actions={"press": press}, availability=available,
    )


def _input(sid: str, index: int) -> EntitySpec:
    def state(context: DeviceContext) -> Mapping[str, Any]:
        value = context.value(sid, "status")
        if isinstance(value, (str, int, bool)):
            if value in (1, "1", True):
                return {"is_on": True}
            if value in (0, "0", False):
                return {"is_on": False}
        return {"is_on": None}

    return EntitySpec(
        platform="binary_sensor", key=sid, name=f"输入接点 {index}",
        state=state,
    )


class Product2MJXAdapter:
    prod_id = "2MJX"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.prod_id != self.prod_id or not context.profile:
            return ()
        entities = []
        for index in range(1, 21):
            sid = f"dryContactFunc{index}"
            if _can_execute(context, sid):
                entities.append(_function(context, sid, index))
        for index in (7, 8):
            sid = f"dryContact{index}"
            if "R" in str(_field(context, sid, "status").get("method", "")):
                entities.append(_input(sid, index))
        return tuple(entities)


ADAPTER = Product2MJXAdapter()
