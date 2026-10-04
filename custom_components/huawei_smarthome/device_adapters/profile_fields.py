"""Field helpers for explicitly selected product entities.

These helpers never discover products or create entities from a whole Profile.
Each product adapter must select its own verified services and fields.
"""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite, isclose
from typing import Any

from .api import EntitySpec
from .context import DeviceContext


def number(value: Any) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not isfinite(result):
        return None
    return int(result) if result.is_integer() else result


def boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        value = value.strip().lower()
        if value in {"true", "on"}:
            return True
        if value in {"false", "off"}:
            return False
    value = number(value)
    return bool(value) if value in (0, 1) else None


def field(context: DeviceContext, sid: str, name: str) -> Mapping[str, Any]:
    for service in (context.profile or {}).get("services") or ():
        if isinstance(service, Mapping) and service.get("serviceId") == sid:
            for item in service.get("characteristics") or ():
                if isinstance(item, Mapping) and item.get("characteristicName") == name:
                    return item
    return {}


def writable(context: DeviceContext, sid: str, name: str) -> bool:
    definition = field(context, sid, name)
    # New Profiles use permission=P; older ones use method=W/RW.
    permission = definition.get("permission")
    if permission is not None:
        return "P" in str(permission)
    return "W" in str(definition.get("method") or "")


def enum_label(context: DeviceContext, sid: str, name: str, value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list, bool)):
        return None
    for option in field(context, sid, name).get("enumList") or ():
        if isinstance(option, Mapping) and str(option.get("enumVal")) == str(value):
            return str(option.get("descCh") or option.get("descEn") or value).strip()
    return str(value).strip() or None


def sensor(key: str, name: str, sid: str, attr: str, *, kind: str = "number",
           metadata: Mapping[str, Any] | None = None) -> EntitySpec:
    def read(device: DeviceContext) -> Mapping[str, Any]:
        value = device.value(sid, attr)
        if kind == "enum":
            value = enum_label(device, sid, attr, value)
        elif kind == "number":
            value = number(value)
        elif kind == "bool":
            return {"is_on": boolean(value)}
        elif not isinstance(value, str):
            value = None
        return {"native_value": value}

    return EntitySpec(platform="binary_sensor" if kind == "bool" else "sensor",
                      key=key, name=name, state=read, metadata=metadata or {})


def switch(context: DeviceContext, key: str, name: str, sid: str, attr: str = "on",
           *, preserve: tuple[str, ...] = ()) -> EntitySpec:
    async def send(device: DeviceContext, value: int) -> None:
        body = {attr: value}
        for sibling in preserve:
            current = device.value(sid, sibling)
            if current is None:
                raise ValueError(f"Read {sid}.{sibling} before changing {attr}")
            body[sibling] = current
        await device.async_send_service(sid, body)

    async def turn_on(device: DeviceContext, _data: Mapping[str, Any]) -> None:
        await send(device, 1)

    async def turn_off(device: DeviceContext, _data: Mapping[str, Any]) -> None:
        await send(device, 0)

    can_write = writable(context, sid, attr)
    return EntitySpec(
        platform="switch" if can_write else "binary_sensor", key=key, name=name,
        state=lambda device: {"is_on": boolean(device.value(sid, attr))},
        actions={"turn_on": turn_on, "turn_off": turn_off} if can_write else {},
    )


def numeric(context: DeviceContext, key: str, name: str, sid: str, attr: str,
            *, unit: str | None = None) -> EntitySpec:
    definition = field(context, sid, attr)
    minimum, maximum = number(definition.get("min")), number(definition.get("max"))
    step = number(definition.get("step", 1))
    can_write = (writable(context, sid, attr) and minimum is not None
                 and maximum is not None and minimum < maximum
                 and step is not None and step > 0)

    async def set_value(device: DeviceContext, data: Mapping[str, Any]) -> None:
        value = number(data.get("value"))
        if value is None or not minimum <= value <= maximum:
            raise ValueError(f"{sid}.{attr} must be between {minimum} and {maximum}")
        steps = (value - minimum) / step
        if not isclose(steps, round(steps), abs_tol=1e-7, rel_tol=0):
            raise ValueError(f"{sid}.{attr} must use step {step}")
        await device.async_send_service(sid, {attr: value})

    metadata: dict[str, Any] = {"unit": unit} if unit else {}
    if can_write:
        metadata.update(min=minimum, max=maximum, step=step)
    return EntitySpec(
        platform="number" if can_write else "sensor", key=key, name=name,
        state=lambda device: {"native_value": number(device.value(sid, attr))},
        metadata=metadata, actions={"set_value": set_value} if can_write else {},
    )


def select(context: DeviceContext, key: str, name: str, sid: str, attr: str,
           *, preserve: tuple[str, ...] = ()) -> EntitySpec:
    options: dict[str, int | float] = {}
    seen_values: set[int | float] = set()
    ambiguous = False
    for item in field(context, sid, attr).get("enumList") or ():
        if not isinstance(item, Mapping):
            continue
        value = number(item.get("enumVal"))
        label = str(item.get("descCh") or item.get("descEn") or "").strip()
        if value is None or not label:
            continue
        if label in options or value in seen_values:
            ambiguous = True
        options[label] = value
        seen_values.add(value)
    if ambiguous or not options or not writable(context, sid, attr):
        return sensor(key, name, sid, attr, kind="enum")

    async def choose(device: DeviceContext, data: Mapping[str, Any]) -> None:
        option = data.get("option")
        if not isinstance(option, str) or option not in options:
            raise ValueError(f"Unsupported {sid}.{attr} option")
        body = {attr: options[option]}
        for sibling in preserve:
            current = device.value(sid, sibling)
            if current is None:
                raise ValueError(f"Read {sid}.{sibling} before changing {attr}")
            body[sibling] = current
        await device.async_send_service(sid, body)

    def read(device: DeviceContext) -> Mapping[str, Any]:
        value = number(device.value(sid, attr))
        label = next((label for label, code in options.items() if code == value), None)
        return {"current_option": label}

    return EntitySpec(platform="select", key=key, name=name, state=read,
                      metadata={"options": list(options)}, actions={"select_option": choose})
