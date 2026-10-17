"""Read-only Huawei BER-SE11 (ZG1Z) presence and ambient light.

Profile fields basicFenceEvent.existent and luminance.current/level were
observed on hardware. Invalid or missing values remain unknown. No sensing
configuration, reset action, or unverified sub-zone is exposed.
The device owner confirmed the light unit is lux. Readings are exposed
in lx without scaling. Presence transitions were tested on two devices.
"""
from .api import EntitySpec

_LEVELS = {1: "暗光", 2: "弱光", 3: "适中", 4: "较强", 5: "强", 6: "很强"}


def _presence(context):
    value = context.value("basicFenceEvent", "existent")
    valid = type(value) in (bool, int) and value in (0, 1)
    return {"is_on": bool(value) if valid else None}


def _illuminance(context):
    value = context.value("luminance", "current")
    valid = type(value) is int and 0 <= value <= 65535
    return {"native_value": value if valid else None}


def _level(context):
    value = context.value("luminance", "level")
    return {"native_value": _LEVELS.get(value) if type(value) is int else None}


class ProductAdapter:
    prod_id = "ZG1Z"

    def entities(self, context):
        if (context.prod_id or "").casefold() != self.prod_id.casefold():
            return ()
        return (
            EntitySpec(
                platform="binary_sensor", key="presence", name="人员存在",
                state=_presence, metadata={"device_class": "occupancy"},
            ),
            EntitySpec(
                platform="sensor", key="illuminance", name="光照度",
                state=_illuminance, metadata={"state_class": "measurement", "unit": "lx",
                                            "device_class": "illuminance"},
            ),
            EntitySpec(
                platform="sensor", key="illuminance_level", name="光照度等级",
                state=_level,
            ),
        )


ADAPTER = ProductAdapter()
