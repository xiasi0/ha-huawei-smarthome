"""20I0 欧普智能台灯 Pro (MT615-D20WTT).

Profile: device/guide/20I0/20I0.json on smarthome-drcn.dbankcdn.com.
Brightness is the native 3..255 value, NOT percent; CCT is 3000..5000 K.
Only independent lighting controls are exposed. Study sessions, schedules and
night-mode times require compound payloads and are intentionally omitted.
"""

from .api import EntitySpec
from .context import DeviceContext
from .profile_fields import field, numeric, select, switch


class Product20I0Adapter:
    prod_id = "20I0"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        entities = []
        if field(context, "switch", "on"):
            entities.append(switch(context, "power", "电源", "switch"))
        if field(context, "brightness", "brightness"):
            entities.append(numeric(context, "brightness", "亮度",
                                    "brightness", "brightness"))
        if field(context, "cct", "colorTemperature"):
            entities.append(numeric(context, "color_temp", "色温", "cct",
                                    "colorTemperature", unit="K"))
        if field(context, "lightMode", "mode"):
            entities.append(select(context, "light_mode", "灯光模式", "lightMode", "mode"))
        return tuple(entities)


ADAPTER = Product20I0Adapter()
