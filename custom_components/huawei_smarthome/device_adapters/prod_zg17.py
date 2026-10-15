"""Huawei ZG17 adjustable light belt: on/off, brightness and color temperature.

Only the three directly reported and writable services are exposed.  The
relative-brightness and fade-time services are left unchanged.
"""

import math
from collections.abc import Mapping

from .api import EntitySpec


def _field(context, sid, key):
    profile = context.profile
    if not isinstance(profile, Mapping):
        return None
    if str(profile.get("prodId", "ZG17")).casefold() != "zg17":
        return None
    for service in profile.get("services", ()):
        if not isinstance(service, Mapping) or service.get("serviceId") != sid:
            continue
        for item in service.get("characteristics", ()):
            if isinstance(item, Mapping) and item.get("characteristicName") == key:
                return item
    return None


def _writable(context, sid, key):
    item = _field(context, sid, key)
    return bool(item and "W" in item.get("method", ""))


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _valid_integer(value, schema):
    number = _number(value)
    if number is None or not number.is_integer():
        return None
    integer = int(number)
    low = _number(schema.get("min"))
    high = _number(schema.get("max"))
    step = _number(schema.get("step"))
    if low is not None and integer < low or high is not None and integer > high:
        return None
    if low is not None and step and not math.isclose((integer - low) % step, 0):
        return None
    return integer


def _reported_integer(context, sid, key):
    schema = _field(context, sid, key)
    return _valid_integer(context.value(sid, key), schema) if schema else None


def _state(context):
    switch = context.value("switch", "on")
    if switch in (0, "0", False):
        is_on = False
    elif switch in (1, "1", True):
        is_on = True
    else:
        is_on = None
    brightness = _reported_integer(context, "brightness", "brightness")
    return {
        "is_on": is_on,
        "brightness": round(brightness * 255 / 100) if brightness is not None else None,
        "color_temp_kelvin": _reported_integer(context, "cct", "colorTemperature"),
        "color_mode": "color_temp",
    }


def _command_integer(context, sid, key, value):
    if not _writable(context, sid, key):
        raise ValueError(f"ZG17 Profile does not permit writing {sid}.{key}")
    schema = _field(context, sid, key)
    result = _valid_integer(value, schema)
    if result is None:
        raise ValueError(f"Invalid ZG17 {sid}.{key} command")
    return result


async def _send(context, sid, key, value):
    await context.async_send_service(sid, {key: _command_integer(context, sid, key, value)})


async def _turn_on(context, data):
    if data.get("rgb_color") is not None:
        raise ValueError("ZG17 Profile has no verified RGB control")
    brightness = data.get("brightness")
    temperature = data.get("color_temp_kelvin")
    brightness_command = None
    temperature_command = None

    if brightness is not None:
        amount = _number(brightness)
        if amount is None or not 0 <= amount <= 255:
            raise ValueError("Invalid Home Assistant brightness")
        if amount == 0:
            brightness_command = 0
        else:
            brightness_command = max(1, round(amount * 100 / 255))
            _command_integer(context, "brightness", "brightness", brightness_command)
    if temperature is not None:
        kelvin = _number(temperature)
        schema = _field(context, "cct", "colorTemperature")
        if kelvin is None or not schema or not _writable(context, "cct", "colorTemperature"):
            raise ValueError("Invalid ZG17 color temperature")
        low, high = int(schema["min"]), int(schema["max"])
        step = int(schema["step"])
        if not low <= kelvin <= high:
            raise ValueError("ZG17 color temperature is outside its Profile range")
        temperature_command = low + round((kelvin - low) / step) * step
        _command_integer(context, "cct", "colorTemperature", temperature_command)

    _command_integer(context, "switch", "on", 1)
    if brightness_command == 0:
        await _turn_off(context, {})
        return
    await _send(context, "switch", "on", 1)
    if brightness_command is not None:
        await _send(context, "brightness", "brightness", brightness_command)
    if temperature_command is not None:
        await _send(context, "cct", "colorTemperature", temperature_command)


async def _turn_off(context, data):
    del data
    await _send(context, "switch", "on", 0)


class ProductAdapter:
    prod_id = "ZG17"

    def entities(self, context):
        if (context.prod_id or "").casefold() != self.prod_id.casefold():
            return ()
        fields = (("switch", "on"), ("brightness", "brightness"),
                  ("cct", "colorTemperature"))
        if not all(_writable(context, sid, key) for sid, key in fields):
            return ()
        cct = _field(context, "cct", "colorTemperature")
        return (EntitySpec(
            platform="light", key="light", name="灯带", state=_state,
            metadata={
                "supported_color_modes": {"color_temp"},
                "min_color_temp_kelvin": int(cct["min"]),
                "max_color_temp_kelvin": int(cct["max"]),
            },
            actions={"turn_on": _turn_on, "turn_off": _turn_off},
        ),)


ADAPTER = ProductAdapter()
