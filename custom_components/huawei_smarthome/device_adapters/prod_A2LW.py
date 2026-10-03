"""A2LW 酷宅科技温湿度传感器 (TH Sensor), read-only.

The Profile labels current in Celsius / percent without a multiplier.
The observed cloud shadow reports temperature=28, humidity=43, not tenths.
Do not infer a /10 scale from the broad -100..400 / 0..1000 schema bounds.
"""

from .api import EntitySpec
from .context import DeviceContext
from .profile_fields import field, sensor


class ProductA2LWAdapter:
    prod_id = "A2LW"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        entities = []
        for sid, name, unit in (("temperature", "温度", "°C"), ("humidity", "湿度", "%")):
            if field(context, sid, "current"):
                entities.append(sensor(sid, name, sid, "current", metadata={
                    "unit": unit, "device_class": sid, "state_class": "measurement",
                }))
        return tuple(entities)


ADAPTER = ProductA2LWAdapter()
