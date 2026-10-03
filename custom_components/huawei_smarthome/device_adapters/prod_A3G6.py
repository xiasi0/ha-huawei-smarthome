"""A3G6 美的十字四门冰箱 (observed model 310A1394).

The product Profile declares freezer target -24..-16 C and fridge target
2..8 C, both in whole degrees, plus quick-freeze/quick-cool switches.
These switches are modes, NOT appliance power. No main-power entity is created.
Only target temperatures are reported; do not label them as measured temperature.
Cloud state verified; setting changes still require physical verification.
"""

from .api import EntitySpec
from .context import DeviceContext
from .profile_fields import field, numeric, sensor, switch


class ProductA3G6Adapter:
    prod_id = "A3G6"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        entities = []
        for key, name, sid in (("freezer_target", "冷冻设定温度", "freezerFloat"),
                               ("fridge_target", "冷藏设定温度", "refrigeratorFloat")):
            if field(context, sid, "target"):
                entities.append(numeric(context, key, name, sid, "target", unit="°C"))
        for key, name, sid in (("quick_freeze", "速冻模式", "freezeSwitch"),
                               ("quick_cool", "速冷模式", "refrigerateSwitch")):
            if field(context, sid, "on"):
                entities.append(switch(context, key, name, sid))
        if field(context, "commonFaultDetection", "status"):
            entities.append(sensor("problem", "故障", "commonFaultDetection", "status",
                                   kind="bool", metadata={"device_class": "problem"}))
        if field(context, "commonFaultDetection", "code"):
            entities.append(sensor("fault_code", "故障详情", "commonFaultDetection", "code", kind="enum"))
        return tuple(entities)


ADAPTER = ProductA3G6Adapter()
