"""2J6Y 达伦智能台灯3i (DL-01W Pro).

Profile: device/guide/2J6Y/2J6Y.json on smarthome-drcn.dbankcdn.com.
Main light and night light are separate; switch.on is the overall power.
backlight writes retain the other reported field to avoid changing both at once.
No colour-temperature control: this product only declares brightness 0..100.
"""

from .api import EntitySpec
from .context import DeviceContext
from .profile_fields import field, numeric, select, sensor, switch


class Product2J6YAdapter:
    prod_id = "2J6Y"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        entities = []
        for key, name, sid in (("power", "电源", "switch"),
                               ("main_light", "主灯", "mainSwitch"),
                               ("indicator", "指示灯", "indicator")):
            if field(context, sid, "on"):
                entities.append(switch(context, key, name, sid))
        if field(context, "brightness", "brightness"):
            entities.append(numeric(context, "brightness", "亮度", "brightness",
                                    "brightness", unit="%"))
        for key, name, sid, attr in (("light_mode", "灯光模式", "lightMode", "mode"),
                                      ("fade_time", "渐灭延时", "fadeTime", "time")):
            if field(context, sid, attr):
                entities.append(select(context, key, name, sid, attr))
        if field(context, "backlight", "on") and field(context, "backlight", "brightness"):
            entities.append(switch(context, "night_light", "夜灯", "backlight",
                                   preserve=("brightness",)))
            entities.append(select(context, "night_brightness", "夜灯亮度", "backlight",
                                   "brightness", preserve=("on",)))
        if field(context, "lightStatus", "status"):
            entities.append(sensor("light_status", "灯光状态", "lightStatus", "status", kind="enum"))
        return tuple(entities)


ADAPTER = Product2J6YAdapter()
