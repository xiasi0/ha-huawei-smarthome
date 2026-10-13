"""Independent adapter for OPPLE OP-IDNCD0100300P2 (2N3T).

Explicit Profile mappings: switch.on 0/1, brightness.brightness 1-100,
cct.colorTemperature 2700-6500 K. No subProduct gating for this product.
Preserves existing fade, dimming-curve and power-memory settings.
"""

import math

from .api import EntitySpec


def _field(ctx, sid, key):
    for service in (ctx.profile or {}).get("services", []):
        if service.get("serviceId") == sid:
            return next(
                (
                    f
                    for f in service.get("characteristics", [])
                    if f.get("characteristicName") == key
                ),
                None,
            )
    return None


def _number(value):
    try:
        if isinstance(value, bool):
            return None
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _boolean(value):
    if value in (0, "0", False):
        return False
    if value in (1, "1", True):
        return True
    return None


def _numeric(ctx, sid, key):
    value = _number(ctx.value(sid, key))
    schema = _field(ctx, sid, key)
    if value is None or not schema:
        return None
    low, high = (_number(schema.get("min")), _number(schema.get("max")))
    if low is not None and value < low or (high is not None and value > high):
        return None
    return value


def _writable(ctx, sid, key):
    schema = _field(ctx, sid, key)
    return bool(schema and "W" in schema.get("method", ""))


def _validate(ctx, sid, key, value):
    schema = _field(ctx, sid, key)
    if not _writable(ctx, sid, key):
        raise ValueError(f"Profile does not permit writing {sid}.{key}")
    kind = schema.get("characteristicType")
    if kind in ("int", "float", "double", "bool", "enum"):
        parsed = _number(value)
        if parsed is None:
            raise ValueError("A finite numeric command is required")
        if kind in ("int", "bool", "enum"):
            if not parsed.is_integer():
                raise ValueError("An integer command is required")
            value = int(parsed)
        else:
            value = parsed
        low, high = (_number(schema.get("min")), _number(schema.get("max")))
        if low is not None and value < low or (high is not None and value > high):
            raise ValueError("Command is outside the product Profile range")
        step = _number(schema.get("step"))
        if (
            step
            and low is not None
            and (
                not math.isclose(
                    (value - low) / step, round((value - low) / step), abs_tol=1e-06
                )
            )
        ):
            raise ValueError("Command does not match the product Profile step")
    if kind == "string" and (not isinstance(value, str)):
        raise ValueError("A string command is required")
    choices = schema.get("enumList", [])
    if choices and str(value) not in {str(e["enumVal"]) for e in choices}:
        raise ValueError("Command is not in the product Profile enum")
    return value


async def _send(ctx, sid, key, value):
    value = _validate(ctx, sid, key, value)
    await ctx.async_send_service(sid, {key: value})


def _quantize(ctx, sid, key, value):
    schema = _field(ctx, sid, key)
    value = _number(value)
    if schema is None or value is None:
        raise ValueError("Missing numeric Profile or invalid input")
    low, high = (float(schema["min"]), float(schema["max"]))
    step = float(schema.get("step") or 1)
    return int(max(low, min(high, low + round((value - low) / step) * step)))


def _lights(ctx):
    if not _writable(ctx, "switch", "on"):
        return ()
    dim = _writable(ctx, "brightness", "brightness")
    cct = dim and _writable(ctx, "cct", "colorTemperature")
    metadata = {
        "supported_color_modes": {
            "color_temp" if cct else "brightness" if dim else "onoff"
        }
    }
    if cct:
        schema = _field(ctx, "cct", "colorTemperature")
        metadata.update(
            min_color_temp_kelvin=int(schema["min"]),
            max_color_temp_kelvin=int(schema["max"]),
        )

    def state(c):
        brightness = _numeric(c, "brightness", "brightness") if dim else None
        return {
            "is_on": _boolean(c.value("switch", "on")),
            "brightness": round(brightness * 255 / 100)
            if brightness is not None
            else None,
            "color_temp_kelvin": _numeric(c, "cct", "colorTemperature")
            if cct
            else None,
            "color_mode": next(iter(metadata["supported_color_modes"])),
        }

    async def on(c, data):
        brightness, temperature = (None, None)
        if data.get("brightness") is not None:
            if (
                not dim
                or _number(data["brightness"]) is None
                or (not 0 <= float(data["brightness"]) <= 255)
            ):
                raise ValueError("Unsupported or invalid brightness")
            brightness = _quantize(
                c, "brightness", "brightness", float(data["brightness"]) * 100 / 255
            )
        if data.get("color_temp_kelvin") is not None:
            if not cct:
                raise ValueError("Color temperature is unsupported")
            temperature = _quantize(
                c, "cct", "colorTemperature", data["color_temp_kelvin"]
            )
        if data.get("rgb_color") is not None:
            raise ValueError("RGB has not been verified for this product")
        _validate(c, "switch", "on", 1)
        if brightness is not None:
            _validate(c, "brightness", "brightness", brightness)
        if temperature is not None:
            _validate(c, "cct", "colorTemperature", temperature)
        if data.get("brightness") is not None and float(data["brightness"]) == 0:
            await off(c, {})
            return
        await _send(c, "switch", "on", 1)
        if brightness is not None:
            await _send(c, "brightness", "brightness", brightness)
        if temperature is not None:
            await _send(c, "cct", "colorTemperature", temperature)

    async def off(c, data):
        await _send(c, "switch", "on", 0)

    return (
        EntitySpec(
            "light", "light", "灯", state, metadata, {"turn_on": on, "turn_off": off}
        ),
    )


class ProductAdapter:
    prod_id = "2N3T"

    def entities(self, context):
        if (context.prod_id or "").casefold() != self.prod_id.casefold():
            return ()
        return _lights(context)


ADAPTER = ProductAdapter()
