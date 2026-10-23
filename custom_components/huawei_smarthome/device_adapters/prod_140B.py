"""Independent 140B adapter with explicit product service mappings.

Field mappings and command validation are local to this product.
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


def _sensor(
    ctx,
    sid,
    key,
    name,
    *,
    unit=None,
    device_class=None,
    binary=False,
    enum=False,
    scale=1,
):
    schema = _field(ctx, sid, key)
    if schema is None or "R" not in schema.get("method", ""):
        return None
    metadata = {}
    if unit:
        metadata["unit"] = unit
    if device_class:
        metadata["device_class"] = device_class

    def state(c):
        raw = c.value(sid, key)
        if binary:
            return {"is_on": _boolean(raw)}
        if enum:
            value = next(
                (
                    v.get("descCh") or str(raw)
                    for v in schema.get("enumList", [])
                    if str(v.get("enumVal")) == str(raw)
                ),
                None,
            )
        else:
            value = _numeric(c, sid, key)
            if value is not None:
                value = value / 10 if scale == 0.1 else value * scale
        return {"native_value": value}

    return EntitySpec(
        "binary_sensor" if binary else "sensor",
        f"{sid}_{key}",
        name,
        state,
        metadata=metadata,
    )


def _covers(ctx):
    sid = key = "mode"
    schema = _field(ctx, sid, key)
    if not schema or not _writable(ctx, sid, key):
        return ()
    labels = {
        int(e["enumVal"]): e.get("descCh", "").strip()
        for e in schema.get("enumList", [])
    }
    if (
        labels.get(0) not in ("关", "关闭窗帘")
        or labels.get(1) not in ("开", "打开窗帘")
        or labels.get(2) not in ("停止", "暂停")
    ):
        return ()
    actions = {}
    for name, value in (("open", 1), ("close", 0), ("stop", 2)):

        async def action(c, data, value=value):
            await _send(c, sid, key, value)

        actions[name] = action
    # ``opener.current`` carries ``report: 0`` in the 140B Profile, i.e. the
    # device never pushes its real opening percentage.  Only offer position
    # control when the position is actually reported back, otherwise the
    # slider and the derived open/closed state would both be fiction.
    positions = bool((_field(ctx, "opener", "current") or {}).get("report"))
    if positions and _writable(ctx, "opener", "target"):

        async def position(c, data):
            await _send(c, "opener", "target", data["position"])

        actions["set_position"] = position

    def state(c):
        value = _numeric(c, "opener", "current") if positions else None
        return {
            "current_position": int(value) if value is not None else None,
            "is_closed": value == 0 if value is not None else None,
        }

    result = [
        EntitySpec(
            "cover", "curtain", "窗帘", state, {"device_class": "curtain"}, actions
        )
    ]
    if not positions:
        result.append(_sensor(ctx, "opener", "current", "位置原始值", unit="%"))
    return tuple((e for e in result if e))


class ProductAdapter:
    prod_id = "140B"

    def entities(self, context):
        if (context.prod_id or "").casefold() != self.prod_id.casefold():
            return ()
        return _covers(context)


ADAPTER = ProductAdapter()
