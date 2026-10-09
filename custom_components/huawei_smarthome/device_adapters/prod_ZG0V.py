"""Huawei ZG0V Light Belt: Profile-defined switch/on control only.

ZG0V.json declares a bool RW switch/on with 0 (off) and 1 (on).
The bundled official service/data references (version 11) have no ZG0V
override. Commands and state mapping still require real-device validation.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext


_PROD_ID = "ZG0V"
_SWITCH_SID = "switch"
_ON_FIELD = "on"


def _switch_field(context: DeviceContext) -> Mapping[str, Any] | None:
    """Require this product's writable boolean field before exposing control."""

    if (context.prod_id or "").casefold() != _PROD_ID.casefold():
        return None
    profile = context.profile
    if not isinstance(profile, Mapping):
        return None
    profile_prod_id = profile.get("prodId")
    if profile_prod_id is not None and (
        not isinstance(profile_prod_id, str)
        or profile_prod_id.casefold() != _PROD_ID.casefold()
    ):
        return None
    services = profile.get("services")
    if not isinstance(services, list) or not context.has_service(_SWITCH_SID):
        return None
    for service in services:
        if not isinstance(service, Mapping) or service.get("serviceId") != _SWITCH_SID:
            continue
        fields = service.get("characteristics")
        if not isinstance(fields, list):
            return None
        for field in fields:
            if (
                not isinstance(field, Mapping)
                or field.get("characteristicName") != _ON_FIELD
            ):
                continue
            if field.get("characteristicType") != "bool":
                return None
            if field.get("method") not in ("W", "RW"):
                return None
            return field
    return None


def _state(context: DeviceContext) -> Mapping[str, Any]:
    value = context.value(_SWITCH_SID, _ON_FIELD)
    is_on = None
    if value in (0, "0", False):
        is_on = False
    elif value in (1, "1", True):
        is_on = True
    return {"is_on": is_on, "color_mode": "onoff"}


async def _send_switch(context: DeviceContext, value: int) -> None:
    field = _switch_field(context)
    if field is None:
        raise ValueError("ZG0V Profile does not permit writing switch.on")
    # has_service() also accepts Profile-only services. Require the cloud
    # snapshot or a received state report to confirm the actual command sid.
    if (
        _SWITCH_SID not in context.descriptor.service_states
        and not context.service_state(_SWITCH_SID)
    ):
        raise ValueError("ZG0V switch service has not been reported by the device")
    choices = field.get("enumList", [])
    if not isinstance(choices, list) or (
        choices
        and not any(
            isinstance(choice, Mapping) and choice.get("enumVal") == value
            for choice in choices
        )
    ):
        raise ValueError("Command is not in the ZG0V Profile enum")
    await context.async_send_service(_SWITCH_SID, {_ON_FIELD: value})


async def _turn_on(context: DeviceContext, data: Mapping[str, Any]) -> None:
    if any(
        data.get(key) is not None
        for key in ("brightness", "color_temp_kelvin", "rgb_color")
    ):
        raise ValueError("ZG0V only supports on/off")
    await _send_switch(context, 1)


async def _turn_off(context: DeviceContext, data: Mapping[str, Any]) -> None:
    del data
    await _send_switch(context, 0)


class ProductZG0VAdapter:
    """Expose one on/off light for the Huawei Light Belt."""

    prod_id = _PROD_ID

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if _switch_field(context) is None:
            return ()
        return (
            EntitySpec(
                platform="light",
                key="light",
                name="灯带",
                state=_state,
                metadata={"supported_color_modes": {"onoff"}},
                actions={"turn_on": _turn_on, "turn_off": _turn_off},
            ),
        )


ADAPTER = ProductZG0VAdapter()
